# blog2epub

Point it at blog root URLs. It keeps an eye on each of them and turns them into EPUB books for
your e-reader: a cover (yours or a generated one), a title page, a nested table of contents
(one *part* per year, month or blog, one *chapter* per post, with excerpts), readability-cleaned
post bodies with embedded images and lead images, and cross-links between posts that stay inside
the book. A book can be one blog's whole archive, or a magazine-style digest that combines
several blogs with a date range and a post limit.

The idea comes from Facundo Olano's
[Turn your blog into a book](https://jorge.olano.dev/blog/turn-your-blog-into-an-ebook/): an
EPUB is just zipped XHTML plus a manifest, so all you need is a way to get post bodies and a
template for the boilerplate. That post builds a book from a blog's *source files* with a static
site generator. This project does the same for blogs you **don't** own: it fetches posts through
whatever the site exposes, caches them, and writes the EPUB directly.

The first configured blog is [tyk.io/blog](https://tyk.io/blog).

## How it works

```
blogs.yaml ──► sync ──► cache/<blog>/ ──► build ──► output/<book>.epub
  blogs = sources       posts/*.json     books = outputs   (or <book>-<year>.epub)
  books = outputs       images/*
                │
                └── source auto-detected per blog:
                    1. WordPress REST API   (/wp-json/wp/v2/posts: full HTML, dates, authors, categories, featured image)
                    2. RSS / Atom feed      (+ page fetch and readability when the feed is truncated)
                    3. sitemap.xml          (+ readability extraction and meta/JSON-LD for dates)
```

- **Sources.** Each blog gets the richest source that answers. tyk.io is WordPress, so the REST
  API delivers all 627 posts in seven requests with clean rendered HTML and metadata, and no
  scraping of the page chrome is needed. Feeds and sitemaps cover everything else.
- **Monitoring.** `sync` lists what the source knows, compares it with the cache, and fetches
  only new posts and posts whose `modified` stamp changed. Posts that vanish from the source stay
  in the cache unless you pass `--prune`. `run` syncs and then rebuilds only blogs that changed.
- **Readability.** Pages fetched from a feed link or a sitemap go through
  [readability](https://github.com/buriy/python-readability) to isolate the article. The
  `readability` option controls a second pass at build time: `auto` (default) runs it on feed
  bodies, which often carry "this post appeared first on" footers; `always` runs it on every
  post, including WordPress API content; `never` skips it. The pass keeps the original whenever
  readability would throw away more than 40% of the text, so image-only figures and short posts
  are safe.
- **Cleaning.** Post HTML is normalised into well-formed XHTML: scripts, styles, forms,
  tracking attributes and Word pastes are stripped; iframes and videos become links; the best
  `srcset` candidate under `max_image_width` is chosen; lazy-load placeholders are resolved;
  headings are demoted so the post title is the only `h1`; links to other posts in the same
  book are rewritten to point inside the book.
- **Books.** A book is one or more blogs plus a selection (`since`, `until`, `max_posts`) and a
  layout (`group_by`, `order`, `split`). Every blog builds its own book unless it says
  `standalone: false`; the `books` list adds combined ones. Each chapter opens with the post's
  featured image when it has one, and every part page lists its posts with date, author and
  excerpt, which is what makes the combined books read like a magazine issue.
- **Building.** A dependency-free EPUB 3 writer produces `content.opf`, `nav.xhtml` (nested
  parts and chapters, plus landmarks), a `toc.ncx` for older readers, a title page with stats
  and sources, and the cover: your JPG/PNG (a path next to `blogs.yaml` or a URL) or a generated
  SVG. Output passes [epubcheck](https://github.com/w3c/epubcheck) with zero warnings.

## Quick start

```bash
make setup                 # venv + editable install
make test
.venv/bin/blog2epub list
.venv/bin/blog2epub run tyk                 # sync + build → output/tyk.epub
.venv/bin/blog2epub run api-management      # sync its five blogs, build the digest
.venv/bin/blog2epub status
```

Every command takes `-c path/to/blogs.yaml` and `-v`/`-vv` for progress output.

| Command | What it does |
| --- | --- |
| `list` | Show configured blogs, books, and how many posts are cached. |
| `detect URL` | Probe a URL, say which source would be used, list a few posts and print a ready-made config entry. |
| `sync [ids] [--full] [--prune]` | Fetch new and changed posts and their images into `cache/`. Ids are blogs or books. |
| `build [ids]` | Write EPUB(s) from the cache. Works offline (except a cover URL on first use). |
| `run [ids] [--force] [--report FILE]` | `sync`, then `build` every book whose blogs changed. `--report` writes a JSON summary (used by CI). |
| `status` | Cache size, date range, last sync, output files per book. |

## Configuration

```bash
.venv/bin/blog2epub detect https://example.org/blog
```

prints which source works for a URL and a ready-made entry to paste into `blogs.yaml`.
Everything under `defaults` applies to every blog and book unless overridden.

```yaml
defaults:
  output_dir: output
  cache_dir: cache
  request_delay: 0.5        # seconds between requests: be polite
  images: true              # download images (blog) / embed them (book)
  max_image_width: 1200     # largest srcset candidate not above this width
  max_image_bytes: 8000000
  group_by: year            # year | month | blog | none → the "part" level of the TOC
  order: asc                # asc reads oldest → newest like a book; desc is magazine order
  split: none               # none | year → one EPUB, or one per year
  demote_headings: true
  readability: auto         # auto | always | never
  excerpts: true            # excerpts on the part/contents pages
  featured_images: true     # lead image per chapter

blogs:                      # sources; each also builds its own book unless standalone: false
  - id: tyk                 # file names: output/tyk.epub, cache/tyk/
    title: "Tyk Blog"
    url: https://tyk.io/blog
    author: "Tyk Technologies"
    description: "Every post from the Tyk API management blog, collected as an ebook."
    source: auto            # auto | wordpress | feed | sitemap
    include: ["^https://tyk\\.io/blog/"]   # only URLs matching one of these are posts
    exclude: []
    # since: "2020-01-01"   # and/or until:  (also limits what gets fetched)
    # max_posts: 200        # keep only the most recent N in the standalone book
    # cover: covers/tyk.jpg # jpg/png path next to blogs.yaml, or a URL
    # wordpress: { api: https://tyk.io/wp-json/wp/v2, categories: [12, 15] }
    # feed:      { url: https://example.org/feed.xml }
    # sitemap:   { url: https://example.org/sitemap.xml }
  - id: kong
    title: "Kong Blog"
    url: https://konghq.com/blog
    standalone: false       # only used inside combined books

books:                      # combined outputs
  - id: api-management      # → output/api-management.epub
    title: "API Management Digest"
    blogs: [tyk, kong, gravitee, solo, postman]
    since: "2025-01-01"
    max_posts: 150          # the 150 most recent posts across all blogs
    group_by: blog          # one part per blog (or month for an issue-like layout)
    order: desc
    cover: covers/api-management.jpg
```

## Monitoring with GitHub Actions

`.github/workflows/monitor.yml` runs every Monday (and on demand):

1. restores `cache/` from the previous run, so only new posts are fetched;
2. runs `blog2epub run --report report.json`, which rebuilds every book whose blogs changed;
3. uploads all EPUBs as a workflow artifact;
4. when anything changed, refreshes the rolling **`latest`** GitHub release so the newest books
   are always at `https://github.com/<you>/blog2epub/releases/tag/latest`.

`workflow_dispatch` accepts `force` (rebuild everything) and `full` (ignore the cache).
Nothing generated is committed to the repository; `cache/` and `output/` are git-ignored.

## Layout

```
blogs.yaml                     configuration
src/blog2epub/
  cli.py                       commands
  config.py                    YAML → BlogConfig / BookConfig / Settings
  sources/                     wordpress.py, feed.py, sitemap.py, base.py (+ auto-detection)
  extract.py                   readability (page extraction and the build-time pass), meta/JSON-LD
  clean.py                     HTML → XHTML fragment, image/link rewriting
  images.py                    srcset selection, download, sniffing
  covers.py                    cover image from a path or URL
  store.py                     cache/<blog>/index.json, posts/, images/
  sync.py                      discover → fetch changed → fetch images
  epub.py                      EPUB 3 writer (opf, nav, ncx, parts with excerpts, chapters, cover)
  assets/styles.css            e-reader friendly stylesheet
tests/                         pytest; tests/test_epubcheck.py runs W3C epubcheck when EPUBCHECK_JAR is set
```

## Notes and limitations

- Feeds usually list only the most recent posts. The first sync of a feed-only blog gets what
  the feed offers; from then on the cache accumulates, so nothing is lost as long as the monitor
  keeps running. A sitemap source lists the whole archive when one exists.
- A whole archive with images can get big (the full tyk.io book with all images is tens of
  megabytes). Use `split: year` for one file per year, lower `max_image_width`, or set
  `images: false` for a text-only edition.
- Generated covers are SVG, which every EPUB 3 reader renders but Kindle conversions may not.
  Set `cover:` to a JPG or PNG for those.
- Embedded video and iframes are replaced by a link to the original. Inline SVG and forms are
  dropped.
- The books are for personal reading. The content stays the property of its authors; the title
  page says so and every chapter links back to the original URL.
