from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlsplit

from .config import Settings
from .http import HttpClient
from .images import fetch_image
from .store import BlogStore

log = logging.getLogger(__name__)


def resolve_cover(cover: str | None, settings: Settings, client: HttpClient | None = None) -> Path | None:
    """Return a local jpg/png for `cover`, downloading URLs into cache/_covers once."""
    if not cover:
        return None
    if urlsplit(cover).scheme in ("http", "https"):
        store = BlogStore(settings.cache_dir, "_covers")
        path = store.image_path(cover)
        if path is None and client is not None:
            if fetch_image(client, store, cover, 20_000_000):
                path = store.image_path(cover)
            store.save()
        if path is None:
            log.warning("cover %s is not available, using a generated cover", cover)
        return path
    path = settings.config_path.parent / cover
    if not path.exists():
        log.warning("cover file %s not found, using a generated cover", path)
        return None
    return path
