"""Runs the official W3C epubcheck against a generated book when EPUBCHECK_JAR is set (CI does this)."""

import os
import shutil
import subprocess

import pytest

from blog2epub.epub import build_epub, select_entries
from tests.conftest import PNG_1x1, make_post

pytestmark = pytest.mark.skipif(
    not os.environ.get("EPUBCHECK_JAR") or not shutil.which("java"),
    reason="set EPUBCHECK_JAR (and have java) to run epubcheck",
)


def test_generated_epub_passes_epubcheck(tmp_path, blog, store):
    img = "https://example.com/img/one.png"
    store.put_image(img, PNG_1x1, "png", "image/png")
    posts = [
        make_post(
            "wp-1",
            "2023-05-01T10:00:00+00:00",
            html=f'<h1>Top</h1><h2>Intro</h2><p>one <img src="{img}" alt="pic"></p><pre><code>x &lt; y</code></pre>'
            '<table><tr><th>a</th><td>b</td></tr></table><iframe src="https://youtu.be/x"></iframe>',
        ),
        make_post(
            "wp-2",
            "2024-06-01T10:00:00+00:00",
            html='<p id="dup">see <a href="https://example.com/blog/post-1/#dup">first</a></p><p id="dup">x</p>'
            '<figure><img src="https://example.com/missing.png" alt="m"><figcaption>cap</figcaption></figure>',
        ),
    ]
    for p in posts:
        store.put_post(p)
    store.save()
    out = tmp_path / "check.epub"
    book = blog.as_book()
    build_epub(book, select_entries(book, {blog.id: (blog, store)}), out)
    proc = subprocess.run(
        ["java", "-jar", os.environ["EPUBCHECK_JAR"], str(out)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 errors / 0 warnings" in proc.stdout, proc.stdout
