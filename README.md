# blog2epub

Turn the blogs you follow into books for your e-reader.

Point `blogs.yaml` at blog root URLs. blog2epub monitors them, caches every post, and writes
EPUB 3 files: a cover, a title page, a nested table of contents with excerpts, readability-cleaned
articles with their images, and cross-links that stay inside the book. A book can be one blog's
complete archive or a magazine-style digest that combines several blogs with a date range and a
post limit. A weekly GitHub Action keeps the books current.

The idea comes from Facundo Olano's
[Turn your blog into a book](https://jorge.olano.dev/blog/turn-your-blog-into-an-ebook/): an EPUB
is zipped XHTML plus a manifest, so all you need is the post bodies and a little boilerplate. That
post builds a book from a blog's *own source files* with a static site generator. blog2epub does
the same for blogs you **don't** own, by fetching posts through whatever the site exposes.

```
$ blog2epub run
tyk: 627 posts listed via wordpress (https://tyk.io/wp-json/wp/v2/posts); 0 new, 0 updated ...
kong: 10 posts listed via feed (https://konghq.com/feed/); 2 new, 0 updated ...
built output/tyk.epub - 627 posts, 956 images, 52.1 MB
built output/api-management.epub - 150 posts, 119 images, 36.9 MB
```

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Commands](#commands)
- [Configuration](#configuration)
- [Site rules](#site-rules)
- [Recipes](#recipes)
- [Keeping books current with GitHub Actions](#keeping-books-current-with-github-actions)
- [Reading the books](#reading-the-books)
- [Project layout](#project-layout)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [License](#license)

## Features

- **Three ways in, picked automatically.** WordPress REST API (full HTML, dates, authors,
  categories, featured images), RSS/Atom feeds (with a page fetch when the feed is truncated),
  and `sitemap.xml` crawling. The richest one that answers wins.
- **Incremental monitoring.** Each sync lists what the source knows, fetches only new and
  modified posts plus missing images, and keeps everything in a per-blog cache. Building is
  offline.
- **Readability.** Scraped pages go through readability to isolate the article. An optional
  build-time pass cleans feed and API bodies too, with a safety net that never drops a post's
  content.
- **Clean, valid XHTML.** Scripts, styles, forms, tracking attributes, Word pastes, lazy-load
  placeholders and custom elements are handled. Every generated book passes the W3C
  [epubcheck](https://github.com/w3c/epubcheck) with zero errors and warnings.
- **Site rules, Calibre-recipe style.** Per blog, `keep` names the article container and
  `remove` lists the clutter to drop, as CSS selectors. `extra_css` tunes the look.
- **Rolling windows.** `since: 7d`, `2w`, `3m` or `1y` on a book gives a "last week" or "last
  quarter" issue without editing dates.
- **Real navigation.** EPUB 3 `nav.xhtml` with parts (per year, month or blog), optional month
  sub-sections inside each year, and chapters; a `toc.ncx` for older readers; landmarks; and
  part pages that list each post with its date, author and excerpt.
- **Magazine digests.** Combine any number of blogs into one book, newest first, with a lead
  image per article and the blog name in every byline.
- **Your cover or a generated one.** Point `cover:` at a JPG/PNG (path or URL). The Tyk book
  ships with a magazine-style cover rendered from an HTML template with live cover lines
  (`make cover`, see `covers/README.md`).
- **Scriptable.** A plain CLI, a JSON report for automation, and a ready-made GitHub Actions
  workflow that publishes rebuilt books to a rolling release.

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
cached unless you pass `--prune`.

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

Java is only needed for `make epubcheck` and the optional validator test.

## Quick start

```bash
.venv/bin/blog2epub list                    # what is configured
.venv/bin/blog2epub run tyk                 # sync + build → output/tyk.epub
.venv/bin/blog2epub run api-management      # sync its five blogs, build the digest
.venv/bin/blog2epub status                  # cache and output state
```

To add a blog, let blog2epub probe it first:

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
| `keep` | `[]` | CSS selectors for the article container(s). When one matches, only that content is kept. See [Site rules](#site-rules). |
| `remove` | `[]` | CSS selectors for clutter to drop from every post (share bars, newsletter boxes, related posts). |
| `extra_css` | – | CSS appended to every book that contains this blog. Chapters carry `class="blog-<id>"` for scoping. |
| `request_delay` | inherits | Per-blog override. |
| `wordpress` | `{}` | `api` (base URL), `post_type`, `categories` (ids), `params` (extra query params). |
| `feed` | `{}` | `url` of the feed when discovery fails. |
| `sitemap` | `{}` | `url` of the sitemap when discovery fails. |
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
| `cover` | – | JPG/PNG path relative to `blogs.yaml`, or a URL (downloaded once). Otherwise a cover is generated. |
| `images` | `true` | Embed images. `false` gives a text-only edition. |
| `group_by` | `year` | Part level of the TOC: `year`, `year-month` (years with month sub-sections), `month`, `blog` or `none`. |
| `order` | `asc` | `asc` reads oldest to newest like a book; `desc` is magazine order. |
| `split` | `none` | `year` writes one EPUB per year (`<id>-<year>.epub`). |
| `demote_headings` | `true` | Shift headings inside posts down so the post title is the only `h1`. |
| `readability` | `auto` | Build-time readability pass: `auto` (feed bodies only), `always`, `never`. |
| `excerpts` | `true` | Excerpts on the part pages. |
| `featured_images` | `true` | Lead each chapter with the post's featured image. |
| `extra_css` | – | CSS appended to this book's stylesheet. |

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
    # cover: covers/tyk.jpg

  - id: kong
    title: "Kong Blog"
    url: https://konghq.com/blog
    standalone: false               # only used inside combined books
  - id: gravitee
    title: "Gravitee Blog"
    url: https://www.gravitee.io/blog
    standalone: false

books:
  - id: api-management
    title: "API Management Digest"
    description: "Recent posts from API management vendors, in one magazine-style ebook."
    blogs: [tyk, kong, gravitee]
    since: "2025-01-01"
    max_posts: 150
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

**A blog's complete archive, one file per year.** Big archives with images get large (the full
tyk.io book is about 50 MB). Split it:

```yaml
  - id: tyk
    url: https://tyk.io/blog
    split: year               # output/tyk-2015.epub ... output/tyk-2026.epub
```

**A weekly issue.** Newest first, grouped by blog, always the last seven days at build time:

```yaml
books:
  - id: apim-weekly
    title: "API Management Weekly"
    blogs: [tyk, kong, gravitee, solo, postman]
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

**Only some categories of a WordPress blog.** Find category ids at
`https://<site>/wp-json/wp/v2/categories`, then:

```yaml
  - id: tyk-engineering
    url: https://tyk.io/blog
    wordpress: { categories: [12, 15] }
```

**A blog whose feed is not discoverable:**

```yaml
  - id: example
    url: https://example.org/writing
    source: feed
    feed: { url: https://example.org/writing/index.xml }
```

## Magazine covers

`covers/tyk.jpg` is rendered from `covers/tyk.html` by `scripts/render_cover.py`: an HTML page
in Tyk's brand palette with a masthead, three kicker-plus-title cover lines taken from the newest
cached posts, a hexagon badge with the post count and year span, and a topic strip. Re-render it
after a sync to refresh the cover lines:

```bash
make cover        # installs the `covers` extra (Playwright) and renders covers/tyk.jpg
```

The cover carries an issue number, the render date as `2026.09.05`, and the title page inside the
book repeats it as `Issue 2026.09.05` from the build date. The weekly workflow re-renders the cover
before building, so both stay current. Copy the template to make a cover for another blog; the
placeholders (`$count`, `$issue`, `$issue_number`, `$kicker1`, `$title1`, ...) work for any blog id. Fonts are bundled under `covers/fonts/`
(SIL Open Font License), so rendering is identical everywhere and needs no network.

## Keeping books current with GitHub Actions

`.github/workflows/monitor.yml` runs every Monday at 06:00 UTC and on demand:

1. restores `cache/` from the previous run with `actions/cache`, so only new posts are fetched;
2. runs `blog2epub run --report report.json`, which rebuilds every book whose blogs changed;
3. uploads all EPUBs as a workflow artifact (kept 30 days);
4. when something changed, refreshes the rolling **`latest`** GitHub release, so the newest books
   are always at `https://github.com/<you>/blog2epub/releases/tag/latest`;
5. writes a summary to the job page.

"Run workflow" accepts two switches: `force` rebuilds every book, `full` ignores the cache and
re-fetches everything. Nothing generated is committed; `cache/` and `output/` are git-ignored.

To run somewhere else, any scheduler that can call `blog2epub run` works: the cache directory is
the only state.

## Reading the books

- **Kobo, PocketBook, Tolino, Boox, Apple Books, Calibre:** copy the `.epub` over as is.
- **Kindle:** Send to Kindle accepts EPUB up to 200 MB via the web and app, 25 MB via email.
  Set `cover:` to a JPG or PNG for Kindle; generated covers are SVG, which Kindle conversion may
  not render.
- The table of contents shows parts and chapters; part pages give the date, author and an excerpt
  for every post; every chapter links back to the original URL.

## Project layout

```
blogs.yaml                     configuration (blogs = sources, books = outputs)
covers/                        cover images, the Tyk cover template and bundled fonts
scripts/render_cover.py        renders an HTML cover template to JPG with Playwright
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
  clean.py                     HTML → valid XHTML fragment; images, links, ids, headings
  images.py                    srcset parsing, download, media-type sniffing
  covers.py                    cover from a local path or a URL
  store.py                     cache/<blog>/index.json, posts/, images/
  sync.py                      discover → fetch changed → fetch images → save index
  epub.py                      selection, grouping, page renderers, EPUB 3 packaging
  assets/styles.css            e-reader friendly stylesheet
tests/                         pytest suite (sources with a fake HTTP client, cleaner, builder, config)
.github/workflows/ci.yml       ruff, mypy, pytest + epubcheck on every push
.github/workflows/monitor.yml  weekly sync/build/release
```

## Development

```bash
make check            # ruff (lint + format check), mypy, pytest
make format           # apply ruff fixes and formatting
make test
make epubcheck        # build everything, then validate with the W3C checker (needs Java)
EPUBCHECK_JAR=path/to/epubcheck.jar make test   # also runs the validator inside the test suite
```

Design notes for contributors:

- Sources return `PostRef`s from `discover()` and `Post`s from `fetch()`. A new source is a class
  with `detect`, `discover`, `fetch` and `describe`, registered in `sources/__init__.py`.
- `clean.clean_html` is the only place that turns untrusted HTML into XHTML. Anything epubcheck
  complains about is fixed there, with a regression test in `tests/test_clean.py`.
- The EPUB writer has no dependencies; every page is a small render function in `epub.py`, and
  `tests/test_epub.py` parses the generated OPF, nav and NCX to check structure.
- `tests/test_sources.py` drives the sources with a fake HTTP client, so the suite runs offline.

## Troubleshooting

- **`no usable source`**: the site has no WordPress API, feed or sitemap that answers. Pass the
  feed or sitemap URL explicitly with `feed: { url: ... }` or `sitemap: { url: ... }`.
- **Only ten posts**: the blog is feed-only. The cache accumulates with every sync; run the monitor
  weekly and the archive grows from now on.
- **`N image references had no cached file`**: images that failed to download (too large, not an
  image, server error). `sync --full` retries them; `status` shows the counts.
- **Book too large**: use `split: year`, lower `max_image_width`, or `images: false`.
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

## License

MIT. See [LICENSE](LICENSE).
