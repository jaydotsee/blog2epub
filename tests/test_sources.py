"""Source tests with a fake HTTP client (no network)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from blog2epub.config import BlogConfig
from blog2epub.sources import resolve_source
from blog2epub.sources.feed import FeedSource
from blog2epub.sources.sitemap import SitemapSource
from blog2epub.sources.wordpress import WordPressSource
from blog2epub.store import BlogStore
from blog2epub.sync import sync_blog


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code = status
        self.content = body if isinstance(body, bytes) else body.encode()
        self.text = self.content.decode("utf-8", "replace")
        self.headers = headers or {}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def iter_content(self, n):
        yield self.content


class FakeClient:
    """Routes (url, sorted params) -> FakeResponse; records what was requested."""

    def __init__(self, routes):
        self.routes = routes  # callable(url, params) -> FakeResponse | None
        self.calls = []
        self.requests_made = 0

    def get(self, url, params=None, allow_404=False, stream=False, **kw):
        self.calls.append((url, dict(params or {})))
        self.requests_made += 1
        resp = self.routes(url, params or {})
        if resp is None:
            resp = FakeResponse(404)
        if allow_404 and resp.status_code == 404:
            return resp
        resp.raise_for_status()
        return resp

    def get_text(self, url, **kw):
        return self.get(url, **kw).text

    def get_json(self, url, **kw):
        return self.get(url, **kw).json()

    def try_get(self, url, **kw):
        resp = self.get(url, allow_404=True, **kw)
        return resp if resp.status_code == 200 else None


BLOG_HTML = '<html><head><link rel="https://api.w.org/" href="https://example.com/wp-json/" />' \
            '<link rel="alternate" type="application/rss+xml" href="/feed/"/></head><body/></html>'


def wp_item(i, date="2024-01-01T00:00:00", modified=None, link=None):
    return {"id": i, "date_gmt": date, "modified_gmt": modified or date, "slug": f"p{i}",
            "link": link or f"https://example.com/blog/p{i}/", "title": {"rendered": f"Post &amp; {i}"},
            "content": {"rendered": f"<p>content {i}</p><img src='/img{i}.png'>"},
            "excerpt": {"rendered": "<p>ex</p>"}, "author": 1,
            "_embedded": {"author": [{"name": "Ann"}], "wp:term": [[{"taxonomy": "category", "name": "Cat"}],
                                                                   [{"taxonomy": "post_tag", "name": "T1"}]]}}


def make_wp_routes(items, images=True):
    def routes(url, params):
        if url == "https://example.com/blog":
            return FakeResponse(200, BLOG_HTML)
        if url == "https://example.com/wp-json/wp/v2/posts":
            if "include" in params:
                ids = {int(x) for x in params["include"].split(",")}
                return FakeResponse(200, json.dumps([i for i in items if i["id"] in ids]))
            page = int(params.get("page", 1))
            per = int(params.get("per_page", 100))
            chunk = items[(page - 1) * per: page * per]
            if page > 1 and not chunk:
                return FakeResponse(400, "{}")
            return FakeResponse(200, json.dumps(chunk), {"X-WP-TotalPages": str(max(1, -(-len(items) // per)))})
        if url.startswith("https://example.com/img") and images:
            return FakeResponse(200, b"\x89PNG\r\n\x1a\n" + b"\0" * 20, {"Content-Type": "image/png"})
        return None
    return routes


def test_wordpress_detect_discover_fetch(blog):
    items = [wp_item(1), wp_item(2, link="https://example.com/news/p2/"), wp_item(3)]
    client = FakeClient(make_wp_routes(items))
    src = resolve_source(blog, client)
    assert isinstance(src, WordPressSource)
    refs = src.discover()
    assert [r.key for r in refs] == ["wp-1", "wp-3"]  # /news/ filtered out by include pattern
    assert refs[0].title == "Post & 1"
    posts = list(src.fetch(refs))
    assert posts[0].author == "Ann" and posts[0].categories == ["Cat"] and posts[0].tags == ["T1"]
    assert posts[0].date == "2024-01-01T00:00:00+00:00"
    fetch_call = [c for c in client.calls if "include" in c[1]][0]
    assert fetch_call[1]["include"] == "1,3" and "after" not in fetch_call[1]


def test_wordpress_since_filter_sent_as_after(blog):
    blog.since = "2024-01-02"
    client = FakeClient(make_wp_routes([wp_item(1, date="2024-01-01T00:00:00"), wp_item(2, date="2024-01-03T00:00:00")]))
    src = WordPressSource.detect(blog, client)
    refs = src.discover()
    assert [r.key for r in refs] == ["wp-2"]
    assert client.calls[-1][1]["after"] == "2024-01-02T00:00:00"


def test_sync_is_incremental_and_detects_modified(tmp_path, blog):
    settings = SimpleNamespace(config_path=tmp_path / "blogs.yaml", cache_dir=tmp_path / "cache",
                               output_dir=tmp_path / "out")
    items = [wp_item(1), wp_item(2)]
    client = FakeClient(make_wp_routes(items))
    store = BlogStore(settings.cache_dir, blog.id)
    r1 = sync_blog(blog, settings, client, store)
    assert (r1.new, r1.updated, r1.images_fetched) == (2, 0, 2)
    assert store.index["source"] == "wordpress"

    items[1]["modified_gmt"] = "2024-02-01T00:00:00"
    items.append(wp_item(3))
    client2 = FakeClient(make_wp_routes(items))
    store2 = BlogStore(settings.cache_dir, blog.id)
    r2 = sync_blog(blog, settings, client2, store2)
    assert (r2.new, r2.updated, r2.removed) == (1, 1, 0)
    fetched = [c for c in client2.calls if "include" in c[1]][0][1]["include"]
    assert fetched == "2,3"
    assert r2.images_fetched == 1  # only the new post's image

    del items[0]
    store3 = BlogStore(settings.cache_dir, blog.id)
    r3 = sync_blog(blog, settings, FakeClient(make_wp_routes(items)), store3)
    assert r3.stale == 1 and r3.removed == 0 and len(store3.post_index) == 3
    store4 = BlogStore(settings.cache_dir, blog.id)
    r4 = sync_blog(blog, settings, FakeClient(make_wp_routes(items)), store4, prune=True)
    assert r4.removed == 1 and len(store4.post_index) == 2


RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
<item><title>Feed post</title><link>https://example.com/blog/f1/</link><guid>g1</guid>
<pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate><description>short</description></item>
</channel></rss>"""

PAGE = """<html><head><title>Feed post - Site</title>
<meta property="article:published_time" content="2024-01-01T00:00:00+00:00"/>
<meta name="author" content="Bob"/></head><body><nav>menu menu menu</nav>
<article><h1>Feed post</h1>""" + "<p>Real paragraph of article text that is long enough to be picked up. </p>" * 20 + """
</article><footer>foot</footer></body></html>"""


def test_feed_source_fetches_full_page_when_body_is_short(blog):
    blog.source = "feed"

    def routes(url, params):
        if url == "https://example.com/blog":
            return FakeResponse(200, BLOG_HTML)
        if url == "https://example.com/feed/":
            return FakeResponse(200, RSS)
        if url == "https://example.com/blog/f1/":
            return FakeResponse(200, PAGE)
        return None

    src = resolve_source(blog, FakeClient(routes))
    assert isinstance(src, FeedSource)
    refs = src.discover()
    assert len(refs) == 1 and refs[0].date.startswith("2024-01-01")
    post = next(iter(src.fetch(refs)))
    assert "Real paragraph" in post.html and "menu menu" not in post.html
    assert post.author == "Bob"


SITEMAP_INDEX = """<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://example.com/post-sitemap.xml</loc></sitemap></sitemapindex>"""
SITEMAP = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://example.com/blog/f1/</loc><lastmod>2024-01-02</lastmod></url>
<url><loc>https://example.com/about/</loc></url>
<url><loc>https://example.com/blog/</loc></url></urlset>"""


def test_sitemap_source(blog):
    blog.source = "sitemap"

    def routes(url, params):
        return {
            "https://example.com/robots.txt": FakeResponse(200, "Sitemap: https://example.com/sitemap_index.xml\n"),
            "https://example.com/sitemap_index.xml": FakeResponse(200, SITEMAP_INDEX),
            "https://example.com/post-sitemap.xml": FakeResponse(200, SITEMAP),
            "https://example.com/blog/f1/": FakeResponse(200, PAGE),
        }.get(url)

    src = resolve_source(blog, FakeClient(routes))
    assert isinstance(src, SitemapSource)
    refs = src.discover()
    assert [r.url for r in refs] == ["https://example.com/blog/f1/"]
    post = next(iter(src.fetch(refs)))
    assert post.title == "Feed post" and post.date.startswith("2024-01-01") and post.modified == "2024-01-02"


def test_resolve_source_fails_cleanly():
    from blog2epub.sources import SourceError
    b = BlogConfig(id="x", url="https://nothing.example/blog")
    with pytest.raises(SourceError):
        resolve_source(b, FakeClient(lambda u, p: None))


def test_store_failed_image_entries(tmp_path):
    store = BlogStore(tmp_path / "cache", "x")
    store.mark_image_failed("https://x/a.png", "404")
    assert store.image_path("https://x/a.png") is None and store.image_failed("https://x/a.png")
    assert store.image_media_type("https://x/a.png") is None
    store.put_image("https://x/b.png", b"\x89PNG", "png", "image/png")
    assert store.image_path("https://x/b.png").name.endswith(".png") and not store.image_failed("https://x/b.png")
