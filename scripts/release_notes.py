#!/usr/bin/env python3
"""Compose the notes for an issue's release from the books' build reports.

    scripts/release_notes.py --issue 20260917 reports/*.json > notes.md
    scripts/release_notes.py --issue 20260917 --assets assets.jsonl --asked tyk,kong reports/*.json

One release holds every book built that day, so the notes are a section per book: a table of its
volumes, or a line when the book is one file. Two inputs keep the notes true to what the release
actually holds, rather than to this run alone:

  --assets   the release's current assets, one `{"name":…,"size":…}` per line, as
             `gh api repos/<repo>/releases/<id>/assets --jq '.[] | {name, size}'` writes them.
             A book rebuilt on its own does not erase the sections of the books already there.
  --asked    the ids the run planned to build, so a book whose job failed is named in the notes
             instead of quietly missing.

Reading the reports here rather than in the workflow keeps the YAML short and the formatting
testable; the report shape is what `blog2epub build --report` writes.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# tyk-20260917.2026.epub, api-management-20260917.epub, tyk-collectors-20260917.epub
ASSET = re.compile(r"^(?P<id>.+?)-(?P<issue>\d{8})(?P<volume>\..+)?\.epub$")


def _size(nbytes: float) -> str:
    return f"{nbytes / 1e9:.2f} GB" if nbytes >= 1e9 else f"{nbytes / 1e6:.1f} MB"


def _span(volume: dict) -> str:
    first, last = volume.get("first_date"), volume.get("last_date")
    return f"{first} to {last}" if first and last else (first or "")


def _from_report(book: dict, book_id: str) -> list[str]:
    volumes = book["built"]
    lines = [f"### {book.get('title') or book_id} — `{book_id}`", ""]
    if len(volumes) > 1:
        posts = sum(v["posts"] for v in volumes)
        lines += [
            f"{posts} posts in {len(volumes)} volumes, each under the size Send to Kindle accepts.",
            "",
            "| File | Volume | Posts | Covering | Size |",
            "| --- | --- | --- | --- | --- |",
            *(
                f"| `{v['file']}` | {v.get('label') or v.get('title') or ''} | {v['posts']} "
                f"| {_span(v)} | {_size(v['bytes'])} |"
                for v in volumes
            ),
        ]
    else:
        v = volumes[0]
        span = f", {_span(v)}" if _span(v) else ""
        lines.append(f"`{v['file']}`: {v['posts']} posts{span}, {_size(v['bytes'])}.")
    return [*lines, ""]


def _from_assets(book_id: str, assets: list[dict]) -> list[str]:
    """A book this run did not build, kept from an earlier run of the same issue."""
    lines = [f"### `{book_id}`", "", "Kept from an earlier run of this issue.", ""]
    if len(assets) > 1:
        lines += [
            "| File | Size |",
            "| --- | --- |",
            *(f"| `{a['name']}` | {_size(a['size'])} |" for a in assets),
        ]
    else:
        lines.append(f"`{assets[0]['name']}`: {_size(assets[0]['size'])}.")
    return [*lines, ""]


def compose(
    reports: list[dict],
    issue: str,
    *,
    collectors: bool = False,
    asked: list[str] | None = None,
    assets: list[dict] | None = None,
) -> str:
    """The release body: a summary line, a section per book, then what is missing."""
    suffix = "-collectors" if collectors else ""
    built = {b["id"] + suffix: b for r in reports for b in r.get("books", []) if b.get("built")}

    by_book: dict[str, list[dict]] = {}
    for asset in assets or []:
        match = ASSET.match(asset["name"])
        if match and match["issue"] == issue:
            by_book.setdefault(match["id"], []).append(asset)
    for volumes in by_book.values():
        volumes.sort(key=lambda a: a["name"])

    ids = sorted(set(built) | set(by_book))
    files = sum(len(built[i]["built"]) if i in built else len(by_book[i]) for i in ids)
    total = sum(
        sum(v["bytes"] for v in built[i]["built"]) if i in built else sum(a["size"] for a in by_book[i])
        for i in ids
    )

    edition = "Collector's editions" if collectors else "Issue"
    lines = [
        f"{edition} {issue}, built by blog2epub: {len(ids)} book{'s' if len(ids) != 1 else ''}, "
        f"{files} file{'s' if files != 1 else ''}, {_size(total)}.",
        "",
    ]
    if collectors:
        lines += [
            "Each book is the complete archive in a single file, past what Send to Kindle "
            "accepts — for keeping and copying over USB rather than emailing.",
            "",
        ]
    lines += ["## Books", ""]
    for book_id in ids:
        book = built.get(book_id)
        lines += _from_report(book, book_id) if book else _from_assets(book_id, by_book[book_id])

    missing = sorted({a + suffix for a in asked or []} - set(ids))
    if missing:
        lines += [
            "## Not in this issue",
            "",
            "These books did not build; the run log says why. Their last good issue is unchanged.",
            "",
            *(f"- `{book_id}`" for book_id in missing),
            "",
        ]
    lines += [
        "---",
        "",
        f"Every file is named `<book>-{issue}[.volume].epub`, so a download says which issue it "
        "came from. EPUB 3, validated with epubcheck. Copy to your e-reader or send to Kindle.",
    ]
    return "\n".join(lines)


def _read_assets(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="*", type=Path, help="build.json files, one per book")
    parser.add_argument("--issue", required=True, help="the issue date, YYYYMMDD")
    parser.add_argument("--collectors", action="store_true", help="the one-file edition")
    parser.add_argument("--assets", type=Path, help="the release's assets, one JSON object a line")
    parser.add_argument("--asked", default="", help="comma-separated ids the run planned to build")
    args = parser.parse_args()

    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    asked = [b.strip() for b in args.asked.split(",") if b.strip()]
    print(
        compose(
            reports,
            args.issue,
            collectors=args.collectors,
            asked=asked,
            assets=_read_assets(args.assets),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
