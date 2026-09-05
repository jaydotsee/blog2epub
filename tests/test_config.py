import pytest

from blog2epub.config import ConfigError, load_config


def test_load_config_merges_defaults(tmp_path):
    cfg = tmp_path / "blogs.yaml"
    cfg.write_text("""
defaults:
  output_dir: out
  request_delay: 0
  group_by: month
  images: false
blogs:
  - id: a
    url: https://a.example/blog
  - id: b
    url: https://b.example/
    title: B
    group_by: year
    since: 2024-01-01
""")
    s = load_config(cfg)
    assert s.output_dir == tmp_path / "out"
    assert s.request_delay == 0
    a, b = s.blogs
    assert a.title == "a" and a.group_by == "month" and a.images is False
    assert b.group_by == "year" and b.since == "2024-01-01"
    assert s.blog("b") is b
    with pytest.raises(ConfigError):
        s.blog("zzz")


@pytest.mark.parametrize(
    "body",
    [
        "blogs:\n  - url: https://x\n",  # missing id
        "blogs:\n  - id: x\n",  # missing url
        "blogs:\n  - id: x\n    url: https://x\n    order: sideways\n",
        "blogs:\n  - id: x\n    url: https://x\n    bogus: 1\n",
        "blogs:\n  - id: x\n    url: https://x\n  - id: x\n    url: https://y\n",
        "blogs:\n  - id: x\n    url: https://x\n    include: ['(']\n",
        "defaults:\n  nope: 1\nblogs: []\n",
    ],
)
def test_invalid_config(tmp_path, body):
    cfg = tmp_path / "blogs.yaml"
    cfg.write_text(body)
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_accepts_url(blog):
    assert blog.accepts_url("https://example.com/blog/hello/")
    assert not blog.accepts_url("https://example.com/docs/hello/")
    blog.exclude = [r"/draft-"]
    assert not blog.accepts_url("https://example.com/blog/draft-1/")


def test_books_and_standalone(tmp_path):
    cfg = tmp_path / "blogs.yaml"
    cfg.write_text("""
defaults:
  order: desc
blogs:
  - id: a
    url: https://a.example/blog
  - id: b
    url: https://b.example/
    standalone: false
    group_by: month
books:
  - id: digest
    title: Digest
    blogs: [a, b]
    group_by: blog
    max_posts: 50
    since: 2025-01-01
    cover: covers/d.jpg
""")
    s = load_config(cfg)
    books = s.all_books()
    assert [b.id for b in books] == ["a", "digest"]  # b has no standalone book
    assert books[0].blogs == ["a"] and books[0].order == "desc"
    d = s.book("digest")
    assert d.blogs == ["a", "b"] and d.group_by == "blog" and d.max_posts == 50 and d.since == "2025-01-01"
    assert d.order == "desc"  # defaults apply to books too
    assert s.blog("b").as_book().group_by == "month"
    with pytest.raises(ConfigError):
        s.book("zzz")


@pytest.mark.parametrize(
    "body",
    [
        "blogs:\n  - id: a\n    url: https://a\nbooks:\n  - id: d\n    blogs: [nope]\n",  # unknown blog
        "blogs:\n  - id: a\n    url: https://a\nbooks:\n  - id: a\n    blogs: [a]\n",  # clashes with blog id
        "blogs:\n  - id: a\n    url: https://a\nbooks:\n  - id: d\n    blogs: []\n",  # empty blogs
        "blogs:\n  - id: a\n    url: https://a\nbooks:\n  - id: d\n    blogs: [a]\n    group_by: author\n",
        "blogs:\n  - id: a\n    url: https://a\n    readability: maybe\n",
    ],
)
def test_invalid_books(tmp_path, body):
    cfg = tmp_path / "blogs.yaml"
    cfg.write_text(body)
    with pytest.raises(ConfigError):
        load_config(cfg)
