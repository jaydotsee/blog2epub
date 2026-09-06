# Changelog

All notable changes to blog2epub. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- **uv is the package manager.** `uv.lock` pins every dependency; `uv sync --all-extras` (or
  `make setup`) builds `.venv` from it, the dev tools live in a PEP 735 `dev` group rather than
  an extra, and the Makefile and every workflow run through `uv run`. `bin/blog2epub` runs the
  CLI through uv from any directory, and `bin/publish <book>` is the cron entry point: one
  book per crontab line, logging to `logs/`, finding uv on cron's bare `PATH`, and serialising
  on the download cache so overlapping entries queue.
- **Books are cut into volumes, one per year by default.** `split` now takes `year` (the
  default), `month`, `size` or `none`. Whatever the split, no volume exceeds `max_book_bytes`
  (default `200MB`, Send to Kindle's limit) except with `none`: `size` cuts only where the budget
  says, and a year or month that outgrows it is cut inside the period and its parts numbered.
  The planner weighs text as the zip will store it and images at their file size, so an archive
  of any length arrives readable. Links to a post that landed in another volume go back to the
  post's own URL.
- **Issues are `YYYYMMDD` and volumes are `YYYYMMDD.n`.** Output files are
  `<book>-<YYYYMMDD>.<n>.epub`, the title page says `Issue 20260905.2 · Volume 2 of 3`, and
  `build`/`run` take `--issue YYYYMMDD` so a release built on a later day keeps its date.
  A rebuild removes the book's files from earlier issues.
- **Releases are manual, and every book has a stable tag.** `release.yml` runs only from the
  Actions tab (`books: all` or a list, an optional `issue` date, `full`); tag and branch pushes
  no longer publish. Each book goes to `<book>-<YYYYMMDD>`, the issue, kept with a table of its
  volumes in the notes, and to `<book>-latest`, moved to the newest issue on every run. Both are
  cleared before upload, so re-running an issue replaces its files rather than adding to them.
  Books build one after another so each sync lands in the shared cache. The weekly monitor is
  gone; `sync.yml` takes its slot and only keeps the download cache warm — GitHub evicts an
  Actions cache after seven days unused — building and publishing nothing.
- **Every volume gets its own cover.** Point `cover:` at an HTML template (`covers/<id>.html`)
  and the build renders it once per volume with that volume's post count, year span, cover
  lines and issue number; `$volume`, `$volumes` and `$volume_label` ("2024", or "Vol. 2 of 3"
  for a size split) are new placeholders, and the shipped templates show the label beside the
  issue number. Rendering
  moved from `scripts/render_cover.py` into `blog2epub.covers`; the script now only refreshes
  the previews in `covers/`. Without Playwright the build uses the image beside the template.
- `build` gained `--report FILE`, the same JSON `run` writes, with one entry per volume.

### Added
- Image optimisation is now a standard step in the pipeline: Pillow is a core dependency,
  `optimize_images` defaults to on, every build reports what it saved, and a missing Pillow is
  an error in the log rather than a silently enormous book. Images are downscaled to
  `max_image_width` and re-encoded; transparent PNGs above 150 KB are flattened onto white and
  encoded as JPEG, which is what dominates a large archive. The Kong book went from 705 MB to
  236 MB with no visible change on an e-reader.
- The complete **Axway** archive (1,968 posts, 2011 to 2026) — the longest here, and the one
  that made size-based volumes necessary — and the complete **Gravitee** archive (656 posts). Both have covers in their brand palette. Gravitee
  publishes through HubSpot, so its entry reads that sitemap rather than the site's own.
- Per-blog `title_strip`: regexes matched against the end of a post title and dropped, applied
  at build time so a rule can change without re-fetching. For a stale brand the generic rules
  cannot know about, such as the Ambassador Labs naming a migration left on ten Gravitee posts.
- `AGENTS.md`: how to work on the repository and the recipe pattern for adding a blog, with the
  gotchas learned building the Tyk and Kong archives.
- `scripts/probe_blog.py`: works out a new blog's recipe in one command — sources and their post
  counts, URL shape and `include` regex, `keep`/`remove` candidates, a real extraction with a
  cross-article bleed check, brand colours, and a draft config entry.
- The `/add-blog` skill, which walks from a URL to a published release.
- `HttpClient.get_text_tolerant` retries the other trailing-slash form on 404, so sitemaps that
  disagree with their server (Gravitee lists `/slug/`, serves `/slug`) work.
- Sitemap indexes partitioned by date or language can be narrowed and uncapped with
  `sitemap: { include: [...], max: N }` — Google Cloud's blog has 1058 such files.
- `min_chars` (default 150) skips posts whose body is too short to be real, so soft 404s (a site
  answering 200 with an error page) never become chapters.
- `scripts/probe_blog.py --from-config --id <blog>` probes a blog through its configured source
  and rules, for iterating on an entry that auto-detection cannot reach.
- The complete **Apigee** archive (244 posts, 2011 to 2026) from Google Cloud's blog, with a
  cover in Google's palette.
- The complete **Kong blog** archive as a second standalone book (901 posts): sourced from Kong's
  blog sitemap because the feed carries only the latest ten, with `keep`/`remove` rules for the
  related-post cards Kong prerenders into every page, and its own cover in Kong's palette.
- `scripts/render_cover.py --all` renders every cover template that names a configured blog or
  book; `make cover` and the monitor workflow use it.

### Fixed
- Block elements are lifted out of the paragraphs that cannot legally contain them. WordPress
  drops a `figure` or a video-embed `div` straight into a `<p>`; browsers close the paragraph
  silently, epubcheck does not. This was 170 errors across the Axway archive. The repair now
  covers every phrasing-only element (`p`, `h1`-`h6`, `dt` and the inline tags), replacing the
  narrower inline-only version.
- A `dl` carrying terms but no descriptions (WordPress galleries emit `dl > dt` alone) becomes
  plain blocks rather than an invalid definition list.
- An href may carry only one `#`. A broken markdown link produced two, which epubcheck rejects;
  the fragment is now percent-encoded like the path and query already were.
- SVGs cairosvg cannot parse are retried with `light-dark()` and `var()` colours resolved to
  their light-theme value, which is what draw.io emits and what a book wants. The warning for
  SVGs left unrasterised no longer blames a missing cairosvg when cairosvg is installed.
- Placeholder publication dates are ignored. HubSpot writes `1970-01-01T00:00:00.000Z` when the
  field is unset and puts the real date on a second JSON-LD node; three Gravitee posts were
  landing in a 1970 chapter. A date now has to be 1995 or later to count, and an unusable one no
  longer blocks a later good one on the same page.
- A trailing site name is stripped from post titles. `og:title` and `<title>` routinely carry
  " | Site Name" where the on-page `<h1>` does not, which put "| Gravitee" and "| Ambassador" in
  25 chapter titles. The tail goes when the page's own headline ends earlier or when the tail is
  the site naming itself; a title that genuinely contains a pipe, and another brand's name on a
  migrated post, are both left alone.
- Kindle's Send to Kindle converter treated books containing SVG images as fixed layout. SVG
  images (and the generated fallback cover) are now rasterised to PNG at build time
  (`svg_images: raster`, the default; `keep` and `drop` are the alternatives). Needs the new
  `svg` extra (cairosvg).

## [0.2.0] – 2026-09-05

### Added
- Combined **books** from any number of blogs (`books:` in `blogs.yaml`), with `since`/`until`,
  `max_posts`, `group_by: blog | year | year-month | month | none`, `order`, `split`.
- Rolling date windows (`7d`, `2w`, `3m`, `1y`) for blogs and books.
- Site rules per blog: `keep`, `remove` (CSS selectors) and `extra_css`.
- Build-time readability pass (`readability: auto | always | never`).
- Featured/lead images, excerpts on contents pages, issue numbers on covers and title pages.
- Year → month → post navigation (`group_by: year-month`) with month pages in reading order.
- Magazine covers rendered from HTML templates (`scripts/render_cover.py`, `make cover`), with
  bundled OFL fonts; covers for the Tyk archive and the API Management Digest.
- The **API Management Digest**: a monthly book from eleven API-management blogs.
- Weekly monitor workflow with a rolling `latest` release; on-demand `release.yml` publishing a
  dated release from a tag, a `release/<book>-<date>` branch, or the Actions tab.
- Network robustness: per-blog failure isolation, whole-file image retries, transient vs
  permanent image failures with automatic retry after three days.

### Changed
- Media-type sniffing trusts an explicit non-image Content-Type over the URL extension.

## [0.1.0] – 2026-09-05

### Added
- Initial release: WordPress REST, RSS/Atom and sitemap sources with auto-detection, incremental
  per-blog cache, XHTML cleaner, dependency-free EPUB 3 writer with `nav.xhtml` and `toc.ncx`,
  CLI (`list`, `detect`, `sync`, `build`, `run`, `status`), CI with epubcheck.

[Unreleased]: https://github.com/jaydotsee/blog2epub/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/jaydotsee/blog2epub/releases/tag/v0.2.0
[0.1.0]: https://github.com/jaydotsee/blog2epub/commits/20669e6
