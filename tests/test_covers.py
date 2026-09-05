from types import SimpleNamespace

from blog2epub.covers import resolve_cover
from tests.conftest import PNG_1x1
from tests.test_sources import FakeClient, FakeResponse


def _settings(tmp_path):
    return SimpleNamespace(
        config_path=tmp_path / "blogs.yaml", cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"
    )


def test_cover_local_path(tmp_path):
    (tmp_path / "covers").mkdir()
    (tmp_path / "covers" / "c.png").write_bytes(PNG_1x1)
    assert resolve_cover("covers/c.png", _settings(tmp_path)) == tmp_path / "covers" / "c.png"
    assert resolve_cover("covers/nope.png", _settings(tmp_path)) is None
    assert resolve_cover(None, _settings(tmp_path)) is None


def test_cover_url_is_downloaded_once(tmp_path):
    url = "https://cdn.example/cover.png"
    client = FakeClient(
        lambda u, p: FakeResponse(200, PNG_1x1, {"Content-Type": "image/png"}) if u == url else None
    )
    path = resolve_cover(url, _settings(tmp_path), client)
    assert path is not None and path.read_bytes() == PNG_1x1 and path.suffix == ".png"
    again = resolve_cover(url, _settings(tmp_path), client)
    assert again == path and client.requests_made == 1
    assert resolve_cover("https://cdn.example/missing.png", _settings(tmp_path), client) is None
