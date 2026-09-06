<p align="center">
  <img src="docs/social-preview.png" alt="blog2epub: navigable EPUB books and monthly digests from the blogs you read" width="100%">
</p>

<h1 align="center">blog2epub</h1>

<p align="center">
  Point it at the blogs you read. Get navigable EPUB books and monthly digests for your e-reader, kept current by a weekly workflow.
</p>

<p align="center">
  <a href="https://github.com/jaydotsee/blog2epub/actions/workflows/ci.yml"><img src="https://github.com/jaydotsee/blog2epub/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/jaydotsee/blog2epub/actions/workflows/monitor.yml"><img src="https://github.com/jaydotsee/blog2epub/actions/workflows/monitor.yml/badge.svg" alt="Monitor"></a>
  <a href="https://github.com/jaydotsee/blog2epub/releases"><img src="https://img.shields.io/github/v/release/jaydotsee/blog2epub?include_prereleases&label=release" alt="Latest release"></a>
  <img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue" alt="Python 3.10 to 3.13">
  <img src="https://img.shields.io/badge/EPUB%203-epubcheck%20clean-2ea44f" alt="EPUB 3, epubcheck clean">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="MIT license"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#configuration">Configuration</a> ·
  <a href="#the-api-management-digest">The digest</a> ·
  <a href="#keeping-books-current-with-github-actions">Automation</a> ·
  <a href="https://github.com/jaydotsee/blog2epub/releases">Download books</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

---

**blog2epub** monitors blogs, caches every post, and writes EPUB 3 files with a cover, a title
page, a nested table of contents with excerpts, readability-cleaned articles with their images,
and cross-links that stay inside the book. A book can be one blog's complete archive or a
magazine-style digest that combines several blogs over a date range. Every book it produces passes
the W3C [epubcheck](https://github.com/w3c/epubcheck) with zero errors and warnings.

It ships configured with six books: five complete archives — [Tyk](https://tyk.io/blog)
(627 posts), [Kong](https://konghq.com/blog) (900 posts),
[Apigee](https://cloud.google.com/blog/products/apigee) (244 posts),
[Axway](https://blog.axway.com) (1,968 posts, back to 2011) and
[Gravitee](https://www.gravitee.io/blog) (656 posts) — and the
**API Management Digest**, a monthly issue drawn from eleven API-management blogs. All are
published on the [releases page](https://github.com/jaydotsee/blog2epub/releases).

The idea comes from Facundo Olano's [Turn your blog into a book](https://jorge.olano.dev/blog/turn-your-blog-into-an-ebook/):
an EPUB is zipped XHTML plus a manifest. That post builds a book from a blog's *own source files*.
blog2epub does the same for blogs you **don't** own, by fetching posts through whatever the site
exposes.

## What it looks like on the reader

<p align="center">
  <img src="docs/screenshots/contents.png" width="24%" alt="Table of contents: years, months, posts">
  <img src="docs/screenshots/part.png" width="24%" alt="A year page listing its months and posts with excerpts">
  <img src="docs/screenshots/month.png" width="24%" alt="A month page with dates, authors and excerpts">
  <img src="docs/screenshots/chapter.png" width="24%" alt="A chapter with byline, source link and images">
</p>
<p align="center"><sub>Contents · year page · month page · chapter. Rendered at a 6-inch e-reader viewport from the generated Tyk book.</sub></p>

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Commands](#commands)
- [Configuration](#configuration)
- [Site rules](#site-rules)
- [Recipes](#recipes)
- [The API Management Digest](#the-api-management-digest)
- [Magazine covers](#magazine-covers)
- [Keeping books current with GitHub Actions](#keeping-books-current-with-github-actions)
- [Reading the books](#reading-the-books)
- [Project layout](#project-layout)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [Contributing and license](#contributing-and-license)

## Features

- **Three ways in, picked automatically.** WordPress REST API (full HTML, dates, authors,
  categories, featured images), RSS/Atom feeds (with a page fetch when the feed is truncated),
  and `sitemap.xml` crawling. The richest one that answers wins.
- **Incremental monitoring.** Each sync lists what the source knows, fetches only new and
  modified posts plus missing images, and keeps everything in a per-blog cache. Building is
  offline. Requests retry with backoff, image downloads get a second attempt, and one unreachable
  blog never stops the others.
- **Readability.** Scraped pages go through readability to isolate the article. An optional
  build-time pass cleans feed and API bodies too, with a safety net that never drops a post's
  content.
- **Site rules, Calibre-recipe style.** Per blog, `keep` names the article container and
  `remove` lists the clutter to drop, as CSS selectors. `extra_css` tunes the look.
- **E-reader-sized images.** Every build downscales images to `max_image_width` and re-encodes
  them, flattening heavy transparent PNGs onto white. Blogs serve images sized for desktop
  retina screens; without this step a complete archive is several times larger than it needs to
  be (Kong: 705 MB as served, 236 MB built).
- **Clean, valid XHTML.** Scripts, styles, forms, tracking attributes, Word pastes, lazy-load
  placeholders and custom elements are handled. Every generated book passes epubcheck with zero
  errors and warnings.
- **Real navigation.** EPUB 3 `nav.xhtml` with parts (per year, month or blog), optional month
  sub-sections inside each year, and chapters; a `toc.ncx` for older readers; landmarks; and
  part pages that list each post with its date, author and excerpt.
- **Magazine digests.** Combine any number of blogs into one book, newest first, with a lead
  image per article and the blog name in every byline. Rolling windows (`since: 7d`, `1m`, `1y`)
  give a fresh issue on every build.
- **Volumes that fit a reader.** A book is cut into volumes that each stay under 200 MB (Send
  to Kindle's limit), or by year or month if you prefer; each volume is `<book>-<issue>.<n>.epub`
  with its own cover and navigation.
- **Covers with live cover lines.** HTML templates rendered once per volume, with that volume's
  newest post titles, post count, year span and issue number. Or point `cover:` at your own image.
- **Scriptable and automated.** A plain CLI, a JSON report, a weekly GitHub Actions monitor
  publishing to a rolling release, and an on-demand workflow for dated releases.

## How it works

```
blogs.yaml
  blogs: sources          books: outputs
      │                       │
      ▼                       ▼
  ┌────────┐   cache/<blog>/   ┌────────┐
  │  sync  │ ───────────────▶ │ build  │ ───▶ output/<book>.epub
  └────────┘   index.json     └────────┘        (or <book>-<year>.epub)
      │        posts/*.json        │
      │        images/*            └─ select (since/until/max_posts) → sort → group into parts
      │                               → readability pass → clean to XHTML → resolve images/links
      └─ detect source:               → render cover, title, nav, ncx, parts, chapters → zip
         1. WordPress REST API
         2. RSS / Atom feed (+ page fetch + readability when truncated)
         3. sitemap.xml (+ readability, meta and JSON-LD for dates and authors)
```

**Sources.** For every blog, `sync` tries the WordPress REST API first (`/wp-json/wp/v2/posts`),
then the feed advertised in the page or at the usual paths, then the sitemap from `robots.txt`.
The choice is remembered in the cache. WordPress is by far the best source: tyk.io's 627 posts
arrive in seven requests with rendered HTML and full metadata. Feeds usually carry only the latest
ten or so posts, so a feed-only blog fills its cache over time as the monitor keeps running.
Sitemaps list whole archives but need readability to extract each page.

**Cache.** `cache/<blog>/index.json` records every known post (URL, title, dates) and every image
(or the reason it failed). Posts live one per JSON file, images by URL hash. A post is re-fetched
only when the source reports a newer `modified` stamp. Posts that disappear from the source stay
cached unless you pass `--prune`. Transient image failures are retried after three days;
permanent ones (404, not an image, too large) only with `--full`.

**Cleaning.** Post HTML becomes a well-formed XHTML fragment: iframes and videos turn into links,
the best `srcset` candidate not wider than `max_image_width` is chosen, lazy-load `data-src`
attributes win over placeholders, inline wrappers around block content are unwrapped, unknown and
custom elements are unwrapped, invalid hrefs and ids are dropped, headings are demoted so the post
title is the only `h1`, and links to other posts in the same book are rewritten to chapter files.

**Books.** A book is one or more blogs plus a selection and a layout. Every blog builds its own
book unless it sets `standalone: false`; the `books` list adds combined ones. Chapters open with
the post's featured image when the body does not already contain it, and each part page lists its
posts with date, author, blog and excerpt.

## Installation

Requires Python 3.10 or newer.

```bash
git clone https://github.com/jaydotsee/blog2epub.git
cd blog2epub
make setup            # creates .venv and installs blog2epub with the dev tools
```

or, without the Makefile:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Image downscaling is part of a plain install. Java is only needed for `make epubcheck` and the
optional validator test. Cover rendering needs the `covers` extra (Playwright) and a Chromium.
SVG rasterisation needs the `svg` extra (cairosvg, which needs the cairo library: `libcairo2` on
Debian and Ubuntu, `cairo` on Homebrew); `make setup` installs it.

## Quick start

```bash
.venv/bin/blog2epub list                    # what is configured
.venv/bin/blog2epub run tyk                 # sync + build → output/tyk.epub
.venv/bin/blog2epub run api-management      # sync its eleven blogs, build the digest
.venv/bin/blog2epub status                  # cache and output state
```

### Adding a blog

Run the probe: it reports every source that answers and how many posts each lists, the URL shape,
candidate extraction rules, a real extraction of five posts with a check for other posts leaking
in, the site's brand colours, and a draft config entry.

```bash
.venv/bin/python scripts/probe_blog.py https://example.com/blog
```

`AGENTS.md` explains what to do with the answers and the traps to avoid; the `/add-blog` skill
walks the whole path from URL to published release. For a quick look at just the source:

```
$ .venv/bin/blog2epub detect https://konghq.com/blog
source: feed (https://konghq.com/feed/)
posts:  10
  2026-09-03T15:02:11+00:00  Kong Gateway Now Supports FIPS 140-3  https://konghq.com/blog/product-releases/kong-gateway-fips-140-3

suggested blogs.yaml entry:

  - id: konghq
    title: "..."
    url: https://konghq.com/blog
    source: feed
    include:
      - "^https://konghq\\.com/blog/"
```

Paste the entry into `blogs.yaml`, set a title, and run `blog2epub run konghq`.

## Commands

Every command accepts `-c FILE` (default `./blogs.yaml`) and `-v` / `-vv` for progress output.

| Command | What it does |
| --- | --- |
| `list` | Show configured blogs and books, with cached post counts. |
| `detect URL [--source S] [--sample N]` | Probe a URL, report which source works, list posts, print a config entry. |
| `sync [ids] [--full] [--prune]` | Fetch new and changed posts and their images into `cache/`. Ids can be blogs or books (the book's blogs are synced). `--full` re-fetches everything and retries failed images. |
| `build [ids]` | Write EPUB(s) from the cache. Works offline (a cover URL is fetched once). |
| `run [ids] [--force] [--report FILE] [--full] [--prune]` | `sync`, then `build` every book whose blogs changed or whose output is missing. `--report` writes a JSON summary. |
| `status` | Per blog: source, last sync, post and image counts. Per book: output files. |

Exit codes: `0` success, `1` configuration error, `2` a blog or book failed (the others still run).

The JSON report written by `run --report` looks like this and drives the GitHub Action:

```json
{
  "changed": true,
  "blogs": [{"id": "tyk", "source": "wordpress (...)", "discovered": 627, "new": 1, "updated": 0, "cached": 627, "errors": []}],
  "books": [{"id": "tyk", "built": [{"path": "output/tyk.epub", "posts": 627, "images": 956, "bytes": 52105534}]}]
}
```

## Configuration

`blogs.yaml` has three sections. Keys under `defaults` apply to every blog and book unless the
entry overrides them.

### `defaults`

| Key | Default | Meaning |
| --- | --- | --- |
| `output_dir` | `output` | Where `.epub` files are written (relative to `blogs.yaml`). |
| `cache_dir` | `cache` | Per-blog download cache. |
| `user_agent` | `blog2epub/0.1` | Sent with every request. Put a contact URL in it. |
| `request_delay` | `0.5` | Seconds between requests. Be polite. |
| `timeout` | `30` | Request timeout in seconds. |

Any blog or book key may also appear under `defaults`.

### `blogs` (sources)

| Key | Default | Meaning |
| --- | --- | --- |
| `id` | required | Short name: `cache/<id>/`, `output/<id>.epub`. Letters, digits, `.`, `_`, `-`. |
| `url` | required | Blog root URL. |
| `title` | `id` | Shown in bylines, part pages and the book title. |
| `source` | `auto` | `auto`, `wordpress`, `feed` or `sitemap`. |
| `include` | `[]` | Regexes; only post URLs matching one of them are kept. |
| `exclude` | `[]` | Regexes; matching URLs are dropped. |
| `since`, `until` | – | A date (`YYYY-MM-DD`) or a rolling window (`7d`, `2w`, `3m`, `1y`). Limits what is fetched and what the standalone book contains. |
| `standalone` | `true` | Build this blog's own book. Set `false` for blogs that only feed combined books. |
| `images` | `true` | Download images during sync. |
| `max_image_width` | `1200` | Choose the largest `srcset` candidate not wider than this. |
| `max_image_bytes` | `8000000` | Skip larger images. |
| `fetch_full` | `true` | Feed source: fetch the page when the feed body is missing or short. |
| `min_chars` | `150` | Skip posts whose body is shorter than this and name them in the log. Catches soft 404s, where a site answers 200 with an error page. Set `0` for a blog of genuinely tiny posts. |
| `keep` | `[]` | CSS selectors for the article container(s). When one matches, only that content is kept. See [Site rules](#site-rules). |
| `remove` | `[]` | CSS selectors for clutter to drop from every post (share bars, newsletter boxes, related posts). |
| `extra_css` | – | CSS appended to every book that contains this blog. Chapters carry `class="blog-<id>"` for scoping. |
| `request_delay` | inherits | Per-blog override. |
| `wordpress` | `{}` | `api` (base URL), `post_type`, `categories` (ids), `params` (extra query params such as `author`). |
| `feed` | `{}` | `url` of the feed when discovery fails. |
| `sitemap` | `{}` | `url` of the sitemap when discovery fails; `include` (regexes) picks which partitions of a sitemap index to walk; `max` raises the 200-file cap. Large sites partition by date and language. |
| book keys | see below | `author`, `description`, `publisher`, `language`, `max_posts`, `cover`, `group_by`, `order`, `split`, `demote_headings`, `readability`, `excerpts`, `featured_images` configure the blog's standalone book. |

### `books` (outputs)

| Key | Default | Meaning |
| --- | --- | --- |
| `id` | required | Output name: `output/<id>.epub`. Must not clash with a blog id. |
| `blogs` | required | List of blog ids to combine. |
| `title` | `id` | Book title. |
| `author`, `description`, `publisher`, `language` | – / `en` | EPUB metadata; the description also appears on the title page and generated cover. |
| `since`, `until` | – | Only posts published in this range. A date, or a rolling window like `7d`, `2w`, `3m`, `1y` measured from the time of the build. |
| `max_posts` | – | Keep the N most recent posts across all the book's blogs. |
| `cover` | – | An HTML template (rendered once per volume, see [Magazine covers](#magazine-covers)), a JPG/PNG path relative to `blogs.yaml`, or a URL (downloaded once). Otherwise a cover is generated. |
| `images` | `true` | Embed images. `false` gives a text-only edition. |
| `group_by` | `year` | Part level of the TOC: `year`, `year-month` (years with month sub-sections), `month`, `blog` or `none`. |
| `order` | `asc` | `asc` reads oldest to newest like a book; `desc` is magazine order. |
| `split` | `size` | How the book is cut into volumes: `size` packs posts in reading order into volumes under `max_book_bytes`; `year` and `month` cut on the posts' dates; `none` is one file whatever the size. |
| `max_book_bytes` | `200MB` | The size each volume stays under with `split: size`. Bytes, or `150MB`, `1.5GB`. |
| `demote_headings` | `true` | Shift headings inside posts down so the post title is the only `h1`. |
| `readability` | `auto` | Build-time readability pass: `auto` (feed bodies only), `always`, `never`. |
| `excerpts` | `true` | Excerpts on the part pages. |
| `featured_images` | `true` | Lead each chapter with the post's featured image. |
| `extra_css` | – | CSS appended to this book's stylesheet. |
| `optimize_images` | `true` | Downscale images to `max_image_width` and re-encode them at build time. A standard step: blogs serve desktop-sized images, and Kong's archive is 705 MB as served against 236 MB optimised. Turn it off only to keep originals. |
| `image_quality` | `82` | JPEG quality used when re-encoding. |
| `svg_images` | `raster` | What to do with SVG images: `raster` converts them to PNG (needs the `svg` extra, cairosvg), `keep` embeds them as is, `drop` replaces them with their alt text. Kindle's converter falls back to a fixed layout when it meets SVG, so `raster` is the default. |

### About `readability`

Pages that had to be scraped (feed links without a full body, sitemap URLs) always go through
[readability](https://github.com/buriy/python-readability) when they are fetched. The
`readability` option controls a second pass at build time:

- `auto` runs it on bodies that came straight out of a feed, which often carry "this post
  appeared first on" footers and sharing widgets.
- `always` runs it on everything, including WordPress API content.
- `never` skips it.

The pass keeps the original whenever readability would drop more than 40% of the text, so short
posts and image-only figures are never lost.

### Full example

```yaml
defaults:
  output_dir: output
  cache_dir: cache
  user_agent: "blog2epub/0.1 (+https://github.com/jaydotsee/blog2epub)"
  request_delay: 0.5
  group_by: year
  order: asc
  readability: auto

blogs:
  - id: tyk
    title: "Tyk Blog"
    url: https://tyk.io/blog
    author: "Tyk Technologies"
    description: "Every post from the Tyk API management blog, collected as an ebook."
    include: ["^https://tyk\\.io/blog/"]
    order: desc
    group_by: year-month
    cover: covers/tyk.jpg

  - id: kong
    title: "Kong Blog"
    url: https://konghq.com/blog
    standalone: false               # only used inside combined books
    since: 3m
    remove: ["[itemtype='https://schema.org/BreadcrumbList']", "span.agent"]

books:
  - id: api-management
    title: "API Management Digest"
    blogs: [tyk, kong]
    since: 1m
    group_by: blog
    order: desc
    cover: covers/api-management.jpg
```

## Site rules

Calibre news recipes get most of their value from two lists: the tags that hold the article and
the tags to throw away. blog2epub has the same two knobs, as CSS selectors, on every blog:

```yaml
  - id: example
    url: https://example.org/blog
    keep:
      - "article.post"             # the article container; only this survives when it matches
    remove:
      - ".share-bar"
      - ".newsletter-signup"
      - "aside.related"
      - "div[class*='cookie']"
    extra_css: |
      .blog-example blockquote { font-style: italic; }
```

- `keep` is applied to the full page before readability when a page has to be scraped (feed
  links without a body, sitemap URLs), so it fixes the cases where readability picks the wrong
  block. It is applied again to every cached body at build time, so it also trims WordPress API
  content. When nothing matches, the whole body is kept.
- `remove` runs after `keep`, at fetch and at build, and also stops the removed images from being
  downloaded.
- Selectors are validated when the config loads. Any selector `lxml.cssselect` understands works:
  classes, ids, attribute matches, descendant and child combinators.
- `extra_css` on a blog is appended to every book that contains it; use the `.blog-<id>` class
  to scope it. `extra_css` on a book applies to that book only.

Find selectors by opening a post in the browser's inspector, or run `detect` and look at one of
the listed URLs.

## Recipes

**Newest first, years with month sub-sections.** This is how the Tyk book is configured:
the table of contents reads 2026 → September 2026 → posts, all newest first. Each year gets a part
page listing its months, and each month a short page listing its posts with excerpts, placed right
before them in reading order.

```yaml
  - id: tyk
    url: https://tyk.io/blog
    order: desc
    group_by: year-month
```

**A blog's complete archive, one file per year.** By default a big archive is cut into volumes
by size (see [Volumes](#volumes)); to cut on the calendar instead:

```yaml
  - id: tyk
    url: https://tyk.io/blog
    split: year               # output/tyk-20260905.1.epub is 2015, .2 is 2016, ...
```

**A weekly issue.** Newest first, grouped by blog, always the last seven days at build time:

```yaml
books:
  - id: apim-weekly
    title: "API Management Weekly"
    blogs: [tyk, kong, gravitee, nordicapis, postman]
    since: 7d
    group_by: blog
    order: desc
```

Rolling windows are measured when the build runs, so the weekly GitHub Action produces a fresh
issue every Monday. `1y` on a blog limits what gets fetched as well as what the book contains.

**Text only, for a small file.** `images: false` on the book keeps the download cache intact but
embeds nothing:

```yaml
books:
  - id: tyk-text
    blogs: [tyk]
    images: false
```

**Only some authors or categories of a WordPress blog.** Any query parameter of the posts endpoint
can be passed; APIDAYS' articles on API Scene are selected this way in the shipped config:

```yaml
  - id: apidays
    url: https://www.apiscene.io/author/apidays-conferences/
    wordpress: { api: https://www.apiscene.io/wp-json/wp/v2, params: { author: 3 } }
  - id: apiscene
    url: https://apiscene.io
    wordpress: { params: { author_exclude: 3 } }
```

**A blog whose posts are not under the URL you were given.** `cloud.google.com/blog/products/apigee`
is a tag page; the posts live under other product sections. Match where they really are:

```yaml
  - id: apigee
    url: https://cloud.google.com/blog/products/apigee
    source: sitemap
    sitemap:
      url: https://cloud.google.com/transform/sitemapsummary/cloudblog
      include: ["/cloudblog/en/"]   # the index is partitioned by fortnight and language
      max: 400
    include: ["^https://cloud\\.google\\.com/blog/(products/api-management/|[^ ]*apigee)"]
```

**A blog whose feed is not discoverable:**

```yaml
  - id: example
    url: https://example.org/writing
    source: feed
    feed: { url: https://example.org/writing/index.xml }
```

## The complete-archive books

Five blogs are configured as complete archives, newest first, with year → month navigation and
their own covers:

| Book | Source | Posts | Notes |
| --- | --- | --- | --- |
| `tyk` | WordPress REST API | 627 | The API delivers every post with full metadata in seven requests. |
| `kong` | `sitemaps/blogs.xml` | 900 | The feed carries only the latest ten, so the sitemap is used instead. |
| `apigee` | Google's `cloudblog` sitemap | 244 | The URL given is a tag page, not a section; posts live under other product paths. |
| `axway` | WordPress REST API | 1,968 | The longest archive here, back to 2011, across API management, MFT and B2B. |
| `gravitee` | HubSpot sitemap | 656 | Gravitee publishes through HubSpot, so the archive is in that sitemap, not the site's own. |

Kong's pages prerender twenty related-post cards into every article, which readability alone
mistakes for part of the story, so the entry uses a `keep` selector for the article body plus
`remove` selectors for the surrounding furniture. It is the worked example for
[Site rules](#site-rules) on a modern JavaScript-rendered site. Apigee is the worked example of a
blog URL that is a tag page: nothing lives under `/blog/products/apigee`, so the entry matches
where the posts really are and walks only the English partitions of Google's 1058-file sitemap
index. Gravitee is the worked example of a blog whose archive lives on the platform it publishes
through: its own sitemap knows nothing of the posts, HubSpot's has all of them, and the two
disagree about trailing slashes, which `get_text_tolerant` absorbs.

Axway is the largest book here: 1,968 posts and 4,799 images come to 291 MB, which no single
file should be. It is the reason books are cut into volumes.

## Volumes

A book is written as one or more **volumes**, `output/<book>-<issue>.<n>.epub`, where the issue
is the build date as `YYYYMMDD` and `n` counts from 1. The `split` key says where the cuts go:

- `size` (the default) packs posts in reading order into volumes that each stay under
  `max_book_bytes`, `200MB` unless you say otherwise, because that is what Send to Kindle
  accepts. The planner weighs each post's text as the zip will store it and its images at their
  file size, counting an image shared by several posts once per volume, so the cut lands where
  the budget says and the actual file comes in under it. Most books fit in one volume and are
  simply `<book>-<issue>.1.epub`.
- `year` and `month` cut on the posts' dates, one volume per calendar period, however big.
- `none` writes one file whatever the size.

Each volume is a complete book of its own: its own cover, title page (`Issue 20260905.2 ·
Volume 2 of 3`), contents and navigation, and a title such as *Axway Blog, Vol. 2* or *Tyk Blog
2024*. A link to a post that landed in another volume goes back to the post's web page rather
than dangling. Rebuilding a book removes its files from earlier issues; `blog2epub build
--issue 20260905` pins the issue when a release is built on a later day.

```bash
.venv/bin/blog2epub run kong     # sync + build → output/kong.epub
```

## The API Management Digest

`blogs.yaml` ships a second book, `api-management`: a monthly digest of the last 30 days of posts
from API Changelog, API Evangelist, API Scene, APIDAYS (which publishes on API Scene), Axway,
Bruno Pedro, Gravitee, Kong, Nordic APIs, Postman and Tyk. It uses a rolling `since: 1m` window
measured at build time, one part per blog, newest first, and its own cover. The digest-only blogs
carry `since: 3m` so their first sync stays small; the cache accumulates from then on.

```bash
.venv/bin/blog2epub run api-management     # sync its blogs, build output/api-management.epub
```

Because the window rolls, the weekly workflow always produces a fresh issue; the release workflow
(below) publishes one as a dated release when you want to keep it.

## Magazine covers

<p align="center">
  <img src="covers/tyk.jpg" width="19%" alt="Tyk Blog cover">
  <img src="covers/kong.jpg" width="19%" alt="Kong Blog cover">
  <img src="covers/apigee.jpg" width="19%" alt="Apigee Blog cover">
  <img src="covers/axway.jpg" width="19%" alt="Axway Blog cover">
  <img src="covers/gravitee.jpg" width="19%" alt="Gravitee Blog cover">
</p>

Every book has a cover rendered from the HTML template next to it by `scripts/render_cover.py`,
each in its blog's own brand palette: Tyk's purple, Kong's acid lime on near-black, Google's four
colours for Apigee, Axway's crimson on warm off-white, Gravitee's flame on near-black, and teal
and amber for the digest. The Tyk cover uses a masthead, three
kicker-plus-title cover lines taken from the newest cached posts, a hexagon badge with the post
count and year span, and a topic strip. The digest cover uses the month as its headline, the lead
post as the main cover line, four more posts with their blog names as kickers, a post-count stamp
and the list of sources. Re-render them after a sync to refresh the cover lines:

```bash
make cover        # installs the `covers` extra (Playwright) and renders every cover
```

Those JPGs are previews. The real covers are rendered by the build itself: when `cover:` names an
HTML template, every volume gets the template filled with **its own** post count, year span,
cover lines and issue number (`20260905.2`), plus `$volume_label` (*Vol. 2 of 3*, empty for a
single volume), so a three-volume archive has three different covers and the title page inside
each repeats the same issue number. Without Playwright the build uses the image beside the
template and says so. Copy a template to make a cover for another blog or book; the placeholders
(`$count`, `$first_year`, `$last_year`, `$issue`, `$issue_number`, `$volume`, `$volumes`,
`$volume_label`, `$month`, `$kicker1`, `$title1`, ...) work for any id. Fonts are bundled under
`covers/fonts/` (SIL Open Font License), so rendering is identical everywhere and needs no
network.

## Keeping books current with GitHub Actions

`.github/workflows/monitor.yml` runs every Monday at 06:00 UTC and on demand:

1. restores `cache/` from the previous run with `actions/cache`, so only new posts are fetched;
2. installs Chromium so each volume's cover can be rendered during the build;
3. runs `blog2epub run --report report.json`, which rebuilds every book whose blogs changed;
4. uploads all EPUBs as a workflow artifact (kept 30 days);
5. when something changed, clears and refreshes the rolling **`latest`** GitHub release, so the
   newest volumes are always at `https://github.com/jaydotsee/blog2epub/releases/tag/latest`;
6. writes a summary to the job page.

"Run workflow" accepts two switches: `force` rebuilds every book, `full` ignores the cache and
re-fetches everything. Nothing generated is committed; `cache/` and `output/` are git-ignored.

`.github/workflows/release.yml` publishes one book as a **dated release**: the issue. Three ways
to run it, all producing the tag `<book>-<YYYYMMDD>` with the volumes attached as
`<book>-<YYYYMMDD>.<n>.epub` and a table of them in the release notes:

```bash
git tag -a tyk-20260905 -m "Tyk Blog, issue 20260905" && git push origin tyk-20260905
git push origin main:release/tyk-20260905          # for hosts that block tag pushes
# or: Actions tab → "Release a book" → Run workflow → book id (the issue is today, UTC)
```

Re-running an issue replaces its files: the workflow clears the release's assets after a
successful build and before uploading, so a book that changed shape never carries both.

To run somewhere else, any scheduler that can call `blog2epub run` works: the cache directory is
the only state.

## Reading the books

- **Kobo, PocketBook, Tolino, Boox, Apple Books, Calibre:** copy the `.epub` over as is.
- **Kindle:** Send to Kindle accepts EPUB up to 200 MB via the web and app, 25 MB via email;
  the default `split: size` keeps every volume under the first limit.
  Amazon's converter treats a book as fixed layout ("original layout preserved, similar to PDF")
  when it finds content it cannot reflow, SVG images in particular. blog2epub therefore rasterises
  SVG images and the generated cover to PNG by default (`svg_images: raster`, which needs the
  `svg` extra). If a book still arrives as fixed layout, `svg_images: drop` removes the SVGs
  entirely, and converting with Calibre (`ebook-convert book.epub book.azw3`) bypasses Amazon's
  converter altogether.
- The table of contents shows parts and chapters; part pages give the date, author and an excerpt
  for every post; every chapter links back to the original URL.

## Project layout

```
AGENTS.md                      how to work on this repo, and the recipe pattern for a new blog
.claude/skills/add-blog/       the /add-blog skill: probe, configure, build, release
blogs.yaml                     configuration (blogs = sources, books = outputs)
covers/                        cover images, their HTML templates and bundled fonts
docs/                          README assets (screenshots, social preview)
scripts/probe_blog.py          works out a new blog's recipe: source, URL shape, rules, colours
scripts/render_cover.py        renders a cover template to JPG with Playwright
scripts/render_docs.py         renders the README screenshots and social preview
src/blog2epub/
  cli.py                       list, detect, sync, build, run, status
  config.py                    YAML → BlogConfig / BookConfig / Settings, validation
  http.py                      polite HTTP client: retries, backoff, delay between requests
  sources/
    __init__.py                auto-detection order: wordpress → feed → sitemap
    base.py                    Source interface, URL/date filtering
    wordpress.py               WordPress REST API listing + batched fetch with embeds
    feed.py                    RSS/Atom via feedparser, page fetch for truncated bodies
    sitemap.py                 sitemap index crawl, per-page extraction
  extract.py                   readability + meta/JSON-LD extraction; build-time readability pass
  clean.py                     HTML → valid XHTML fragment; site rules, images, links, ids
  images.py                    srcset parsing, download with retry, media-type sniffing
  covers.py                    cover from a local path or a URL
  store.py                     cache/<blog>/index.json, posts/, images/
  sync.py                      discover → fetch changed → fetch images → save index
  epub.py                      selection, grouping, page renderers, EPUB 3 packaging
  assets/styles.css            e-reader friendly stylesheet
tests/                         pytest suite; runs offline with a fake HTTP client
.github/workflows/ci.yml       ruff, mypy, pytest + epubcheck on every push
.github/workflows/monitor.yml  weekly sync/build/release
.github/workflows/release.yml  dated release of one book
```

## Development

```bash
make check            # ruff (lint + format check), mypy, pytest
make format           # apply ruff fixes and formatting
make test
make epubcheck        # build everything, then validate with the W3C checker (needs Java)
EPUBCHECK_JAR=path/to/epubcheck.jar make test   # also runs the validator inside the test suite
```

[AGENTS.md](AGENTS.md) is the working guide: ground rules, the recipe pattern for adding a blog,
a gotchas table, and a map of where to change what. Design notes are in
[CONTRIBUTING.md](CONTRIBUTING.md). In short: sources are
small classes with `detect`, `discover` and `fetch`; `clean.clean_html` is the only place that
turns untrusted HTML into XHTML; the EPUB writer has no dependencies and its output is checked
structurally and with epubcheck in the tests; and the whole suite runs offline against a fake
HTTP client.

## Troubleshooting

- **`no usable source`**: the site has no WordPress API, feed or sitemap that answers. Pass the
  feed or sitemap URL explicitly with `feed: { url: ... }` or `sitemap: { url: ... }`.
- **Only ten posts**: the blog is feed-only. The cache accumulates with every sync; run the monitor
  weekly and the archive grows from now on.
- **`N image references had no cached file`**: images that failed to download. Permanent failures
  (404, not an image, too large) are remembered; transient ones (timeouts, server errors) are
  retried automatically three days later, or immediately with `sync --full`. `status` shows the
  counts.
- **A blog is unreachable**: it is reported as an error and the run continues with the other blogs;
  the exit code is 2 so CI notices. Books that include the failed blog are still built from what
  the cache holds.
- **Book too large**: with the default `split: size` a volume never exceeds `max_book_bytes`,
  so a "too large" file means the book has `split: none` or `year`. Images dominate; every build
  reports what optimisation saved, and if it says nothing, check the log for a Pillow error.
  Then lower `max_image_width` or `image_quality`, set `max_book_bytes` smaller, or use
  `images: false`.
- **Kindle shows "original layout preserved" / no font size control**: the converter met SVG. Make
  sure the `svg` extra is installed (the build warns when it is not) or set `svg_images: drop`.
- **A post is missing**: check `include`/`exclude`, `since`/`until`, and whether the source lists
  it (`detect URL --sample 50`).
- **Articles come with menus or footers**: add a `keep` selector for the article container, or
  `remove` selectors for the clutter. See [Site rules](#site-rules).
- **A `keep` selector removes everything**: it matched nothing on some pages and everything was
  kept, or it matched a wrapper. Test it in the browser inspector on two different posts.
- **WordPress returns 401/403 for the API**: the site restricts it. Set `source: feed` or
  `source: sitemap`.

## Limitations

- Feeds list only recent posts; sitemaps list everything but need extraction per page.
- Embedded video and iframes become links to the original. Inline SVG, forms and scripts are
  dropped.
- Comments are never included.
- The books are for personal reading. Content remains the property of its authors; the title page
  says so and every chapter links back to the original URL.

## Contributing and license

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md). Changes are tracked in [CHANGELOG.md](CHANGELOG.md).

MIT, see [LICENSE](LICENSE). Bundled fonts (Bebas Neue, Barlow, Barlow Condensed) are under the
SIL Open Font License 1.1.
