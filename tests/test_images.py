"""Loading the optional SVG rasteriser.

cairosvg is optional twice over: the `svg` extra installs the Python package, and the package
binds to a native cairo that pip does not install. A machine can therefore have the module and
not the library — the ordinary state of a Mac after `uv sync` without `brew install cairo` —
and that combination used to abort a whole build partway through, rather than degrading the
way a missing optional dependency is supposed to.
"""

from __future__ import annotations

import builtins

import pytest

from blog2epub import images

# The first line of what cairocffi's dlopen actually raises; the real one runs a dozen more.
DLOPEN_ERROR = 'no library called "cairo-2" was found\nno library called "cairo" was found'


@pytest.fixture(autouse=True)
def _fresh_import_cache():
    """The loader imports once per process, so each test needs a clean slate."""
    images._load_cairosvg.cache_clear()
    yield
    images._load_cairosvg.cache_clear()


def _import_raises(monkeypatch, exc: Exception) -> None:
    real = builtins.__import__

    def fake(name, *args, **kwargs):
        if name == "cairosvg":
            raise exc
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake)


def test_a_missing_cairo_library_does_not_abort_the_build(monkeypatch, caplog):
    """The macOS case: cairosvg imported, its native library did not."""
    _import_raises(monkeypatch, OSError(DLOPEN_ERROR))

    with caplog.at_level("WARNING"):
        assert images.rasterize_svg_bytes(b"<svg/>", 200) is None

    assert images.cairosvg_available() is False
    problem = images.cairosvg_problem()
    assert "cairo library" in problem
    assert "brew install cairo" in problem
    # the dlopen message is quoted, but only its first line
    assert 'no library called "cairo-2"' in problem
    assert "\n" not in problem
    assert any("SVG images will not be rasterised" in r.message for r in caplog.records)


def test_a_missing_package_reports_the_extra_instead(monkeypatch):
    """The other absence: no `svg` extra at all, where the install hint is a different one."""
    _import_raises(monkeypatch, ImportError("No module named 'cairosvg'"))

    assert images.rasterize_svg_bytes(b"<svg/>", 200) is None
    assert images.cairosvg_available() is False
    assert images.cairosvg_problem() == "cairosvg is not installed (pip install 'blog2epub[svg]')"


def test_rasterize_svg_reports_failure_rather_than_raising(monkeypatch, tmp_path):
    """The call site that crashed: epub.prepare asks for a PNG and expects a bool back."""
    _import_raises(monkeypatch, OSError(DLOPEN_ERROR))
    svg = tmp_path / "diagram.svg"
    svg.write_bytes(b"<svg/>")

    assert images.rasterize_svg(svg, tmp_path / "diagram.png", 600) is False
    assert not (tmp_path / "diagram.png").exists()


def test_a_working_cairosvg_reports_no_problem():
    pytest.importorskip("cairosvg")

    assert images.cairosvg_available() is True
    assert images.cairosvg_problem() == ""
