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
    html = (
        '<p onclick="x()" style="color:red" data-x="1">Hi<br>there</p><script>alert(1)</script>'
        '<!-- c --><o:p></o:p><font color="red">f</font><div style="x">&nbsp;</div><p></p>'
    )
    xhtml, _ = _clean(html)
    assert xhtml.startswith('<div class="post-body">')
    assert "<br/>" in xhtml
    assert (
        "script" not in xhtml and "onclick" not in xhtml and "style=" not in xhtml and "data-x" not in xhtml
    )
    assert "o:p" not in xhtml and "<font" not in xhtml
    assert "<p/>" not in xhtml and "<p></p>" not in xhtml


def test_links_become_absolute_and_internal_links_rewritten():
    html = '<a href="../other/">rel</a> <a href="https://example.com/blog/other/#sec">abs</a> <a href="https://elsewhere.org/x">ext</a>'
    xhtml, _ = _clean(html, link_resolver=lambda u: "ch-0002.xhtml" if "other" in u else None)
    assert xhtml.count('href="ch-0002.xhtml"') == 2
    assert 'href="https://elsewhere.org/x"' in xhtml


def test_images_use_srcset_and_missing_images_become_text():
    html = (
        '<img src="/a.jpg" srcset="/a-300.jpg 300w, /a-768.jpg 768w, /a-2000.jpg 2000w" width="2000" alt="A">'
        '<img src="/gone.png" alt="Gone">'
        '<img src="/noalt.png">'
    )
    seen = []

    def resolver(url):
        seen.append(url)
        return "../Images/a.jpg" if "a-768" in url else None

    xhtml, imgs = _clean(html, image_resolver=resolver, max_image_width=1000)
    assert seen[0] == "https://example.com/a-768.jpg"
    assert imgs == ["https://example.com/a-768.jpg"]
    assert 'src="../Images/a.jpg"' in xhtml and "width=" not in xhtml
    assert "[image: Gone]" in xhtml
    assert xhtml.count("<img") == 1


def test_media_embeds_become_links():
    html = '<iframe src="https://www.youtube.com/embed/abc"></iframe><video><source src="/v.mp4"></video>'
    xhtml, _ = _clean(html)
    assert 'href="https://www.youtube.com/embed/abc"' in xhtml
    assert 'href="https://example.com/v.mp4"' in xhtml
    assert "iframe" not in xhtml and "<video" not in xhtml


def test_embed_inside_paragraph_stays_valid():
    xhtml, _ = _clean('<p>Watch: <iframe src="https://www.youtube.com/embed/abc"></iframe> now</p>')
    assert '<p>Watch: <span class="embed"><a href="https://www.youtube.com/embed/abc">' in xhtml
    assert "<p><p" not in xhtml


def test_inline_wrappers_around_blocks_are_unwrapped():
    xhtml, _ = _clean('<strong>Intro <p>para</p></strong><a href="/x"><div>block</div></a>')
    assert "<strong><p>" not in xhtml and "<strong>" not in xhtml
    assert "<a" not in xhtml and "<div>block</div>" in xhtml


def test_invalid_hrefs_dropped_and_spaces_encoded():
    xhtml, _ = _clean(
        '<a href="https://2022 State of Report">r</a><a href="/a b/c?x=1 2">s</a>'
        '<a href="mailto:a@b.c">m</a><a href="ftp://x/y">f</a><a href="weird:thing">w</a>'
    )
    assert 'href="https://2022' not in xhtml
    assert 'href="https://example.com/a%20b/c?x=1%202"' in xhtml
    assert 'href="mailto:a@b.c"' in xhtml and 'href="ftp://x/y"' in xhtml and "weird:thing" not in xhtml


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
    assert '<pre class="lang-go"><code>if x &lt; 1 {\n  y()\n}</code></pre>' in xhtml


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
    assert normalize_url("https://www.Example.com/blog/a/?utm_source=x#frag") == normalize_url(
        "http://example.com/blog/a"
    )


def test_srcset_with_data_uri_placeholder_and_lazy_attrs():
    ss = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 934 481'%3E%3C/svg%3E 300w, /real-768.jpg 768w"
    assert pick_srcset_candidate("data:image/gif;base64,R0lGOD", ss, 1200) == "/real-768.jpg"
    only_placeholder = (
        "data:image/svg+xml,%3Csvg xmlns='https://www.w3.org/2000/svg' viewBox='0 0 934 481'%3E%3C/svg%3E"
    )
    assert pick_srcset_candidate("/fallback.jpg", only_placeholder, 1200) == "/fallback.jpg"
    assert pick_srcset_candidate(only_placeholder, only_placeholder + " 300w", 1200) is None
    html = '<img src="data:image/gif;base64,R0lGOD" data-src="/lazy.jpg" data-srcset="/lazy-300.jpg 300w, /lazy-900.jpg 900w" alt="l">'
    xhtml, imgs = _clean(html, max_image_width=800)
    assert imgs == ["https://example.com/lazy-300.jpg"]
    assert "data-src" not in xhtml


def test_wordpress_lazy_placeholder_with_broken_protocol_relative_src():
    html = (
        '<p><img loading="lazy" alt="" class="size-medium" data-lazy-src="https://tyk.io/wp-content/uploads/2023/04/x-934x678.png" '
        'height="678" src="//www.w3.org/2000/svg\'%20viewBox=\'0%200%20934%20678\'%3E%3C/svg%3E" width="934" /></p>'
    )
    _, imgs = _clean(html)
    assert imgs == ["https://tyk.io/wp-content/uploads/2023/04/x-934x678.png"]
    html2 = '<img src="//www.w3.org/2000/svg\'%20viewBox=\'0%200%201%201\'%3E%3C/svg%3E" alt="broken only">'
    xhtml, imgs2 = _clean(html2)
    assert imgs2 == [] and "[image: broken only]" in xhtml


def test_unknown_and_custom_elements_are_unwrapped():
    xhtml, _ = _clean(
        "<p>a <envelope><b>bold</b></envelope> <my-widget>w</my-widget> <hgroup><h2>H</h2></hgroup></p>"
    )
    assert "envelope" not in xhtml and "my-widget" not in xhtml and "hgroup" not in xhtml
    assert "<b>bold</b>" in xhtml and "w" in xhtml and "<h2>H</h2>" in xhtml


def test_empty_and_whitespace_ids_dropped():
    xhtml, _ = _clean('<p id="">x</p><p id=" ">y</p><p id="ok">z</p>')
    assert xhtml.count("id=") == 1 and 'id="ok"' in xhtml


def test_invalid_punycode_hosts_dropped():
    xhtml, _ = _clean(
        '<a href="https://xn--jess%20muoz%20rodrguez-fcc0g2k/">bad</a>'
        '<a href="https://xn--bcher-kva.example/x">ok</a><a href="https://ex ample.com/">sp</a>'
    )
    assert xhtml.count("href=") == 1 and 'href="https://xn--bcher-kva.example/x"' in xhtml


def test_malformed_lists_are_repaired():
    """CMS exports nest lists directly in lists and leave loose content between items."""
    xhtml, _ = _clean(
        "<ul><li>one</li><ul><li>nested</li></ul></ul>"
        "<ul>loose text<li>two</li><p>para</p><strong>bold</strong></ul>"
        "<div><li>orphan</li></div>"
    )
    root = etree.fromstring(f"<body>{xhtml}</body>")
    for lst in root.iter("ul", "ol"):
        assert (lst.text or "").strip() == ""
        assert all(c.tag == "li" for c in lst), [c.tag for c in lst]
    for li in root.iter("li"):
        assert li.getparent().tag in ("ul", "ol")
    assert "nested" in xhtml and "loose text" in xhtml and "para" in xhtml and "orphan" in xhtml


def test_nested_links_are_unwrapped():
    """A link inside a link is invalid. Direct nesting is split by the parser; nesting through
    an element in between survives parsing and has to be undone."""
    xhtml, _ = _clean(
        '<a href="https://a.example/"><span><a href="https://b.example/">inner</a></span> rest</a>'
    )
    root = etree.fromstring(f"<body>{xhtml}</body>")
    assert not [a for a in root.iter("a") if any(x.tag == "a" for x in a.iterancestors())]
    assert "inner" in xhtml and "rest" in xhtml


def test_invalid_urls_are_rejected_or_encoded():
    xhtml, _ = _clean(
        '<a href="https://ex.example/blog/post]">bracket</a>'
        '<a href="http://managerhost:port/info">bad port</a>'
        '<a href="https://ok.example/a%20b?x=1#f">fine</a>'
    )
    assert "post]" not in xhtml and "post%5D" in xhtml  # encoded, link kept
    assert "managerhost" not in xhtml  # unusable, href dropped
    assert 'href="https://ok.example/a%20b?x=1#f"' in xhtml  # untouched, no double-encoding
