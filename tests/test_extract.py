"""Metadata extraction: the dates and titles a page claims are not always usable."""

from blog2epub.extract import extract_article


def test_placeholder_epoch_date_is_ignored_for_a_later_real_one():
    # HubSpot writes 1970-01-01 for "unset" and puts the real date on a second Article node.
    page = """<html><head><title>t</title>
    <script type="application/ld+json">{"@type":"BlogPosting","datePublished":"1970-01-01T00:00:00.000Z"}</script>
    <script type="application/ld+json">{"@type":"BlogPosting","datePublished":"2025-10-14T01:30:21"}</script>
    </head><body><h1>A post</h1><article><p>%s</p></article></body></html>""" % ("Body text here. " * 40)
    assert extract_article(page, "https://example.com/p")["date"] == "2025-10-14T01:30:21"


def test_epoch_date_with_no_alternative_leaves_the_post_undated():
    page = """<html><head><title>t</title>
    <meta property="article:published_time" content="1970-01-01T00:00:00Z">
    </head><body><h1>A post</h1><article><p>%s</p></article></body></html>""" % ("Body text here. " * 40)
    assert extract_article(page, "https://example.com/p")["date"] is None


def test_site_name_suffix_is_dropped_when_the_h1_agrees():
    page = """<html><head><meta property="og:title" content="The Importance of Zero Trust | Ambassador">
    <title>The Importance of Zero Trust | Ambassador</title></head>
    <body><h1>The Importance of Zero Trust</h1><article><p>%s</p></article></body></html>""" % ("Body. " * 60)
    assert extract_article(page, "https://example.com/p")["title"] == "The Importance of Zero Trust"


def test_a_pipe_the_h1_also_carries_is_kept():
    # Only a suffix the page's own headline lacks is boilerplate; a real one stays.
    title = "Kafka | Pulsar: choosing a broker"
    page = f"""<html><head><meta property="og:title" content="{title}">
    <title>{title}</title></head>
    <body><h1>{title}</h1><article><p>{"Body. " * 60}</p></article></body></html>"""
    assert extract_article(page, "https://example.com/p")["title"] == title


def test_the_site_naming_itself_is_dropped_even_when_the_h1_differs():
    # SEO title and on-page headline can be different sentences; the trailing brand still goes.
    page = """<html><head><meta property="og:title" content="What Is API Governance? | Gravitee.io">
    <title>x</title></head><body><h1>A Complete Guide to API Governance</h1>
    <article><p>%s</p></article></body></html>""" % ("Body. " * 60)
    assert extract_article(page, "https://www.gravitee.io/blog/p")["title"] == "What Is API Governance?"


def test_another_brand_in_the_title_is_left_alone():
    # Migrated posts carry a former publisher's name. That is fact, not boilerplate.
    title = "3 Factors AWS Lambda is Not Ready for Prime Time | Ambassador"
    page = f"""<html><head><meta property="og:title" content="{title}"><title>x</title></head>
    <body><h1>Why AWS Lambda Is Not Production Ready</h1>
    <article><p>{"Body. " * 60}</p></article></body></html>"""
    assert extract_article(page, "https://www.gravitee.io/blog/p")["title"] == title


def test_a_subtitle_after_a_dash_survives():
    title = "Rate limiting - a practical guide"
    page = f"""<html><head><meta property="og:title" content="{title}"><title>x</title></head>
    <body><h1>{title}</h1><article><p>{"Body. " * 60}</p></article></body></html>"""
    assert extract_article(page, "https://www.gravitee.io/blog/p")["title"] == title
