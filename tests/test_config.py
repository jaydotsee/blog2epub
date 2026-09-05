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


@pytest.mark.parametrize("body", [
    "blogs:\n  - url: https://x\n",                       # missing id
    "blogs:\n  - id: x\n",                                # missing url
    "blogs:\n  - id: x\n    url: https://x\n    order: sideways\n",
    "blogs:\n  - id: x\n    url: https://x\n    bogus: 1\n",
    "blogs:\n  - id: x\n    url: https://x\n  - id: x\n    url: https://y\n",
    "blogs:\n  - id: x\n    url: https://x\n    include: ['(']\n",
    "defaults:\n  nope: 1\nblogs: []\n",
])
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
