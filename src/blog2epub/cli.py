from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import re
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import requests

from . import __version__
from .config import BlogConfig, BookConfig, ConfigError, Settings, load_config
from .covers import resolve_cover
from .epub import BuildResult, book_outputs, build_book
from .http import HttpClient
from .models import utcnow_iso
from .sources import SourceError, resolve_source
from .store import BlogStore
from .sync import SyncResult, sync_blog

log = logging.getLogger("blog2epub")


def _client(settings: Settings, blog: BlogConfig | None = None) -> HttpClient:
    delay = blog.request_delay if blog and blog.request_delay is not None else settings.request_delay
    return HttpClient(settings.user_agent, delay=delay, timeout=settings.timeout)


def _select_books(settings: Settings, ids: list[str]) -> list[BookConfig]:
    return settings.all_books() if not ids else [settings.book(i) for i in ids]


def _select_blogs(settings: Settings, ids: list[str]) -> list[BlogConfig]:
    """Blog ids, or the blogs behind the given book ids; default: every blog."""
    if not ids:
        return list(settings.blogs)
    out: dict[str, BlogConfig] = {}
    for i in ids:
        if any(b.id == i for b in settings.blogs):
            out[i] = settings.blog(i)
        else:
            for blog_id in settings.book(i).blogs:
                out[blog_id] = settings.blog(blog_id)
    return list(out.values())


def _sources(settings: Settings) -> dict[str, tuple[BlogConfig, BlogStore]]:
    return {b.id: (b, BlogStore(settings.cache_dir, b.id)) for b in settings.blogs}


def _build(
    settings: Settings, book: BookConfig, sources, issue: str | None = None, collectors: bool = False
) -> list[BuildResult]:
    cover = resolve_cover(book.cover, settings, _client(settings))
    results = build_book(book, sources, settings.output_dir, cover, issue=issue, collectors=collectors)
    for blog_id in book.blogs:
        store = sources[blog_id][1]
        store.index.setdefault("builds", {})[book.id] = {
            "at": utcnow_iso(),
            "issue": results[0].issue if results else issue,
            "files": [str(r.path) for r in results],
            "posts": sum(r.posts for r in results),
        }
        store.save()
    return results


def _built(r: BuildResult) -> dict:
    """One volume as the JSON report and the release notes see it."""
    return {
        "path": str(r.path),
        "file": r.path.name,
        "title": r.title,
        "issue": r.issue,
        "issue_number": r.issue_number,
        "volume": r.volume,
        "volumes": r.volumes,
        "label": r.label,
        "posts": r.posts,
        "images": r.images,
        "bytes": r.size,
        "first_date": r.first_date,
        "last_date": r.last_date,
        "cover": str(r.cover) if r.cover else None,
    }


def _build_line(r: BuildResult) -> str:
    what = f"{r.title} ({r.label})" if r.label else r.title
    line = f"built {r.path} - {what}: {r.posts} posts, {r.images} images, {r.size / 1e6:.1f} MB"
    saved = r.image_bytes_before - r.image_bytes
    if saved > 100_000:
        scale, unit = (1e6, "MB") if r.image_bytes_before > 1e6 else (1e3, "kB")
        line += (
            f" (images optimised: {r.image_bytes_before / scale:.1f} -> {r.image_bytes / scale:.1f} "
            f"{unit}, -{100 * saved / r.image_bytes_before:.0f}%)"
        )
    if r.missing_images:
        line += f" ({r.missing_images} image references had no cached file)"
    return line


DEFAULT_JOBS = 4  # blogs synced at once; one slow host should not hold up the rest


def _sync_blogs(
    settings: Settings, blogs: list[BlogConfig], *, full: bool, prune: bool, jobs: int
) -> list[tuple[BlogConfig, BlogStore, SyncResult | Exception]]:
    """Sync each blog, up to `jobs` at a time, and return the results in the order given.

    Blogs are independent — each has its own cache directory and HTTP client — so the only
    thing to protect is politeness: two blogs on the same host take turns, so a site never
    sees more requests than its own `request_delay` allows.
    """
    host_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
    out_lock = threading.Lock()

    def one(blog: BlogConfig) -> tuple[BlogConfig, BlogStore, SyncResult | Exception]:
        store = BlogStore(settings.cache_dir, blog.id)
        try:
            with host_locks[urlsplit(blog.url).netloc.lower()]:
                result: SyncResult | Exception = sync_blog(
                    blog, settings, _client(settings, blog), store, full=full, prune=prune
                )
        except (SourceError, requests.RequestException) as exc:
            result = exc
        with out_lock:  # one blog's lines stay together even when several finish at once
            if isinstance(result, Exception):
                log.error("%s: %s", blog.id, result)
            else:
                print("\n".join([result.summary(), *(f"  ! {e}" for e in result.errors)]))
        return blog, store, result

    if jobs <= 1 or len(blogs) <= 1:
        return [one(b) for b in blogs]
    with ThreadPoolExecutor(max_workers=min(jobs, len(blogs))) as pool:
        return list(pool.map(one, blogs))


# ---- commands ------------------------------------------------------------------
def cmd_list(settings: Settings, args: argparse.Namespace) -> int:
    print("blogs:")
    for b in settings.blogs:
        store = BlogStore(settings.cache_dir, b.id)
        flag = "" if b.standalone else "  (no standalone book)"
        print(f"  {b.id:14} {b.title:32} {b.url}  [{b.source}] cached={len(store.post_index)}{flag}")
    print("books:")
    for bk in settings.all_books():
        span = " ".join(
            x
            for x in (
                f"since {bk.since}" if bk.since else "",
                f"until {bk.until}" if bk.until else "",
                f"max {bk.max_posts}" if bk.max_posts else "",
            )
            if x
        )
        print(
            f"  {bk.id:14} {bk.title:32} blogs={','.join(bk.blogs)} by {bk.group_by} {bk.order}"
            + (f"  {span}" if span else "")
        )
    return 0


def cmd_detect(settings: Settings, args: argparse.Namespace) -> int:
    blog = BlogConfig(id="probe", url=args.url, source=args.source)
    client = _client(settings, blog)
    try:
        source = resolve_source(blog, client)
    except (SourceError, requests.RequestException) as exc:
        print(f"no usable source: {exc}")
        return 2
    refs = source.discover()
    print(f"source: {source.describe()}")
    print(f"posts:  {len(refs)}")
    for r in refs[: args.sample]:
        print(f"  {r.date or '----------':>25}  {r.title[:60]:60}  {r.url}")
    if refs:
        print("\nsuggested blogs.yaml entry:\n")
        print(
            f'  - id: {args.id or _suggest_id(args.url)}\n    title: "..."\n    url: {args.url}\n'
            f'    source: {source.name}\n    include:\n      - "^{_prefix_regex(args.url)}"'
        )
    return 0


def _suggest_id(url: str) -> str:
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    return host.split(".", 1)[0]


def _prefix_regex(url: str) -> str:
    return re.escape(url.rstrip("/") + "/").replace("\\", "\\\\")


def cmd_sync(settings: Settings, args: argparse.Namespace) -> int:
    synced = _sync_blogs(
        settings, _select_blogs(settings, args.ids), full=args.full, prune=args.prune, jobs=args.jobs
    )
    return 2 if any(isinstance(r, Exception) for _, _, r in synced) else 0


def cmd_build(settings: Settings, args: argparse.Namespace) -> int:
    rc = 0
    sources = _sources(settings)
    report: dict = {"issue": args.issue, "books": []}
    for book in _select_books(settings, args.ids):
        entry: dict = {"id": book.id, "title": book.title, "blogs": book.blogs, "built": []}
        try:
            results = _build(settings, book, sources, issue=args.issue, collectors=args.collectors)
        except ValueError as exc:
            log.error("%s", exc)
            entry["error"] = str(exc)
            rc = 2
        else:
            entry["built"] = [_built(r) for r in results]
            if results:
                report["issue"] = report["issue"] or results[0].issue
            for r in results:
                print(_build_line(r))
        report["books"].append(entry)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return rc


def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    report: dict = {"changed": False, "issue": args.issue, "blogs": [], "books": []}
    rc = 0
    changed_blogs: set[str] = set()
    synced = _sync_blogs(
        settings, _select_blogs(settings, args.ids), full=args.full, prune=args.prune, jobs=args.jobs
    )
    for blog, store, result in synced:
        entry: dict = {"id": blog.id, "title": blog.title, "url": blog.url}
        if isinstance(result, Exception):
            entry["error"] = str(result)
            report["blogs"].append(entry)
            rc = 2
            continue
        entry.update(
            {
                "source": result.source,
                "discovered": result.discovered,
                "new": result.new,
                "updated": result.updated,
                "removed": result.removed,
                "errors": result.errors,
                "cached": len(store.post_index),
            }
        )
        if result.changed:
            changed_blogs.add(blog.id)
        report["blogs"].append(entry)

    sources = _sources(settings)
    for book in _select_books(settings, args.ids):
        existing = book_outputs(settings.output_dir, book.id)
        touched = bool(changed_blogs & set(book.blogs))
        entry = {"id": book.id, "title": book.title, "blogs": book.blogs, "built": []}
        if touched or args.force or not existing:
            try:
                results = _build(settings, book, sources, issue=args.issue)
            except ValueError as exc:
                log.error("%s", exc)
                entry["error"] = str(exc)
                rc = 2
            else:
                entry["built"] = [_built(r) for r in results]
                if results:
                    report["issue"] = report.get("issue") or results[0].issue
                report["changed"] = report["changed"] or touched or not existing
                for r in results:
                    print(_build_line(r))
        else:
            print(f"{book.id}: no changes, keeping {', '.join(p.name for p in existing)}")
        report["books"].append(entry)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return rc


def cmd_status(settings: Settings, args: argparse.Namespace) -> int:
    for blog in settings.blogs:
        store = BlogStore(settings.cache_dir, blog.id)
        idx = store.index
        dates = sorted(d for d in (v.get("date") for v in store.post_index.values()) if d)
        ok = sum(1 for v in store.image_index.values() if not v.get("error"))
        print(f"blog {blog.id} ({blog.title})")
        print(f"  source:     {idx.get('source') or 'not synced yet'}")
        print(f"  last sync:  {idx.get('last_sync') or '-'}")
        print(
            f"  posts:      {len(store.post_index)}"
            + (f"  ({dates[0][:10]} .. {dates[-1][:10]})" if dates else "")
        )
        print(f"  images:     {ok} cached, {len(store.image_index) - ok} failed")
    for book in settings.all_books():
        outputs = book_outputs(settings.output_dir, book.id)
        print(f"book {book.id} ({book.title}) <- {', '.join(book.blogs)}")
        for p in outputs:
            print(f"  output:     {p} ({p.stat().st_size / 1e6:.1f} MB)")
        if not outputs:
            print("  output:     not built yet")
    return 0


# ---- entry point ---------------------------------------------------------------
def _issue(value: str) -> str:
    if not re.fullmatch(r"\d{8}", value):
        raise argparse.ArgumentTypeError(f"issue must be YYYYMMDD, e.g. 20260905, not {value!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="blog2epub", description="Monitor blogs and turn them into EPUB books.")
    p.add_argument("-c", "--config", default="blogs.yaml", help="path to blogs.yaml (default: ./blogs.yaml)")
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v for info, -vv for debug")
    p.add_argument("--version", action="version", version=f"blog2epub {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show configured blogs and books").set_defaults(func=cmd_list)

    d = sub.add_parser("detect", help="probe a URL and report which source would be used")
    d.add_argument("url")
    d.add_argument("--source", default="auto", choices=["auto", "wordpress", "feed", "sitemap"])
    d.add_argument("--id", help="blog id to use in the suggested config")
    d.add_argument("--sample", type=int, default=5, help="how many discovered posts to print")
    d.set_defaults(func=cmd_detect)

    for name, func, help_ in (
        ("sync", cmd_sync, "fetch new and changed posts into the cache"),
        ("build", cmd_build, "write EPUB(s) from the cache"),
        ("run", cmd_run, "sync, then build every book whose blogs changed"),
    ):
        s = sub.add_parser(name, help=help_)
        s.add_argument("ids", nargs="*", help="blog or book ids (default: all)")
        if name != "build":
            s.add_argument("--full", action="store_true", help="re-fetch every post, retry failed images")
            s.add_argument(
                "--prune", action="store_true", help="drop cached posts the source no longer lists"
            )
            s.add_argument(
                "--jobs",
                type=int,
                default=DEFAULT_JOBS,
                metavar="N",
                help=f"blogs to sync at once (default {DEFAULT_JOBS}; 1 for one at a time). "
                "Blogs on the same host still take turns.",
            )
        if name == "run":
            s.add_argument("--force", action="store_true", help="rebuild even when nothing changed")
        if name in ("build", "run"):
            s.add_argument(
                "--issue",
                metavar="YYYYMMDD",
                type=_issue,
                help="issue date the volumes are numbered under (default: today, UTC)",
            )
            s.add_argument("--report", metavar="FILE", help="write a JSON summary (used by CI)")
        if name == "build":
            s.add_argument(
                "--collectors",
                action="store_true",
                help="build the whole archive as one file, the collector's edition, "
                "as <book>-collectors-<issue>.epub, ignoring split and max_book_bytes",
            )
        s.set_defaults(func=func)

    sub.add_parser("status", help="show cache and output state").set_defaults(func=cmd_status)
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
    except BrokenPipeError:
        # `blog2epub list | head` closes the pipe early; exit quietly like any well-behaved CLI.
        # Point stdout at /dev/null so the interpreter does not complain again while shutting
        # down; stdout may have no file descriptor at all (pytest capture, redirection).
        with contextlib.suppress(OSError, ValueError, io.UnsupportedOperation):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
