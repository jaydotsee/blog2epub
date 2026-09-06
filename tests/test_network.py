"""Network robustness: retries, transient vs permanent image failures, per-blog isolation."""

from __future__ import annotations

import json
import threading
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
from tests.test_sources import (
    BLOG_HTML,
    PAGE,
    FakeClient,
    FakeResponse,
    make_wp_routes,
    wp_item,
)

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


def test_wordpress_fetch_batch_failure_is_survivable(blog):
    """Listing failures are fatal; a single failed batch of posts is not."""
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
    assert list(src.fetch(refs)) == []  # skipped, not raised


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
    assert sorted(calls) == ["bad", "good"]  # both ran; blogs sync concurrently, so order is free
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


SOFT_404 = """<html><head><title>Google Cloud Blog</title></head><body><article>
<p>404. That&#39;s an error. The requested URL was not found on this server.</p>
</article></body></html>"""


def test_soft_404_pages_are_not_stored_as_posts(tmp_path, blog):
    """Some sites answer 200 with an error page; those must not become chapters."""
    from types import SimpleNamespace

    from blog2epub.store import BlogStore
    from blog2epub.sync import sync_blog

    settings = SimpleNamespace(
        config_path=tmp_path / "blogs.yaml", cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"
    )
    sitemap = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://example.com/blog/gone/</loc></url>"
        "<url><loc>https://example.com/blog/real/</loc></url></urlset>"
    )
    routes = {
        "https://example.com/robots.txt": FakeResponse(200, "Sitemap: https://example.com/sitemap.xml"),
        "https://example.com/sitemap.xml": FakeResponse(200, sitemap),
        "https://example.com/blog/gone/": FakeResponse(200, SOFT_404),
        "https://example.com/blog/real/": FakeResponse(200, PAGE),
    }
    blog.source = "sitemap"
    store = BlogStore(settings.cache_dir, blog.id)
    result = sync_blog(blog, settings, FakeClient(lambda u, p: routes.get(u)), store)
    assert result.new == 1
    assert [p.url for p in store.iter_posts()] == ["https://example.com/blog/real/"]
    assert any("too short" in e for e in result.errors)

    blog.min_chars = 0  # a link blog with genuinely tiny posts can switch the guard off
    store2 = BlogStore(settings.cache_dir, blog.id)
    assert sync_blog(blog, settings, FakeClient(lambda u, p: routes.get(u)), store2).new == 1


def test_a_failed_batch_does_not_lose_the_whole_archive(tmp_path, blog):
    """A long sync is many batches; one connection failure must not discard the rest."""
    from types import SimpleNamespace

    from blog2epub.store import BlogStore
    from blog2epub.sync import sync_blog

    settings = SimpleNamespace(
        config_path=tmp_path / "blogs.yaml", cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"
    )
    items = [wp_item(i) for i in range(1, 4)]
    routes = make_wp_routes(items)
    calls = {"n": 0}

    def flaky(url, params):
        if "include" in params:
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.ConnectionError("connection reset mid-archive")
        return routes(url, params)

    class Client(FakeClient):
        def get(self, url, params=None, allow_404=False, stream=False, **kw):
            self.requests_made += 1
            resp = self.routes(url, params or {})
            if resp is None:
                resp = FakeResponse(404)
            resp.raise_for_status()
            return resp

    store = BlogStore(settings.cache_dir, blog.id)
    result = sync_blog(blog, settings, Client(flaky), store)
    # the batch failed, so nothing was stored, but the sync completed and said which posts
    assert result.new == 0 and len(result.errors) == 3
    assert all("not fetched" in e for e in result.errors)

    # the next run picks them up
    store2 = BlogStore(settings.cache_dir, blog.id)
    assert sync_blog(blog, settings, Client(flaky), store2).new == 3


def test_long_syncs_checkpoint_their_progress(tmp_path, blog, monkeypatch):
    """Posts fetched before a failure have to survive it."""
    from types import SimpleNamespace

    from blog2epub import sync as sync_mod
    from blog2epub.store import BlogStore

    monkeypatch.setattr(sync_mod, "SAVE_EVERY_POSTS", 2)
    settings = SimpleNamespace(
        config_path=tmp_path / "blogs.yaml", cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"
    )
    items = [wp_item(i) for i in range(1, 6)]
    store = BlogStore(settings.cache_dir, blog.id)
    saved: list[int] = []
    real_save = store.save

    def counting_save():
        saved.append(len(store.post_index))
        real_save()

    store.save = counting_save  # type: ignore[method-assign]
    sync_mod.sync_blog(blog, settings, FakeClient(make_wp_routes(items)), store)
    assert saved and saved[0] < 5, f"expected a checkpoint before the end, got {saved}"


def _jobs_config(tmp_path, blogs: str):
    cfg = tmp_path / "blogs.yaml"
    cfg.write_text(f"defaults: {{request_delay: 0}}\nblogs:\n{blogs}")
    return cfg


def _watcher(monkeypatch):
    """Fake sync recording how many blogs are in flight at once.

    The hold is an Event.wait, not time.sleep: the autouse `no_sleep` fixture above patches
    `blog2epub.images.time.sleep`, and that attribute belongs to the one shared `time` module,
    so it silences sleeps everywhere for the duration of the test.
    """
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    def fake_sync(blog, settings, client, store, *, full=False, prune=False):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        threading.Event().wait(0.05)
        with lock:
            state["now"] -= 1
        return SyncResult(blog_id=blog.id, source="fake", discovered=1, new=1)

    monkeypatch.setattr(cli, "sync_blog", fake_sync)
    return state


def test_blogs_on_different_hosts_sync_at_the_same_time(tmp_path, monkeypatch, capsys):
    # The barrier only clears when all three are in flight together, so this cannot pass by
    # luck: were the syncs sequential, the first wait would time out and raise.
    barrier = threading.Barrier(3, timeout=10)

    def fake_sync(blog, settings, client, store, *, full=False, prune=False):
        barrier.wait()
        return SyncResult(blog_id=blog.id, source="fake", discovered=1, new=1)

    monkeypatch.setattr(cli, "sync_blog", fake_sync)
    cfg = _jobs_config(
        tmp_path,
        "  - {id: a, url: https://a.example/}\n"
        "  - {id: b, url: https://b.example/}\n"
        "  - {id: c, url: https://c.example/}\n",
    )
    assert cli.main(["-c", str(cfg), "sync"]) == 0
    assert {line.split(":")[0] for line in capsys.readouterr().out.splitlines() if line} == {"a", "b", "c"}


def test_blogs_on_one_host_take_turns(tmp_path, monkeypatch):
    # Two entries, one site (APIDAYS publishes on API Scene). Politeness beats parallelism:
    # the host never sees two syncs at once, whatever --jobs says.
    cfg = _jobs_config(
        tmp_path,
        "  - {id: one, url: https://same.example/a}\n  - {id: two, url: https://same.example/b}\n",
    )
    state = _watcher(monkeypatch)
    assert cli.main(["-c", str(cfg), "sync", "--jobs", "8"]) == 0
    assert state["peak"] == 1


def test_jobs_1_syncs_one_blog_at_a_time(tmp_path, monkeypatch):
    cfg = _jobs_config(
        tmp_path, "  - {id: a, url: https://a.example/}\n  - {id: b, url: https://b.example/}\n"
    )
    state = _watcher(monkeypatch)
    assert cli.main(["-c", str(cfg), "sync", "--jobs", "1"]) == 0
    assert state["peak"] == 1
