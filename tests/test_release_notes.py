"""scripts/release_notes.py: one issue, one release, one section per book.

The notes have to describe the release rather than the run that wrote them last — a book rebuilt
on its own keeps the other books' sections — and a book that failed has to be named rather than
silently absent.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "release_notes.py"
spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
release_notes = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(release_notes)


def _volume(file: str, *, label: str = "", posts: int = 10, size: int = 5_000_000) -> dict:
    return {
        "file": file,
        "title": "Tyk Blog",
        "label": label,
        "posts": posts,
        "bytes": size,
        "first_date": "2026-01-02",
        "last_date": "2026-09-01",
    }


def _report(book_id: str, title: str, volumes: list[dict]) -> dict:
    return {"issue": "20260917", "books": [{"id": book_id, "title": title, "built": volumes}]}


def test_a_book_of_volumes_gets_a_table():
    report = _report(
        "tyk",
        "Tyk Blog",
        [_volume("tyk-20260917.2026.epub", label="2026"), _volume("tyk-20260917.2025.epub", label="2025")],
    )
    notes = release_notes.compose([report], "20260917")

    assert "### Tyk Blog — `tyk`" in notes
    assert "| File | Volume | Posts | Covering | Size |" in notes
    assert "| `tyk-20260917.2026.epub` | 2026 | 10 | 2026-01-02 to 2026-09-01 | 5.0 MB |" in notes
    assert "20 posts in 2 volumes" in notes


def test_a_one_volume_book_gets_a_line_not_a_table():
    notes = release_notes.compose([_report("kong", "Kong Blog", [_volume("kong-20260917.epub")])], "20260917")

    assert "| File |" not in notes
    assert "`kong-20260917.epub`: 10 posts, 2026-01-02 to 2026-09-01, 5.0 MB." in notes


def test_every_book_of_the_run_is_one_release():
    reports = [
        _report("tyk", "Tyk Blog", [_volume("tyk-20260917.epub")]),
        _report("kong", "Kong Blog", [_volume("kong-20260917.epub")]),
    ]
    notes = release_notes.compose(reports, "20260917")

    assert notes.startswith("Issue 20260917, built by blog2epub: 2 books, 2 files, 10.0 MB.")
    assert notes.index("`kong`") < notes.index("`tyk`")  # sorted, so the notes read the same way twice


def test_a_book_already_in_the_release_keeps_its_section():
    """Re-running one book of an issue must not rewrite the notes down to that book."""
    reports = [_report("tyk", "Tyk Blog", [_volume("tyk-20260917.epub")])]
    assets = [
        {"name": "tyk-20260917.epub", "size": 5_000_000},
        {"name": "kong-20260917.2025.epub", "size": 3_000_000},
        {"name": "kong-20260917.2026.epub", "size": 4_000_000},
    ]
    notes = release_notes.compose(reports, "20260917", assets=assets)

    assert "### Tyk Blog — `tyk`" in notes
    assert "### `kong`" in notes
    assert "Kept from an earlier run of this issue." in notes
    assert "| `kong-20260917.2025.epub` | 3.0 MB |" in notes
    assert notes.startswith("Issue 20260917, built by blog2epub: 2 books, 3 files, 12.0 MB.")


def test_assets_from_another_issue_are_not_counted():
    """The same release only ever holds one issue, but a stray file must not invent a book."""
    notes = release_notes.compose(
        [_report("tyk", "Tyk Blog", [_volume("tyk-20260917.epub")])],
        "20260917",
        assets=[{"name": "kong-20260101.epub", "size": 9_000_000}],
    )

    assert "kong" not in notes


def test_a_book_that_failed_is_named():
    notes = release_notes.compose(
        [_report("tyk", "Tyk Blog", [_volume("tyk-20260917.epub")])],
        "20260917",
        asked=["tyk", "kong"],
    )

    assert "## Not in this issue" in notes
    assert "- `kong`" in notes


def test_the_collectors_edition_matches_its_own_files():
    """The report says `tyk`; the file is `tyk-collectors-...`. One book, one section."""
    reports = [_report("tyk", "Tyk Blog", [_volume("tyk-collectors-20260917.epub", size=60_800_000)])]
    notes = release_notes.compose(
        reports,
        "20260917",
        collectors=True,
        asked=["tyk", "kong"],
        assets=[{"name": "tyk-collectors-20260917.epub", "size": 60_800_000}],
    )

    assert notes.startswith("Collector's editions 20260917, built by blog2epub: 1 book, 1 file, 60.8 MB.")
    assert "### Tyk Blog — `tyk-collectors`" in notes
    assert "Kept from an earlier run" not in notes
    assert "- `kong-collectors`" in notes


def test_gigabytes_once_an_issue_is_large():
    volumes = [
        _volume(f"axway-20260917.{year}.epub", label=str(year), size=600_000_000) for year in (2025, 2026)
    ]
    notes = release_notes.compose([_report("axway", "Axway Blog", volumes)], "20260917")

    assert "1.20 GB." in notes


@pytest.mark.parametrize(
    ("name", "book"),
    [
        ("tyk-20260917.epub", "tyk"),
        ("tyk-20260917.2026.epub", "tyk"),
        ("api-management-20260917.epub", "api-management"),
        ("tyk-collectors-20260917.epub", "tyk-collectors"),
    ],
)
def test_a_file_says_which_book_it_belongs_to(name, book):
    assert release_notes.ASSET.match(name)["id"] == book
