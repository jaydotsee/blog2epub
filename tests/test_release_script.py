"""scripts/clear_release_assets.sh, driven by a fake `gh` on PATH.

The release workflow clears an issue's assets before uploading, so re-running an issue replaces
its files. A brand-new issue has no release yet, and that path is the one that broke: `gh api`
writes its error body to STDOUT and skips `--jq` on failure, so the 404 blob arrived where the
release id was expected and the next request was built around it.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "clear_release_assets.sh"

# What `gh api` really does for a missing tag: the JSON body on stdout, and a non-zero exit.
NOT_FOUND = (
    '{"message":"Not Found",'
    '"documentation_url":"https://docs.github.com/rest/releases/releases'
    '#get-a-release-by-tag-name","status":"404"}'
)


def _fake_gh(tmp_path: Path, script_body: str) -> Path:
    """Put a fake `gh` on PATH that logs its arguments to calls.log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{tmp_path}/calls.log"\n{script_body}\n')
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _run(tmp_path: Path, bin_dir: Path, tag: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "owner/repo",
        "GH_TOKEN": "x",
    }
    return subprocess.run(["bash", str(SCRIPT), tag], capture_output=True, text=True, env=env, check=False)


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def test_a_tag_with_no_release_yet_is_not_an_error(tmp_path):
    """The first issue of a book has no release to clear. This is the case that failed."""
    bin_dir = _fake_gh(tmp_path, f"echo '{NOT_FOUND}'\nexit 1")
    result = _run(tmp_path, bin_dir, "tyk-20260906")

    assert result.returncode == 0, result.stderr
    assert "nothing to clear" in result.stdout
    # and crucially it stopped there rather than asking for the assets of a JSON blob
    assert len(_calls(tmp_path)) == 1
    assert not any("assets" in c for c in _calls(tmp_path))


def test_an_existing_release_has_every_asset_removed(tmp_path):
    body = """
case "$*" in
  *"releases/tags/"*) echo 4242 ;;
  *"releases/4242/assets"*) printf '11 tyk-20260906-2026.epub\\n12 tyk-20260906-2025.epub\\n' ;;
  *) : ;;
esac
"""
    bin_dir = _fake_gh(tmp_path, body)
    result = _run(tmp_path, bin_dir, "tyk-20260906")

    assert result.returncode == 0, result.stderr
    calls = _calls(tmp_path)
    assert any("releases/4242/assets" in c for c in calls)
    assert [c for c in calls if "-X DELETE" in c] == [
        "api -X DELETE repos/owner/repo/releases/assets/11",
        "api -X DELETE repos/owner/repo/releases/assets/12",
    ]


@pytest.mark.parametrize("output", ["", "null", NOT_FOUND, "not json at all"])
def test_only_a_numeric_id_is_believed(tmp_path, output):
    """Whatever gh prints when it cannot answer, none of it is a release id."""
    bin_dir = _fake_gh(tmp_path, f"echo '{output}'")
    result = _run(tmp_path, bin_dir, "tyk-20260906")

    assert result.returncode == 0, result.stderr
    assert "nothing to clear" in result.stdout
    assert not any("assets" in c for c in _calls(tmp_path))


def test_a_missing_tag_argument_is_refused(tmp_path):
    bin_dir = _fake_gh(tmp_path, ":")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_TOKEN": "x"}
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, check=False)
    assert result.returncode != 0
    assert "usage" in result.stderr
