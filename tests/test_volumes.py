"""Cutting a book into volumes: by size (the default), by year or month, and not at all."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from blog2epub import epub as epub_mod
from blog2epub.config import BookConfig, ConfigError, parse_size
from blog2epub.covers import cover_values, volume_label
from blog2epub.epub import book_outputs, build_book, select_entries
from tests.conftest import PNG_1x1, make_post

ISSUE = "20260905"
KB = 1000


def _image(store, name: str, size: int) -> str:
    url = f"https://example.com/img/{name}.jpg"
    store.put_image(url, os.urandom(size), "jpg", "image/jpeg")
    return url


def _archive(store, sizes: list[int], shared: str | None = None):
    """One post per size, each with its own image that big; `shared` adds one image to every post."""
    urls = [_image(store, f"pic{i}", size) for i, size in enumerate(sizes, start=1)]
    for i, url in enumerate(urls, start=1):
        extra = f'<img src="{shared}" alt="s">' if shared else ""
        prev = f'<a href="https://example.com/blog/post-{i - 1}/">previous</a>' if i > 1 else ""
        post = make_post(
            f"wp-{i}",
            f"2023-{i:02d}-01T10:00:00+00:00",
            html=f'<p>post {i} {prev}<img src="{url}" alt="p">{extra}</p>',
        )
        post.blog_id = "demo"
        store.put_post(post)
    store.save()


def _book(blog, **opts) -> BookConfig:
    book = blog.as_book()
    book.optimize_images = False  # random bytes are not a JPEG; keep the sizes we planted
    book.featured_images = False
    book.split = "size"  # the tests below are about the packer; the year default has its own tests
    for k, v in opts.items():
        setattr(book, k, v)
    return book


def _build(blog, store, tmp_path, **opts):
    return build_book(_book(blog, **opts), {blog.id: (blog, store)}, tmp_path / "out", issue=ISSUE)


def test_size_split_packs_posts_in_reading_order_under_the_budget(tmp_path, blog, store):
    _archive(store, [300 * KB, 300 * KB, 300 * KB, 300 * KB])
    # budget = 97% of 2.3 MB minus the 1.5 MB reserved for cover and navigation: about 730 kB,
    # room for two 300 kB images per volume.
    results = _build(blog, store, tmp_path, max_book_bytes=2_300_000)
    assert [r.posts for r in results] == [2, 2]
    assert [r.path.name for r in results] == [f"demo-{ISSUE}-vol1.epub", f"demo-{ISSUE}-vol2.epub"]
    assert [(r.volume, r.volumes, r.label, r.title) for r in results] == [
        (1, 2, "Vol. 1 of 2", "Demo Blog, Vol. 1"),
        (2, 2, "Vol. 2 of 2", "Demo Blog, Vol. 2"),
    ]
    assert all(r.size <= 2_300_000 for r in results)
    # reading order is preserved across the cut: oldest posts first, as the book's order says
    first = zipfile.ZipFile(results[0].path).read("OEBPS/nav.xhtml").decode()
    assert "Post wp-1" in first and "Post wp-3" not in first


def test_an_image_shared_by_two_posts_is_weighed_once_per_volume(tmp_path, blog, store):
    shared = _image(store, "shared", 400 * KB)
    _archive(store, [100 * KB, 100 * KB], shared=shared)
    # Two posts at 100 kB each plus one 400 kB image between them fit a 730 kB budget only if
    # the shared image is counted once. Counted twice they would not.
    results = _build(blog, store, tmp_path, max_book_bytes=2_300_000)
    assert [r.posts for r in results] == [2]
    assert results[0].images == 3


def test_a_post_bigger_than_the_budget_gets_its_own_volume(tmp_path, blog, store, caplog):
    _archive(store, [50 * KB, 900 * KB, 50 * KB])
    results = _build(blog, store, tmp_path, max_book_bytes=2_300_000)
    assert [r.posts for r in results] == [1, 1, 1]
    assert "more than max_book_bytes allows" in caplog.text


def test_links_to_a_post_in_another_volume_fall_back_to_its_url(tmp_path, blog, store):
    _archive(store, [300 * KB, 300 * KB, 300 * KB])
    results = _build(blog, store, tmp_path, max_book_bytes=2_300_000)
    assert [r.posts for r in results] == [2, 1]
    vol1 = zipfile.ZipFile(results[0].path)
    vol2 = zipfile.ZipFile(results[1].path)
    # post 2 sits with post 1: the link stays inside the book
    assert 'href="ch-0001.xhtml"' in vol1.read("OEBPS/Text/ch-0002.xhtml").decode()
    # post 3 links to post 2, which is in volume 1: the link goes back to the web
    assert 'href="https://example.com/blog/post-2/"' in vol2.read("OEBPS/Text/ch-0003.xhtml").decode()
    assert "ch-0002.xhtml" not in vol2.read("OEBPS/Text/ch-0003.xhtml").decode()


def test_a_small_book_is_one_volume_with_no_volume_label(tmp_path, blog, store):
    _archive(store, [10 * KB, 10 * KB])
    results = _build(blog, store, tmp_path)  # split: size at the 200 MB default
    assert len(results) == 1
    r = results[0]
    # One volume needs no suffix at all: demo-20260905.epub
    assert (r.path.name, r.title, r.label, r.volume, r.volumes) == (
        f"demo-{ISSUE}.epub",
        "Demo Blog",
        "",
        1,
        1,
    )
    title_page = zipfile.ZipFile(r.path).read("OEBPS/Text/title.xhtml").decode()
    assert f"Issue {ISSUE}.1" in title_page and "Volume" not in title_page


def test_split_none_ignores_the_budget(tmp_path, blog, store):
    _archive(store, [300 * KB] * 4)
    results = _build(blog, store, tmp_path, split="none", max_book_bytes=2_300_000)
    assert [r.posts for r in results] == [4]


def test_the_default_split_is_by_year_and_a_year_never_passes_the_budget(tmp_path, blog, store):
    # Four 300 kB posts in one year against a 730 kB budget: the year is cut in two, and says so.
    _archive(store, [300 * KB] * 4)
    book = blog.as_book()
    book.optimize_images = book.featured_images = False
    book.max_book_bytes = 2_300_000
    assert book.split == "year"
    results = build_book(book, {blog.id: (blog, store)}, tmp_path / "out", issue=ISSUE)
    assert [(r.title, r.label, r.posts) for r in results] == [
        ("Demo Blog 2023, part 1 of 2", "2023, part 1 of 2", 2),
        ("Demo Blog 2023, part 2 of 2", "2023, part 2 of 2", 2),
    ]
    assert all(r.size <= 2_300_000 for r in results)


def test_a_year_split_within_budget_is_labelled_by_year_alone(tmp_path, blog, store):
    _archive(store, [10 * KB] * 2)
    results = _build(blog, store, tmp_path, split="year")
    assert [(r.title, r.label, r.volume, r.volumes) for r in results] == [("Demo Blog 2023", "2023", 1, 1)]


def test_split_by_month(tmp_path, blog, store):
    _archive(store, [10 * KB] * 3)  # January, February, March 2023
    results = _build(blog, store, tmp_path, split="month")
    assert [(r.title, r.label) for r in results] == [
        ("Demo Blog, January 2023", "January 2023"),
        ("Demo Blog, February 2023", "February 2023"),
        ("Demo Blog, March 2023", "March 2023"),
    ]


def test_a_rebuild_removes_the_previous_issue_but_not_another_books_files(tmp_path, blog, store):
    _archive(store, [10 * KB] * 2)
    out = tmp_path / "out"
    out.mkdir()
    stale = [
        out / "demo-20250101-2023.epub",  # the current shape
        out / "demo-20250101.2.epub",  # the shape the first issues used
        out / "demo.epub",  # and the shapes before issues existed
        out / "demo-2019.epub",
    ]
    other = [out / "demo-extra-20250101.1.epub", out / "demonstration.epub"]
    for p in stale + other:
        p.write_bytes(b"old")
    build_book(_book(blog), {blog.id: (blog, store)}, out, issue=ISSUE)
    assert not any(p.exists() for p in stale)
    assert all(p.exists() for p in other)
    assert [p.name for p in book_outputs(out, "demo")] == [f"demo-{ISSUE}.epub"]


def test_book_outputs_is_exact_on_the_id(tmp_path):
    out = tmp_path
    for name in (
        "api-20260905.1.epub",
        "api.epub",
        "api-2020.epub",
        "api-management-20260905.1.epub",
        "apix.epub",
    ):
        (out / name).write_bytes(b"")
    assert [p.name for p in book_outputs(out, "api")] == ["api-2020.epub", "api-20260905.1.epub", "api.epub"]
    assert [p.name for p in book_outputs(out, "api-management")] == ["api-management-20260905.1.epub"]
    assert book_outputs(tmp_path / "nowhere", "api") == []


def test_issue_must_be_a_date(tmp_path, blog, store):
    _archive(store, [10 * KB])
    with pytest.raises(ValueError, match="YYYYMMDD"):
        build_book(_book(blog), {blog.id: (blog, store)}, tmp_path / "out", issue="2026.09.05")


# ---- covers per volume ---------------------------------------------------------------


def test_cover_values_describe_the_volume_not_the_book(blog, store):
    _archive(store, [10 * KB] * 3)
    entries = select_entries(blog.as_book(), {blog.id: (blog, store)})
    values = cover_values(blog.as_book(), entries[:2], issue=ISSUE, volume=1, volumes=2)
    assert (values["count"], values["issue_number"], values["volume_label"]) == (
        "2",
        f"{ISSUE}.1",
        "Vol. 1 of 2",
    )
    assert (values["first_year"], values["last_year"]) == ("2023", "2023")
    assert (values["years"], values["years_prose"]) == ("2023", "2023")  # one year, said once
    assert values["title1"] == "Post wp-2"  # newest post in the volume leads
    single = cover_values(blog.as_book(), entries, issue=ISSUE)
    assert (single["issue_number"], single["volume_label"], single["count"]) == (f"{ISSUE}.1", "", "3")
    assert volume_label(3, 3) == "Vol. 3 of 3" and volume_label(1, 1) == ""
    # a year split puts the year on the cover, not a volume count
    yearly = cover_values(blog.as_book(), entries, issue=ISSUE, volume=3, volumes=12, label="2024")
    assert yearly["volume_label"] == "2024"


def test_a_span_of_years_is_written_as_a_range(blog, store):
    for i, year in enumerate((2015, 2020, 2026), start=1):
        post = make_post(f"wp-{i}", f"{year}-06-01T10:00:00+00:00", html="<p>x</p>")
        post.blog_id = "demo"
        store.put_post(post)
    store.save()
    entries = select_entries(blog.as_book(), {blog.id: (blog, store)})
    values = cover_values(blog.as_book(), entries, issue=ISSUE)
    assert (values["years"], values["years_prose"]) == ("2015 \u2013 2026", "2015 to 2026")


def test_a_template_cover_is_rendered_once_per_volume(tmp_path, blog, store, monkeypatch):
    _archive(store, [300 * KB] * 3)
    template = tmp_path / "demo.html"
    template.write_text("<h1>$title $issue_number $volume_label $count</h1>")
    seen: list[tuple[Path, dict[str, str]]] = []

    def fake_render(tpl: Path, out: Path, values: dict[str, str], **_) -> list[str]:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(PNG_1x1)
        seen.append((out, values))
        return []

    monkeypatch.setattr(epub_mod, "playwright_available", lambda: True)
    monkeypatch.setattr(epub_mod, "render_cover_template", fake_render)
    results = build_book(
        _book(blog, max_book_bytes=2_300_000),
        {blog.id: (blog, store)},
        tmp_path / "out",
        template,
        issue=ISSUE,
    )
    assert [r.posts for r in results] == [2, 1]
    assert [out.name for out, _ in seen] == [f"demo-{ISSUE}-vol1.jpg", f"demo-{ISSUE}-vol2.jpg"]
    assert [v["issue_number"] for _, v in seen] == [f"{ISSUE}.1", f"{ISSUE}.2"]
    assert [v["count"] for _, v in seen] == ["2", "1"]
    assert [v["volume_label"] for _, v in seen] == ["Vol. 1 of 2", "Vol. 2 of 2"]
    for r in results:
        assert r.cover is not None and r.cover.name == f"demo-{ISSUE}-vol{r.volume}.jpg"
        assert "OEBPS/Images/cover.jpg" in zipfile.ZipFile(r.path).namelist()


def test_without_playwright_a_template_falls_back_to_the_image_beside_it(
    tmp_path, blog, store, monkeypatch, caplog
):
    _archive(store, [10 * KB])
    template = tmp_path / "demo.html"
    template.write_text("<h1>$title</h1>")
    template.with_suffix(".png").write_bytes(PNG_1x1)
    monkeypatch.setattr(epub_mod, "playwright_available", lambda: False)
    results = build_book(_book(blog), {blog.id: (blog, store)}, tmp_path / "out", template, issue=ISSUE)
    assert results[0].cover == template.with_suffix(".png")
    assert "Playwright is not installed" in caplog.text


def test_a_failed_render_still_builds_the_volume(tmp_path, blog, store, monkeypatch, caplog):
    _archive(store, [10 * KB])
    template = tmp_path / "demo.html"
    template.write_text("<h1>$title</h1>")

    def boom(*_, **__):
        raise RuntimeError("no chromium here")

    monkeypatch.setattr(epub_mod, "playwright_available", lambda: True)
    monkeypatch.setattr(epub_mod, "render_cover_template", boom)
    results = build_book(_book(blog), {blog.id: (blog, store)}, tmp_path / "out", template, issue=ISSUE)
    assert results[0].cover is None  # generated cover instead
    assert "could not render cover" in caplog.text
    assert "OEBPS/Images/cover.png" in zipfile.ZipFile(results[0].path).namelist()


# ---- config ------------------------------------------------------------------------------


def test_split_defaults_to_year_and_rejects_the_unknown():
    assert BookConfig(id="b", blogs=["a"]).split == "year"
    assert BookConfig(id="b", blogs=["a"]).max_book_bytes == 200_000_000
    with pytest.raises(ConfigError, match="split"):
        BookConfig(id="b", blogs=["a"], split="chapter")


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("200MB", 200_000_000),
        ("150 M", 150_000_000),
        ("1.5GB", 1_500_000_000),
        (5_000_000, 5_000_000),
        ("64kb", 64_000),
    ],
)
def test_parse_size(given, expected):
    assert parse_size(given) == expected


@pytest.mark.parametrize("bad", ["0", "lots", -5, "MB", True])
def test_parse_size_rejects_nonsense(bad):
    with pytest.raises(ConfigError):
        parse_size(bad)


# ---- the collector's edition ----------------------------------------------------------


def test_collectors_edition_is_one_file_under_its_own_name(tmp_path, blog, store):
    _archive(store, [300 * KB] * 4)  # four posts across 2023, well over the budget below
    out = tmp_path / "out"
    book = _book(blog, max_book_bytes=2_300_000)
    split = build_book(book, {blog.id: (blog, store)}, out, issue=ISSUE)
    collected = build_book(book, {blog.id: (blog, store)}, out, issue=ISSUE, collectors=True)

    # the whole archive in one file, whatever split and max_book_bytes say
    assert [r.posts for r in split] == [2, 2]  # the split edition had to cut it
    assert [(r.path.name, r.posts) for r in collected] == [(f"demo-collectors-{ISSUE}.epub", 4)]
    assert collected[0].size > max(r.size for r in split)  # everything in the one file
    assert (collected[0].title, collected[0].label) == (
        "Demo Blog — Collector's Edition",
        "Collector's Edition",
    )
    title_page = zipfile.ZipFile(collected[0].path).read("OEBPS/Text/title.xhtml").decode()
    assert "Collector&#8217;s Edition" in title_page or "Collector's Edition" in title_page


def test_the_two_editions_never_clear_each_others_files(tmp_path, blog, store):
    _archive(store, [300 * KB] * 3)
    out = tmp_path / "out"
    book = _book(blog, max_book_bytes=2_300_000)
    build_book(book, {blog.id: (blog, store)}, out, issue=ISSUE, collectors=True)
    build_book(book, {blog.id: (blog, store)}, out, issue=ISSUE)  # rebuilding one...
    assert (out / f"demo-collectors-{ISSUE}.epub").exists()  # ...leaves the other alone
    build_book(book, {blog.id: (blog, store)}, out, issue=ISSUE, collectors=True)
    assert len(book_outputs(out, "demo")) > 1
    assert [p.name for p in book_outputs(out, "demo-collectors")] == [f"demo-collectors-{ISSUE}.epub"]


def test_a_collectors_rebuild_replaces_its_own_previous_issue(tmp_path, blog, store):
    _archive(store, [10 * KB] * 2)
    out = tmp_path / "out"
    out.mkdir()
    (out / "demo-collectors-20250101.epub").write_bytes(b"old")
    build_book(_book(blog), {blog.id: (blog, store)}, out, issue=ISSUE, collectors=True)
    assert not (out / "demo-collectors-20250101.epub").exists()
    assert [p.name for p in book_outputs(out, "demo-collectors")] == [f"demo-collectors-{ISSUE}.epub"]
