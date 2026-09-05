"""Network robustness: retries, transient vs permanent image failures, per-blog isolation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

from blog2epub import cli
from blog2epub.config import BlogConfig
from blog2epub.images import fetch_image
from blog2epub.models import PostRef
from blog2epub.sources import SourceError
from blog2epub.sources.feed import FeedSource
from blog2epub.sources.sitemap import SitemapSource
from blog2epub.sources.wordpress import WordPressSource
from blog2epub.sync import SyncResult
from tests.conftest import PNG_1x1
from tests.test_sources import BLOG_HTML, PAGE, FakeClient, FakeResponse, wp_item

PNG_HEADERS = {"Content-Type": "image/png"}
PAGE_RESPONSE = FakeResponse(200, PAGE)


class FlakyBody(FakeResponse):
    """Headers arrive, then the body read fails the first time it is consumed."""

    def __init__(self, failures: int):
        super().__init__(200, PNG_1x1, PNG_HEADERS)
        self.failures = failures

    def iter_content(self, n):
        if self.failures:
            self.failures -= 1
            raise requests.ConnectionError("connection reset while streaming")
        yield self.content


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("blog2epub.images.time.sleep", lambda s: None)


def test_body_failure_is_retried_once(store):
    flaky = FlakyBody(failures=1)
    client = FakeClient(lambda u, p: flaky)
    assert fetch_image(client, store, "https://x/a.png", 10_000_000) is True
    assert client.requests_made == 2 and store.image_path("https://x/a.png") is not None


def test_body_failure_twice_is_transient(store):
    flaky = FlakyBody(failures=5)
    client = FakeClient(lambda u, p: flaky)
    assert fetch_image(client, store, "https://x/a.png", 10_000_000) is False
    entry = store.image_index["https://x/a.png"]
    assert entry["error"] and entry["permanent"] is False
    assert client.requests_made == 2  # exactly one retry, no more
    assert store.image_failed("https://x/a.png") is True  # fresh: not retried yet
    assert fetch_image(client, store, "https://x/a.png", 10_000_000) is False
    assert client.requests_made == 2  # skipped without a request


def test_404_is_permanent_and_never_retried(store):
    client = FakeClient(lambda u, p: FakeResponse(404))
    assert fetch_image(client, store, "https://x/gone.png", 10_000_000) is False
    assert store.image_index["https://x/gone.png"]["permanent"] is True
    assert client.requests_made == 1
    store.image_index["https://x/gone.png"]["fetched_at"] = (
        datetime.now(timezone.utc) - timedelta(days=30)
    ).isoformat()
    assert store.image_failed("https://x/gone.png") is True  # age does not matter for permanent ones


def test_transient_failure_expires_after_three_days(store):
    store.mark_image_failed("https://x/late.png", "timeout")
    assert store.image_failed("https://x/late.png") is True
    store.image_index["https://x/late.png"]["fetched_at"] = (
        datetime.now(timezone.utc) - timedelta(days=4)
    ).isoformat()
    assert store.image_failed("https://x/late.png") is False
    client = FakeClient(lambda u, p: FakeResponse(200, PNG_1x1, PNG_HEADERS))
    assert fetch_image(client, store, "https://x/late.png", 10_000_000) is True


def test_oversize_and_non_image_are_permanent(store):
    big = FakeClient(lambda u, p: FakeResponse(200, PNG_1x1, {"Content-Length": "99999999"}))
    assert fetch_image(big, store, "https://x/big.png", 1000) is False
    assert store.image_index["https://x/big.png"]["permanent"] is True
    html = FakeClient(lambda u, p: FakeResponse(200, b"<html>nope</html>", {"Content-Type": "text/html"}))
    assert fetch_image(html, store, "https://x/page.png", 1000) is False
    assert store.image_index["https://x/page.png"]["permanent"] is True


class Timeout(FakeClient):
    def get(self, url, params=None, allow_404=False, stream=False, **kw):
        self.requests_made += 1
        raise requests.ReadTimeout("read timed out")


def test_wordpress_listing_timeout_is_a_source_error(blog):
    src = WordPressSource(blog, Timeout(lambda u, p: None), "https://example.com/wp-json/wp/v2")
    with pytest.raises(SourceError):
        src.discover()


def test_wordpress_fetch_connection_error_is_a_source_error(blog):
    items = [wp_item(1)]

    def routes(url, params):
        if "include" in params:
            raise requests.ConnectionError("reset")
        return FakeResponse(200, json.dumps(items), {"X-WP-TotalPages": "1"})

    class Client(FakeClient):
        def get(self, url, params=None, allow_404=False, stream=False, **kw):
            self.requests_made += 1
            return self.routes(url, params or {})

    src = WordPressSource(blog, Client(routes), "https://example.com/wp-json/wp/v2")
    refs = src.discover()
    with pytest.raises(SourceError):
        list(src.fetch(refs))


def test_feed_listing_timeout_is_a_source_error(blog):
    src = FeedSource(blog, Timeout(lambda u, p: None), "https://example.com/feed/")
    with pytest.raises(SourceError):
        src.discover()


def test_run_continues_after_one_blog_fails(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "blogs.yaml"
    cfg.write_text(
        "defaults: {request_delay: 0}\n"
        "blogs:\n  - {id: bad, url: https://bad.example/}\n  - {id: good, url: https://good.example/}\n"
    )
    calls: list[str] = []

    def fake_sync(blog, settings, client, store, *, full=False, prune=False):
        calls.append(blog.id)
        if blog.id == "bad":
            raise requests.ConnectionError("no route to host")
        return SyncResult(blog_id=blog.id, source="fake", discovered=1, new=1)

    monkeypatch.setattr(cli, "sync_blog", fake_sync)
    monkeypatch.setattr(cli, "build_book", lambda *a, **k: [])
    rc = cli.main(["-c", str(cfg), "run"])
    out = capsys.readouterr().out
    assert calls == ["bad", "good"]
    assert rc == 2 and "good: 1 posts listed" in out


def test_source_detection_survives_network_errors():
    b = BlogConfig(id="x", url="https://x.example/blog")
    assert WordPressSource.detect(b, Timeout(lambda u, p: None)) is None
    assert FeedSource.detect(b, Timeout(lambda u, p: None)) is None


def test_html_fixture_still_parses():
    assert "api.w.org" in BLOG_HTML


def test_sniff_trusts_server_content_type_over_extension():
    from blog2epub.images import sniff_media_type

    assert sniff_media_type(b"<html>", "text/html", "https://x/a.png") is None
    assert sniff_media_type(b"\x00" * 16, "application/octet-stream", "https://x/a.png") == "image/png"
    assert sniff_media_type(b"\x00" * 16, None, "https://x/a.jpg") == "image/jpeg"
    assert sniff_media_type(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "text/plain", "https://x/x") == "image/png"


def test_list_survives_a_closed_pipe(tmp_path, monkeypatch, capsys):
    """`blog2epub list | head` must exit quietly rather than dumping a traceback."""
    cfg = tmp_path / "blogs.yaml"
    cfg.write_text("blogs:\n  - {id: a, url: https://a.example/}\n")

    real_print = print

    def exploding_print(*a, **kw):
        real_print(*a, **kw)
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr("builtins.print", exploding_print)
    assert cli.main(["-c", str(cfg), "list"]) == 0


def test_trailing_slash_mismatch_is_retried(blog):
    """A sitemap may list /slug/ while the server serves only /slug (Gravitee does this)."""
    served = "https://example.com/blog/f1/"

    def routes(url, params):
        return PAGE_RESPONSE if url == served.rstrip("/") else FakeResponse(404)

    client = FakeClient(routes)
    text, used = client.get_text_tolerant(served)
    assert used == served.rstrip("/") and "Real paragraph" in text

    # the sitemap source records the URL that worked, so chapters link somewhere real
    blog.source = "sitemap"
    src = SitemapSource(blog, FakeClient(routes), "https://example.com/sitemap.xml")
    ref = PostRef(key="sm-1", url=served)
    post = next(iter(src.fetch([ref])))
    assert post.url == served.rstrip("/")
