import pytest

from blog2epub.config import BlogConfig, ConfigError, load_config


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


def test_title_strip_must_be_a_valid_regex():
    with pytest.raises(ConfigError, match="title_strip"):
        BlogConfig(id="b", url="https://e.org", title_strip=["(unclosed"])


OVERRIDE_CONFIG = """
defaults:
  request_delay: 0.5
blogs:
  - id: solo
    url: https://solo.example/blog
    sitemap: {url: https://solo.example/sitemap.xml}
  - id: feeder
    url: https://feeder.example/
    standalone: false
books:
  - id: digest
    title: Digest
    blogs: [solo, feeder]
"""


def _cfg(tmp_path):
    p = tmp_path / "blogs.yaml"
    p.write_text(OVERRIDE_CONFIG)
    return p


def test_set_overrides_a_defaults_key(tmp_path):
    s = load_config(_cfg(tmp_path), ["request_delay=2.5"])
    assert s.request_delay == 2.5


def test_set_overrides_one_blog_and_its_standalone_book(tmp_path):
    s = load_config(_cfg(tmp_path), ["solo.split=month", "solo.max_posts=3"])
    assert s.blog("solo").split == "month"
    # the standalone book is derived from the blog, so the override has to reach it
    book = s.book("solo")
    assert book.split == "month" and book.max_posts == 3
    assert s.blog("feeder").split == "year"  # untouched


def test_set_overrides_a_book_only_id(tmp_path):
    s = load_config(_cfg(tmp_path), ["digest.since=2w"])
    assert s.book("digest").since == "2w"


def test_set_reaches_a_nested_key(tmp_path):
    s = load_config(_cfg(tmp_path), ["solo.sitemap.max=800"])
    assert s.blog("solo").sitemap == {"url": "https://solo.example/sitemap.xml", "max": 800}


def test_set_reads_the_value_as_yaml(tmp_path):
    s = load_config(
        _cfg(tmp_path),
        ["solo.images=false", "solo.max_posts=7", 'solo.exclude=["^https://x/"]', "solo.since=2024-01-01"],
    )
    b = s.blog("solo")
    assert b.images is False and b.max_posts == 7
    assert b.exclude == ["^https://x/"] and b.since == "2024-01-01"


def test_set_goes_through_the_same_validation_as_the_file(tmp_path):
    # an override is not a back door: unknown keys and bad values are refused as in the file
    with pytest.raises(ConfigError, match="unknown keys"):
        load_config(_cfg(tmp_path), ["solo.nosuchkey=1"])
    with pytest.raises(ConfigError, match="must be one of"):
        load_config(_cfg(tmp_path), ["solo.split=weekly"])
    # and `max_book_bytes: 50MB` is parsed, not left as a string
    assert load_config(_cfg(tmp_path), ["solo.max_book_bytes=50MB"]).book("solo").max_book_bytes == 50_000_000


def test_set_reports_a_bad_spec_clearly(tmp_path):
    with pytest.raises(ConfigError, match="needs KEY=VALUE"):
        load_config(_cfg(tmp_path), ["noequals"])
    with pytest.raises(ConfigError, match="no blog or book called 'nope'"):
        load_config(_cfg(tmp_path), ["nope.split=year"])
    with pytest.raises(ConfigError, match="name a key to set"):
        load_config(_cfg(tmp_path), ["solo="])


def test_set_is_accepted_before_and_after_the_subcommand(tmp_path, capsys):
    from blog2epub import cli

    cfg = _cfg(tmp_path)
    assert (
        cli.main(["-c", str(cfg), "--set", "solo.title=Before", "list", "--set", "digest.title=After"]) == 0
    )
    out = capsys.readouterr().out
    assert "Before" in out and "After" in out
