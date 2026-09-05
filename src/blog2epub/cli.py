from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .config import BlogConfig, ConfigError, Settings, load_config
from .epub import build_blog
from .http import HttpClient
from .sources import SourceError, resolve_source
from .store import BlogStore
from .sync import resolve_cover_path, sync_blog

log = logging.getLogger("blog2epub")


def _client(settings: Settings, blog: BlogConfig | None = None) -> HttpClient:
    delay = blog.request_delay if blog and blog.request_delay is not None else settings.request_delay
    return HttpClient(settings.user_agent, delay=delay, timeout=settings.timeout)


def _select(settings: Settings, ids: list[str]) -> list[BlogConfig]:
    if not ids:
        return list(settings.blogs)
    return [settings.blog(i) for i in ids]


# ---- commands ------------------------------------------------------------------
def cmd_list(settings: Settings, args: argparse.Namespace) -> int:
    for b in settings.blogs:
        store = BlogStore(settings.cache_dir, b.id)
        print(f"{b.id:12} {b.title:30} {b.url}  [{b.source}] cached={len(store.post_index)}")
    return 0


def cmd_detect(settings: Settings, args: argparse.Namespace) -> int:
    blog = BlogConfig(id="probe", url=args.url, source=args.source)
    client = _client(settings, blog)
    try:
        source = resolve_source(blog, client)
    except SourceError as exc:
        print(f"no usable source: {exc}")
        return 2
    refs = source.discover()
    print(f"source: {source.describe()}")
    print(f"posts:  {len(refs)}")
    for r in refs[:args.sample]:
        print(f"  {r.date or '----------':>25}  {r.title[:60]:60}  {r.url}")
    if refs:
        print("\nsuggested blogs.yaml entry:\n")
        print(f"  - id: {args.id or _suggest_id(args.url)}\n    title: \"...\"\n    url: {args.url}\n"
              f"    source: {source.name}\n    include:\n      - \"^{_prefix_regex(args.url)}\"")
    return 0


def _suggest_id(url: str) -> str:
    from urllib.parse import urlsplit
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    return host.split(".")[0]


def _prefix_regex(url: str) -> str:
    import re
    return re.escape(url.rstrip("/") + "/").replace("\\", "\\\\")


def cmd_sync(settings: Settings, args: argparse.Namespace) -> int:
    rc = 0
    for blog in _select(settings, args.blogs):
        store = BlogStore(settings.cache_dir, blog.id)
        try:
            result = sync_blog(blog, settings, _client(settings, blog), store, full=args.full, prune=args.prune)
        except SourceError as exc:
            log.error("%s: %s", blog.id, exc)
            rc = 2
            continue
        print(result.summary())
        for err in result.errors:
            print(f"  ! {err}")
    return rc


def cmd_build(settings: Settings, args: argparse.Namespace) -> int:
    rc = 0
    for blog in _select(settings, args.blogs):
        store = BlogStore(settings.cache_dir, blog.id)
        try:
            results = build_blog(blog, store, settings.output_dir, resolve_cover_path(blog, settings, store))
        except ValueError as exc:
            log.error("%s", exc)
            rc = 2
            continue
        _record_build(store, results)
        for r in results:
            print(_build_line(r))
    return rc


def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    report: dict = {"changed": False, "blogs": []}
    rc = 0
    for blog in _select(settings, args.blogs):
        store = BlogStore(settings.cache_dir, blog.id)
        entry: dict = {"id": blog.id, "title": blog.title, "url": blog.url, "built": []}
        try:
            result = sync_blog(blog, settings, _client(settings, blog), store, full=args.full, prune=args.prune)
        except SourceError as exc:
            log.error("%s: %s", blog.id, exc)
            entry["error"] = str(exc)
            report["blogs"].append(entry)
            rc = 2
            continue
        print(result.summary())
        entry.update({"source": result.source, "discovered": result.discovered, "new": result.new,
                      "updated": result.updated, "removed": result.removed, "errors": result.errors,
                      "cached": len(store.post_index)})
        existing = sorted(settings.output_dir.glob(f"{blog.id}*.epub"))
        if result.changed or args.force or not existing:
            try:
                results = build_blog(blog, store, settings.output_dir, resolve_cover_path(blog, settings, store))
            except ValueError as exc:
                log.error("%s", exc)
                entry["error"] = str(exc)
                rc = 2
            else:
                _record_build(store, results)
                entry["built"] = [{"path": str(r.path), "title": r.title, "posts": r.posts,
                                   "images": r.images, "bytes": r.size} for r in results]
                report["changed"] = report["changed"] or result.changed or not existing
                for r in results:
                    print(_build_line(r))
        else:
            print(f"{blog.id}: no changes, keeping {', '.join(p.name for p in existing)}")
        report["blogs"].append(entry)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return rc


def cmd_status(settings: Settings, args: argparse.Namespace) -> int:
    for blog in settings.blogs:
        store = BlogStore(settings.cache_dir, blog.id)
        idx = store.index
        outputs = sorted(settings.output_dir.glob(f"{blog.id}*.epub"))
        dates = sorted(d for d in (v.get("date") for v in store.post_index.values()) if d)
        print(f"{blog.id} ({blog.title})")
        print(f"  source:     {idx.get('source') or 'not synced yet'}")
        print(f"  last sync:  {idx.get('last_sync') or '-'}")
        print(f"  posts:      {len(store.post_index)}" + (f"  ({dates[0][:10]} .. {dates[-1][:10]})" if dates else ""))
        ok = sum(1 for v in store.image_index.values() if not v.get("error"))
        print(f"  images:     {ok} cached, {len(store.image_index) - ok} failed")
        lb = idx.get("last_build") or {}
        print(f"  last build: {lb.get('at', '-')}")
        for p in outputs:
            print(f"  output:     {p} ({p.stat().st_size / 1e6:.1f} MB)")
    return 0


def _record_build(store: BlogStore, results) -> None:
    from .models import utcnow_iso
    store.index["last_build"] = {"at": utcnow_iso(), "files": [str(r.path) for r in results],
                                 "posts": sum(r.posts for r in results)}
    store.save()


def _build_line(r) -> str:
    line = f"built {r.path} - {r.posts} posts, {r.images} images, {r.size / 1e6:.1f} MB"
    if r.missing_images:
        line += f" ({r.missing_images} image references had no cached file)"
    return line


# ---- entry point ---------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="blog2epub", description="Monitor blogs and turn each into an EPUB.")
    p.add_argument("-c", "--config", default="blogs.yaml", help="path to blogs.yaml (default: ./blogs.yaml)")
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v for info, -vv for debug")
    p.add_argument("--version", action="version", version=f"blog2epub {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show configured blogs").set_defaults(func=cmd_list)

    d = sub.add_parser("detect", help="probe a URL and report which source would be used")
    d.add_argument("url")
    d.add_argument("--source", default="auto", choices=["auto", "wordpress", "feed", "sitemap"])
    d.add_argument("--id", help="blog id to use in the suggested config")
    d.add_argument("--sample", type=int, default=5, help="how many discovered posts to print")
    d.set_defaults(func=cmd_detect)

    for name, func, help_ in (("sync", cmd_sync, "fetch new and changed posts into the cache"),
                              ("build", cmd_build, "write EPUB(s) from the cache"),
                              ("run", cmd_run, "sync, then build any blog that changed")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("blogs", nargs="*", help="blog ids (default: all)")
        if name != "build":
            s.add_argument("--full", action="store_true", help="re-fetch every post, retry failed images")
            s.add_argument("--prune", action="store_true", help="drop cached posts the source no longer lists")
        if name == "run":
            s.add_argument("--force", action="store_true", help="rebuild even when nothing changed")
            s.add_argument("--report", metavar="FILE", help="write a JSON summary (used by CI)")
        s.set_defaults(func=func)

    sub.add_parser("status", help="show cache and output state per blog").set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    level = logging.WARNING - 10 * min(args.verbose, 2)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    try:
        settings = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1
    try:
        return args.func(settings, args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
