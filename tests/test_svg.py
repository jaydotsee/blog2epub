"""SVG handling: rasterise (default), keep, drop; fallback cover rasterised."""

from __future__ import annotations

import io
import zipfile

import pytest

from blog2epub.config import BookConfig, ConfigError
from blog2epub.epub import build_epub, select_entries
from blog2epub.images import downgrade_modern_css
from tests.conftest import make_post

cairosvg = pytest.importorskip("cairosvg")

SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="#3366cc"/></svg>'
URL = "https://example.com/img/diagram.svg"


def _book_with_svg(blog, store, mode):
    store.put_image(URL, SVG, "svg", "image/svg+xml")
    store.put_post(
        make_post("wp-1", "2024-01-01T00:00:00+00:00", html=f'<p>see <img src="{URL}" alt="diagram"></p>')
    )
    store.save()
    book = blog.as_book()
    book.svg_images = mode
    return book


def _names_and_chapter(path):
    z = zipfile.ZipFile(path)
    return z.namelist(), z.read("OEBPS/Text/ch-0001.xhtml").decode(), z


def test_svg_rasterised_by_default(tmp_path, blog, store):
    book = _book_with_svg(blog, store, "raster")
    r = build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "r.epub")
    names, ch, z = _names_and_chapter(tmp_path / "r.epub")
    assert r.images == 1
    assert not [n for n in names if n.endswith(".svg")]
    png = [n for n in names if n.endswith(".svg.png")]
    assert len(png) == 1 and z.read(png[0]).startswith(b"\x89PNG")
    assert 'src="../Images/' in ch and ".svg.png" in ch
    opf = z.read("OEBPS/content.opf").decode()
    assert 'media-type="image/png"' in opf and "image/svg+xml" not in opf


def test_svg_kept_when_asked(tmp_path, blog, store):
    book = _book_with_svg(blog, store, "keep")
    build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "k.epub")
    names, ch, _ = _names_and_chapter(tmp_path / "k.epub")
    assert [n for n in names if n.endswith(".svg")] and ".svg.png" not in ch


def test_svg_dropped_when_asked(tmp_path, blog, store):
    book = _book_with_svg(blog, store, "drop")
    r = build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "d.epub")
    names, ch, _ = _names_and_chapter(tmp_path / "d.epub")
    assert r.images == 0 and not [n for n in names if "diagram" in n or n.endswith(".svg")]
    assert "[image: diagram]" in ch


def test_generated_cover_is_png_unless_keep(tmp_path, blog, store):
    store.put_post(make_post("wp-1", "2024-01-01T00:00:00+00:00"))
    store.save()
    book = blog.as_book()
    build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "c.epub")
    z = zipfile.ZipFile(tmp_path / "c.epub")
    assert "OEBPS/Images/cover.png" in z.namelist() and z.read("OEBPS/Images/cover.png").startswith(
        b"\x89PNG"
    )
    assert (
        'href="Images/cover.png" media-type="image/png" properties="cover-image"'
        in z.read("OEBPS/content.opf").decode()
    )
    book.svg_images = "keep"
    build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "s.epub")
    assert "OEBPS/Images/cover.svg" in zipfile.ZipFile(tmp_path / "s.epub").namelist()


def test_config_validates_svg_images():
    with pytest.raises(ConfigError):
        BookConfig(id="b", blogs=["x"], svg_images="vectorise")


def test_images_are_downscaled_and_reencoded(tmp_path, blog, store):
    """Blogs serve desktop-sized images; a whole archive of them is unreadably large."""
    import zipfile

    from PIL import Image

    from blog2epub.epub import build_epub, select_entries
    from tests.conftest import make_post

    big = tmp_path / "big.png"
    Image.new("RGB", (3000, 1800), (30, 90, 160)).save(big, "PNG")
    url = "https://example.com/img/big.png"
    store.put_image(url, big.read_bytes(), "png", "image/png")
    store.put_post(make_post("wp-1", "2024-01-01T00:00:00+00:00", html=f'<p>x <img src="{url}" alt="b"></p>'))
    store.save()

    book = blog.as_book()
    build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "small.epub")
    z = zipfile.ZipFile(tmp_path / "small.epub")
    embedded = next(n for n in z.namelist() if "/Images/" in n and "cover" not in n)
    with Image.open(io.BytesIO(z.read(embedded))) as im:
        assert im.width == blog.max_image_width  # downscaled, not merely re-encoded
    assert len(z.read(embedded)) < big.stat().st_size

    book.optimize_images = False
    build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "orig.epub")
    z2 = zipfile.ZipFile(tmp_path / "orig.epub")
    original = next(n for n in z2.namelist() if "/Images/" in n and "cover" not in n)
    with Image.open(io.BytesIO(z2.read(original))) as im:
        assert im.width == 3000


def test_build_reports_what_optimisation_saved(tmp_path, blog, store):
    """The saving has to be visible, or a silently huge book looks normal."""
    # noise, so it compresses like a real photograph rather than to nothing
    import os

    from PIL import Image

    from blog2epub.cli import _build_line
    from blog2epub.epub import build_epub, select_entries
    from tests.conftest import make_post

    big = tmp_path / "big.jpg"
    Image.frombytes("RGB", (2000, 1500), os.urandom(2000 * 1500 * 3)).save(big, "JPEG", quality=95)
    url = "https://example.com/img/big.jpg"
    store.put_image(url, big.read_bytes(), "jpg", "image/jpeg")
    store.put_post(make_post("wp-1", "2024-01-01T00:00:00+00:00", html=f'<p>x <img src="{url}" alt="b"></p>'))
    store.save()

    book = blog.as_book()
    r = build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "b.epub")
    assert r.image_bytes_before > r.image_bytes > 0
    assert "images optimised" in _build_line(r)


def test_drawio_light_dark_colours_are_downgraded_so_the_diagram_survives():
    # draw.io writes light-dark(#fff, var(--ge-dark-color, #121212)); cairosvg reads that as a
    # hex colour and dies. A book is a light-theme document, so the light value is the right one.
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" '
        b'style="background-color: light-dark(#ffffff, var(--ge-dark-color, #121212));">'
        b'<rect width="10" height="10" fill="light-dark(#3D4574, #ffffff)"/></svg>'
    )
    out = downgrade_modern_css(svg)
    assert b"light-dark" not in out and b"var(" not in out
    assert b"background-color: #ffffff" in out and b'fill="#3D4574"' in out


def test_a_plain_svg_is_left_untouched():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#ff0000"/></svg>'
    assert downgrade_modern_css(svg) == svg
