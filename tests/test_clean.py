from lxml import etree

from blog2epub.clean import clean_html, extract_image_urls, normalize_url
from blog2epub.images import pick_srcset_candidate

BASE = "https://example.com/blog/post/"


def _clean(html, **kw):
    kw.setdefault("image_resolver", lambda url: "../Images/x.png")
    xhtml, imgs = clean_html(html, BASE, **kw)
    etree.fromstring(f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{xhtml}</body></html>')  # well-formed
    return xhtml, imgs


def test_output_is_xhtml_and_strips_junk():
    html = ('<p onclick="x()" style="color:red" data-x="1">Hi<br>there</p><script>alert(1)</script>'
            '<!-- c --><o:p></o:p><font color="red">f</font><div style="x">&nbsp;</div><p></p>')
    xhtml, _ = _clean(html)
    assert xhtml.startswith('<div class="post-body">')
    assert "<br/>" in xhtml
    assert "script" not in xhtml and "onclick" not in xhtml and "style=" not in xhtml and "data-x" not in xhtml
    assert "o:p" not in xhtml and "<font" not in xhtml
    assert "<p/>" not in xhtml and "<p></p>" not in xhtml


def test_links_become_absolute_and_internal_links_rewritten():
    html = '<a href="../other/">rel</a> <a href="https://example.com/blog/other/#sec">abs</a> <a href="https://elsewhere.org/x">ext</a>'
    xhtml, _ = _clean(html, link_resolver=lambda u: "ch-0002.xhtml" if "other" in u else None)
    assert xhtml.count('href="ch-0002.xhtml"') == 2
    assert 'href="https://elsewhere.org/x"' in xhtml


def test_images_use_srcset_and_missing_images_become_text():
    html = ('<img src="/a.jpg" srcset="/a-300.jpg 300w, /a-768.jpg 768w, /a-2000.jpg 2000w" width="2000" alt="A">'
            '<img src="/gone.png" alt="Gone">'
            '<img src="/noalt.png">')
    seen = []

    def resolver(url):
        seen.append(url)
        return "../Images/a.jpg" if "a-768" in url else None

    xhtml, imgs = _clean(html, image_resolver=resolver, max_image_width=1000)
    assert seen[0] == "https://example.com/a-768.jpg"
    assert imgs == ["https://example.com/a-768.jpg"]
    assert 'src="../Images/a.jpg"' in xhtml and 'width=' not in xhtml
    assert "[image: Gone]" in xhtml
    assert xhtml.count("<img") == 1


def test_media_embeds_become_links():
    html = '<iframe src="https://www.youtube.com/embed/abc"></iframe><video><source src="/v.mp4"></video>'
    xhtml, _ = _clean(html)
    assert 'href="https://www.youtube.com/embed/abc"' in xhtml
    assert 'href="https://example.com/v.mp4"' in xhtml
    assert "iframe" not in xhtml and "<video" not in xhtml


def test_headings_demoted_only_when_h1_present():
    assert "<h2>T</h2>" in _clean("<h1>T</h1><h2>S</h2>")[0]
    assert "<h3>S</h3>" in _clean("<h1>T</h1><h2>S</h2>")[0]
    assert "<h2>S</h2>" in _clean("<h2>S</h2>")[0]
    assert "<h1>T</h1>" in _clean("<h1>T</h1>", demote_headings=False)[0]


def test_duplicate_ids_dropped():
    xhtml, _ = _clean('<p id="a">1</p><p id="a">2</p><p id="1bad">3</p>')
    assert xhtml.count('id="a"') == 1 and "1bad" not in xhtml


def test_pre_blocks_survive():
    xhtml, _ = _clean('<pre class="lang-go"><code>if x &lt; 1 {\n  y()\n}</code></pre>')
    assert "<pre class=\"lang-go\"><code>if x &lt; 1 {\n  y()\n}</code></pre>" in xhtml


def test_empty_input():
    assert clean_html("", BASE, image_resolver=lambda u: None)[0] == '<div class="post-body"></div>'


def test_extract_image_urls():
    html = '<img src="/a.jpg"><img src="/a.jpg"><img src="data:image/png;base64,xx">'
    assert extract_image_urls(html, BASE) == ["https://example.com/a.jpg"]


def test_pick_srcset_candidate():
    ss = "/s.jpg 300w, /m.jpg 768w, /l.jpg 1600w"
    assert pick_srcset_candidate("/o.jpg", ss, 1200) == "/m.jpg"
    assert pick_srcset_candidate("/o.jpg", ss, 100) == "/s.jpg"
    assert pick_srcset_candidate("/o.jpg", None, 100) == "/o.jpg"
    assert pick_srcset_candidate("/o.jpg", "/x.jpg 2x", 100) == "/o.jpg"


def test_normalize_url():
    assert normalize_url("https://www.Example.com/blog/a/?utm_source=x#frag") == normalize_url("http://example.com/blog/a")


def test_srcset_with_data_uri_placeholder_and_lazy_attrs():
    ss = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 934 481'%3E%3C/svg%3E 300w, /real-768.jpg 768w"
    assert pick_srcset_candidate("data:image/gif;base64,R0lGOD", ss, 1200) == "/real-768.jpg"
    only_placeholder = "data:image/svg+xml,%3Csvg xmlns='https://www.w3.org/2000/svg' viewBox='0 0 934 481'%3E%3C/svg%3E"
    assert pick_srcset_candidate("/fallback.jpg", only_placeholder, 1200) == "/fallback.jpg"
    assert pick_srcset_candidate(only_placeholder, only_placeholder + " 300w", 1200) is None
    html = '<img src="data:image/gif;base64,R0lGOD" data-src="/lazy.jpg" data-srcset="/lazy-300.jpg 300w, /lazy-900.jpg 900w" alt="l">'
    xhtml, imgs = _clean(html, max_image_width=800)
    assert imgs == ["https://example.com/lazy-300.jpg"]
    assert "data-src" not in xhtml
