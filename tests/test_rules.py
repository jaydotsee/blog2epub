"""Site rules (keep / remove / extra_css) and rolling date windows."""

from datetime import datetime, timedelta, timezone

import pytest

from blog2epub.clean import clean_html, extract_image_urls
from blog2epub.config import BlogConfig, BookConfig, ConfigError
from blog2epub.extract import extract_article
from blog2epub.models import is_relative_date, resolve_date
from blog2epub.sources.wordpress import _iso_day

BASE = "https://example.com/blog/post/"
PAGE = """<html><head><title>T</title></head><body>
<nav class="menu">Home About</nav>
<div class="wrapper">
  <aside class="sidebar"><p>Popular posts</p></aside>
  <article class="entry">
    <h1>Title</h1>
    <div class="share">Share on X</div>
    <p>First real paragraph of the article body.</p>
    <img src="/pic.png" alt="p"/>
    <p>Second paragraph.</p>
    <div class="newsletter"><p>Subscribe!</p><img src="/promo.png" alt=""/></div>
  </article>
</div>
<footer>© 2026</footer>
</body></html>"""


def _clean(html, **kw):
    kw.setdefault("image_resolver", lambda url: "../Images/x.png")
    return clean_html(html, BASE, **kw)[0]


def test_keep_selects_container_and_remove_drops_clutter():
    out = _clean(PAGE, keep=["article.entry"], remove=[".share", ".newsletter"])
    assert "First real paragraph" in out and "Second paragraph" in out
    assert "Popular posts" not in out and "Home About" not in out and "©" not in out
    assert "Share on X" not in out and "Subscribe" not in out


def test_keep_without_match_keeps_everything():
    out = _clean(PAGE, keep=["main.nope"], remove=[".share"])
    assert "Popular posts" in out and "First real paragraph" in out and "Share on X" not in out


def test_keep_multiple_and_nested_selectors_keep_document_order():
    html = '<div class="a"><p>one</p></div><div class="b"><div class="a"><p>two</p></div><p>three</p></div>'
    out = _clean(html, keep=[".b", ".a"])
    assert out.index("one") < out.index("two") < out.index("three")
    assert out.count("two") == 1  # nested match not duplicated


def test_remove_prevents_image_prefetch():
    urls = extract_image_urls(PAGE, BASE, keep=["article"], remove=[".newsletter"])
    assert urls == ["https://example.com/pic.png"]


def test_extract_article_uses_keep_before_readability():
    art = extract_article(PAGE, BASE, keep=["article.entry"], remove=[".share"])
    assert "First real paragraph" in art["html"] and "Share on X" not in art["html"]
    assert "Popular posts" not in art["html"]
    fallback = extract_article(PAGE, BASE, keep=["#missing"])
    assert "First real paragraph" in fallback["html"]  # readability still runs


def test_config_validates_selectors():
    with pytest.raises(ConfigError):
        BlogConfig(id="x", url="https://x", keep=["div[["])
    with pytest.raises(ConfigError):
        BlogConfig(id="x", url="https://x", remove=[":::"])
    BlogConfig(id="x", url="https://x", keep=["article, main .post"], remove=[".a", "#b > p"])


def test_resolve_date_relative_and_absolute():
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    assert resolve_date("7d", now) == now - timedelta(days=7)
    assert resolve_date("2w", now) == now - timedelta(days=14)
    assert resolve_date("3m", now) == now - timedelta(days=90)
    assert resolve_date("1y", now) == now - timedelta(days=365)
    assert resolve_date(" 10D ", now) == now - timedelta(days=10)
    assert resolve_date("2025-01-01", now) == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert resolve_date(None) is None and resolve_date("") is None and resolve_date("soon") is None
    assert is_relative_date("7d") and not is_relative_date("2025-01-01") and not is_relative_date(None)


def test_config_validates_dates():
    BlogConfig(id="x", url="https://x", since="7d", until="2026-12-31")
    BookConfig(id="b", blogs=["x"], since="1y")
    with pytest.raises(ConfigError):
        BlogConfig(id="x", url="https://x", since="last week")
    with pytest.raises(ConfigError):
        BookConfig(id="b", blogs=["x"], until="7 days")


def test_wordpress_after_param_from_relative_since():
    after = _iso_day("7d", end=False)
    assert datetime.fromisoformat(after) > datetime.now() - timedelta(days=8)
    assert _iso_day("2025-01-01", end=True) == "2025-01-01T23:59:59"


def test_extra_css_and_blog_class(tmp_path, blog, store):
    import zipfile

    from blog2epub.epub import build_epub, select_entries
    from tests.conftest import make_post

    store.put_post(make_post("wp-1", "2024-01-01T00:00:00+00:00"))
    store.save()
    blog.extra_css = ".blog-demo pre { font-size: 0.7em; }"
    book = blog.as_book()
    book.extra_css = "body { color: #111; }"
    build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "css.epub")
    z = zipfile.ZipFile(tmp_path / "css.epub")
    css = z.read("OEBPS/Styles/styles.css").decode()
    assert ".blog-demo pre { font-size: 0.7em; }" in css and "body { color: #111; }" in css
    assert 'class="blog-demo"' in z.read("OEBPS/Text/ch-0001.xhtml").decode()


def test_select_entries_with_rolling_window(blog, store):
    from blog2epub.epub import select_entries
    from tests.conftest import make_post

    now = datetime.now(timezone.utc)
    store.put_post(make_post("wp-1", (now - timedelta(days=3)).isoformat()))
    store.put_post(make_post("wp-2", (now - timedelta(days=30)).isoformat()))
    store.save()
    book = blog.as_book()
    book.since = "7d"
    assert [e.post.key for e in select_entries(book, {blog.id: (blog, store)})] == ["wp-1"]
