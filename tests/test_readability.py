from blog2epub.config import BookConfig
from blog2epub.epub import _wants_readability
from blog2epub.extract import readability_pass
from tests.conftest import make_post

BOILERPLATE = "<p>The post <a href='x'>Title</a> appeared first on <a href='y'>Site</a>.</p>"
ARTICLE = "".join(
    f"<p>Paragraph {i} with a reasonable amount of running text to score well in readability.</p>"
    for i in range(12)
)


def test_readability_pass_keeps_article_text():
    out = readability_pass(ARTICLE + BOILERPLATE, "https://example.com/p/")
    assert "Paragraph 3" in out and "Paragraph 11" in out


def test_readability_pass_unwraps_and_falls_back(monkeypatch):
    short = "<figure><img src='a.png' alt=''/></figure><p>Tiny.</p>"
    out = readability_pass(short, "https://example.com/p/")
    assert "readabilityBody" not in out and "<article" not in out and "<figure>" in out and "Tiny." in out
    assert readability_pass("", "https://example.com/p/") == ""

    class Gutted:
        def __init__(self, *a, **k): ...
        def summary(self, html_partial=True):
            return '<body id="readabilityBody"><article><p>Tiny.</p></article></body>'

    monkeypatch.setattr("blog2epub.extract.Document", Gutted)
    assert readability_pass(ARTICLE, "https://example.com/p/") == ARTICLE  # would drop >40% of the text


def test_wants_readability_modes():
    book = BookConfig(id="b", title="b", blogs=["x"])
    feed_post, wp_post = make_post("f", None, source="feed"), make_post("w", None, source="wordpress")
    assert _wants_readability(book, feed_post) and not _wants_readability(book, wp_post)
    book.readability = "always"
    assert _wants_readability(book, wp_post)
    book.readability = "never"
    assert not _wants_readability(book, feed_post)
