from __future__ import annotations

from pathlib import Path

import pytest

from blog2epub.config import BlogConfig
from blog2epub.models import Post
from blog2epub.store import BlogStore

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da"
    "63f8ffff3f0300050001ff5c7c0a5f0000000049454e44ae426082")


@pytest.fixture
def blog() -> BlogConfig:
    return BlogConfig(id="demo", url="https://example.com/blog", title="Demo Blog", author="Demo Author",
                      description="A demo", include=[r"^https://example\.com/blog/"])


@pytest.fixture
def store(tmp_path: Path, blog: BlogConfig) -> BlogStore:
    return BlogStore(tmp_path / "cache", blog.id)


def make_post(key: str, date: str, title: str | None = None, html: str | None = None, **kw) -> Post:
    slug = key.replace("wp-", "post-")
    return Post(key=key, url=f"https://example.com/blog/{slug}/", title=title or f"Post {key}",
                html=html or f"<p>Body of {key}</p>", date=date, author="Someone", **kw)
