from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from .http import HttpClient
from .store import BlogStore

log = logging.getLogger(__name__)

# EPUB 3.3 core media types for images.
MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "svg": "image/svg+xml",
    "webp": "image/webp",
}
_EXT_FOR_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/svg+xml": "svg",
    "image/webp": "webp",
}


def sniff_media_type(data: bytes, content_type: str | None, url: str) -> str | None:
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if b"<svg" in data[:2048].lower():
        return "image/svg+xml"
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _EXT_FOR_TYPE:
        return ct
    if ct and not ct.endswith("octet-stream"):
        return None  # the server says it is not an image (an HTML error page, say); trust it
    ext = urlparse(url).path.rsplit(".", 1)[-1].lower()
    return MEDIA_TYPES.get(ext)


_DESCRIPTOR = re.compile(r"^(\d+(?:\.\d+)?)([wx]),?$")


def parse_srcset(srcset: str) -> list[tuple[int, str]]:
    """Return (width, url) pairs. Tokenises on whitespace so data: URIs with commas survive."""
    if "data:" in srcset:
        # lazy-load placeholders are inline SVG data URIs, often with literal spaces and commas
        srcset = re.sub(r"data:.*?\s+\d+(?:\.\d+)?[wx](?=\s*,|\s*$)", "", srcset, flags=re.S)
        if "data:" in srcset:
            return []
    out: list[tuple[int, str]] = []
    pending: str | None = None
    for token in srcset.split():
        m = _DESCRIPTOR.match(token)
        if m and pending is not None:
            width = int(float(m.group(1))) if m.group(2) == "w" else 0
            out.append((width, pending))
            pending = None
            continue
        if pending is not None:  # previous URL had no descriptor
            out.append((0, pending))
        pending = token.rstrip(",") or None
    if pending is not None:
        out.append((0, pending))
    return [(w, u) for w, u in out if u and not u.startswith("data:")]


def pick_srcset_candidate(src: str | None, srcset: str | None, max_width: int) -> str | None:
    """Choose the largest srcset candidate whose declared width is <= max_width.

    Falls back to `src`; if every candidate is wider than max_width, the narrowest one wins,
    which keeps e-reader files small without dropping the image.
    """
    if src and src.startswith("data:"):
        src = None
    if not srcset:
        return src
    candidates = parse_srcset(srcset)
    if not candidates:
        return src
    fitting = [c for c in candidates if 0 < c[0] <= max_width]
    if fitting:
        return max(fitting)[1]
    widths = [c for c in candidates if c[0] > 0]
    if widths:
        return min(widths)[1]
    return src or candidates[0][1]


def rasterize_svg(svg_path: Path, png_path: Path, width: int) -> bool:
    """Convert an SVG file to PNG (cached next to it). Returns False when cairosvg is unavailable."""
    if png_path.exists():
        return True
    try:
        import cairosvg  # noqa: PLC0415  (optional dependency: the `svg` extra)
    except ImportError:
        return False
    try:
        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), output_width=width)
    except Exception as exc:  # cairosvg raises a variety of parse errors on odd files
        log.warning("could not rasterise %s: %s", svg_path.name, exc)
        return False
    return True


def rasterize_svg_bytes(svg: bytes, width: int) -> bytes | None:
    try:
        import cairosvg  # noqa: PLC0415
    except ImportError:
        return None
    try:
        return cairosvg.svg2png(bytestring=svg, output_width=width)
    except Exception as exc:
        log.warning("could not rasterise SVG: %s", exc)
        return None


PERMANENT_STATUSES = {400, 401, 403, 404, 410, 451}
BODY_RETRY_PAUSE = 2.0  # seconds before re-downloading an image whose body read failed


def _is_permanent(exc: requests.RequestException) -> bool:
    resp = getattr(exc, "response", None)
    return resp is not None and resp.status_code in PERMANENT_STATUSES


def _download(client: HttpClient, url: str, max_bytes: int) -> tuple[bytes, str | None] | str:
    """Return (data, content_type), or a failure reason string for oversize files."""
    resp = client.get(url, stream=True)
    length = resp.headers.get("Content-Length")
    if length and int(length) > max_bytes:
        return f"too large ({length} bytes)"
    chunks: list[bytes] = []
    size = 0
    for chunk in resp.iter_content(65536):
        size += len(chunk)
        if size > max_bytes:
            return f"too large (> {max_bytes} bytes)"
        chunks.append(chunk)
    return b"".join(chunks), resp.headers.get("Content-Type")


def fetch_image(client: HttpClient, store: BlogStore, url: str, max_bytes: int) -> bool:
    """Download `url` into the store unless it is already there (or a failure is still fresh).

    The HTTP client retries connection errors, timeouts before the headers and 5xx responses.
    A failure while the body streams is not covered by that, so the whole download is tried
    once more after a short pause. Failures are recorded as permanent (4xx, oversize, not an
    image) or transient (everything else, retried after FAILED_IMAGE_RETRY_DAYS).
    """
    if store.image_path(url) or store.image_failed(url):
        return store.image_path(url) is not None
    result: tuple[bytes, str | None] | str | None = None
    for attempt in (1, 2):
        try:
            result = _download(client, url, max_bytes)
            break
        except requests.RequestException as exc:
            if _is_permanent(exc):
                log.warning("image %s: %s", url, exc)
                store.mark_image_failed(url, str(exc)[:200], permanent=True)
                return False
            if attempt == 1:
                log.info("image %s: %s, retrying once", url, exc)
                time.sleep(BODY_RETRY_PAUSE)
                continue
            log.warning("image %s: %s", url, exc)
            store.mark_image_failed(url, str(exc)[:200])
            return False
    assert result is not None
    if isinstance(result, str):
        store.mark_image_failed(url, result, permanent=True)
        return False
    data, content_type = result
    media_type = sniff_media_type(data, content_type, url)
    if not media_type or not data:
        store.mark_image_failed(url, "not an image", permanent=True)
        return False
    store.put_image(url, data, _EXT_FOR_TYPE[media_type], media_type)
    return True
