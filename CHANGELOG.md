# Changelog

All notable changes to blog2epub. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
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
- The complete **Kong blog** archive as a second standalone book (901 posts): sourced from Kong's
  blog sitemap because the feed carries only the latest ten, with `keep`/`remove` rules for the
  related-post cards Kong prerenders into every page, and its own cover in Kong's palette.
- `scripts/render_cover.py --all` renders every cover template that names a configured blog or
  book; `make cover` and the monitor workflow use it.

### Fixed
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
