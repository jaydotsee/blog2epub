"""Orchestration: discover -> fetch new/changed posts -> fetch their images -> update the cache."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .clean import extract_image_urls
from .config import BlogConfig, Settings
from .http import HttpClient
from .images import fetch_image
from .models import PostRef, utcnow_iso
from .sources import resolve_source
from .store import BlogStore

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    blog_id: str
    source: str
    discovered: int = 0
    new: int = 0
    updated: int = 0
    removed: int = 0
    stale: int = 0
    images_fetched: int = 0
    images_failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.new or self.updated or self.removed)

    def summary(self) -> str:
        return (f"{self.blog_id}: {self.discovered} posts listed via {self.source}; "
                f"{self.new} new, {self.updated} updated, {self.removed} removed, {self.stale} no longer listed; "
                f"{self.images_fetched} images fetched, {self.images_failed} failed")


def _needs_fetch(store: BlogStore, ref: PostRef, full: bool) -> bool:
    if full or not store.has_post(ref.key):
        return True
    cached = store.post_index[ref.key]
    if ref.modified and cached.get("modified") and ref.modified != cached["modified"]:
        return True
    return False


def cover_source(blog: BlogConfig, settings: Settings) -> Path | str | None:
    if not blog.cover:
        return None
    if urlsplit(blog.cover).scheme in ("http", "https"):
        return blog.cover
    return settings.config_path.parent / blog.cover


def resolve_cover_path(blog: BlogConfig, settings: Settings, store: BlogStore) -> Path | None:
    src = cover_source(blog, settings)
    if src is None:
        return None
    if isinstance(src, Path):
        return src if src.exists() else None
    return store.image_path(src)


def sync_blog(blog: BlogConfig, settings: Settings, client: HttpClient, store: BlogStore, *,
              full: bool = False, prune: bool = False) -> SyncResult:
    source = resolve_source(blog, client, hint=store.index.get("source"))
    result = SyncResult(blog_id=blog.id, source=source.describe())

    refs = source.discover()
    result.discovered = len(refs)
    listed = {r.key for r in refs}
    to_fetch = [r for r in refs if _needs_fetch(store, r, full)]
    log.info("%s: %d posts listed, %d to fetch", blog.id, len(refs), len(to_fetch))

    fetched_keys: set[str] = set()
    for post in source.fetch(to_fetch):
        existed = store.has_post(post.key)
        store.put_post(post)
        fetched_keys.add(post.key)
        if existed:
            result.updated += 1
        else:
            result.new += 1
        log.info("  fetched %s (%s)", post.title[:70], post.date or "undated")
    missing = [r for r in to_fetch if r.key not in fetched_keys]
    for r in missing:
        result.errors.append(f"not fetched: {r.url}")

    for key in list(store.post_index):
        if key not in listed:
            if prune:
                store.remove_post(key)
                result.removed += 1
            else:
                result.stale += 1

    if full:
        # forget previous image failures so they get one more chance
        for url, entry in list(store.image_index.items()):
            if entry.get("error"):
                del store.image_index[url]

    if blog.images:
        wanted: list[str] = []
        for post in store.iter_posts():
            wanted.extend(extract_image_urls(post.html, post.url, blog.max_image_width))
        cover = cover_source(blog, settings)
        if isinstance(cover, str):
            wanted.append(cover)
        for url in dict.fromkeys(wanted):
            if store.image_path(url) or store.image_failed(url):
                continue
            if fetch_image(client, store, url, blog.max_image_bytes):
                result.images_fetched += 1
            else:
                result.images_failed += 1
            if (result.images_fetched + result.images_failed) % 25 == 0:
                store.save()

    store.index["source"] = source.name
    store.index["last_sync"] = utcnow_iso()
    store.save()
    return result
