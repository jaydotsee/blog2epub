from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .models import Post, utcnow_iso

log = logging.getLogger(__name__)

INDEX_VERSION = 1


class BlogStore:
    """On-disk cache for one blog.

    Layout::

        <cache_dir>/<blog_id>/
            index.json          which posts/images we have, when we last synced
            posts/<key>.json    one fully fetched post per file
            images/<sha1>.<ext> downloaded images, keyed by URL hash
    """

    def __init__(self, cache_dir: Path, blog_id: str) -> None:
        self.root = Path(cache_dir) / blog_id
        self.posts_dir = self.root / "posts"
        self.images_dir = self.root / "images"
        self.index_path = self.root / "index.json"
        self.posts_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.index = self._load_index()

    # ---- index -----------------------------------------------------------
    def _load_index(self) -> dict[str, Any]:
        if self.index_path.exists():
            try:
                data = json.loads(self.index_path.read_text(encoding="utf-8"))
                if data.get("version") == INDEX_VERSION:
                    return data
                log.warning("cache index version mismatch for %s, starting fresh", self.root)
            except json.JSONDecodeError:
                log.warning("corrupt cache index %s, starting fresh", self.index_path)
        return {"version": INDEX_VERSION, "source": None, "last_sync": None,
                "last_build": None, "posts": {}, "images": {}}

    def save(self) -> None:
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.index, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(self.index_path)

    @property
    def post_index(self) -> dict[str, dict[str, Any]]:
        return self.index["posts"]

    @property
    def image_index(self) -> dict[str, dict[str, Any]]:
        return self.index["images"]

    # ---- posts -----------------------------------------------------------
    def _post_path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return self.posts_dir / f"{safe}.json"

    def has_post(self, key: str) -> bool:
        return key in self.post_index and self._post_path(key).exists()

    def put_post(self, post: Post) -> None:
        self._post_path(post.key).write_text(
            json.dumps(post.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        self.post_index[post.key] = {
            "url": post.url, "title": post.title, "date": post.date,
            "modified": post.modified, "fetched_at": post.fetched_at,
        }

    def get_post(self, key: str) -> Post | None:
        path = self._post_path(key)
        if not path.exists():
            return None
        return Post.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def remove_post(self, key: str) -> None:
        self.post_index.pop(key, None)
        path = self._post_path(key)
        if path.exists():
            path.unlink()

    def iter_posts(self) -> Iterator[Post]:
        for key in list(self.post_index):
            post = self.get_post(key)
            if post is not None:
                yield post

    # ---- images ----------------------------------------------------------
    @staticmethod
    def image_key(url: str) -> str:
        return hashlib.sha1(url.encode("utf-8")).hexdigest()

    def image_path(self, url: str) -> Path | None:
        entry = self.image_index.get(url)
        if not entry:
            return None
        path = self.images_dir / entry["file"]
        return path if path.exists() else None

    def image_failed(self, url: str) -> bool:
        entry = self.image_index.get(url)
        return bool(entry and entry.get("error"))

    def put_image(self, url: str, data: bytes, ext: str, media_type: str) -> Path:
        name = f"{self.image_key(url)}.{ext}"
        path = self.images_dir / name
        path.write_bytes(data)
        self.image_index[url] = {"file": name, "media_type": media_type, "fetched_at": utcnow_iso()}
        return path

    def mark_image_failed(self, url: str, reason: str) -> None:
        self.image_index[url] = {"error": reason, "fetched_at": utcnow_iso()}

    def image_media_type(self, url: str) -> str | None:
        entry = self.image_index.get(url)
        return entry.get("media_type") if entry else None
