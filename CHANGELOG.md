# Changelog

All notable changes to blog2epub. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **The GitHub About sidebar has a source of truth.** `scripts/set_github_about.sh` (`make about`)
  writes the repository description, website link and topics with the gh CLI, and removes topics
  that are no longer in the list, so the sidebar mirrors the file.

### Removed
- **API Changelog is no longer a digest source.** The Substack is reachable locally but blocked
  from GitHub's runners, so it failed detection in every release run and never contributed a post
  to a published issue. The digest is now twelve blogs.

### Fixed
- **A missing cairo library no longer aborts a build.** cairosvg is optional twice over: the `svg`
  extra installs the Python package, and the package binds to a native cairo that pip does not
  install. With the module present and the library absent — a Mac after `uv sync` without
  `brew install cairo` — cairocffi raises `OSError` from dlopen rather than `ImportError`, which
  the import guard did not catch, so a decorative SVG could kill a build after a full sync had
  already run. Both absences now degrade the way the docs always claimed, and the warning names
  which half is missing.

### Changed
- **A blog that cannot be reached says why.** Detection used to fail with only "could not detect
  a WordPress API, feed or sitemap", which reads the same whether the site has no feed or is
  refusing us outright. Every rejected probe is now recorded and summarised in the error —
  grouped by outcome, one example URL each — so a release log shows `HTTP 403` rather than
  leaving the next reader to re-diagnose it. This is what the digest's Substack source has been
  hitting on every CI run: it is reachable locally and blocked from GitHub's runners.
- **Nothing waits on the slowest source.** Books now release in parallel (the release matrix had
  been sequential), and `sync`/`run` take `--jobs N` (default 4) to sync a book's blogs at once,
  so a throttled site such as Apigee — 1.5 seconds a request — holds up only its own book rather
  than the pipeline. Blogs sharing a host are serialised by a per-host lock, so parallelism never
  becomes extra load on a site. `sync.yml` is now the only writer of the download cache and the
  release jobs restore it read-only, since parallel savers would fork the cache lineage.
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
- **Issues are `YYYYMMDD`, and every file names its issue and its contents.** Output files are
  `<book>-<YYYYMMDD>-<volume>.epub` — `tyk-20260906-2024.epub`, `kong-20260906-vol2.epub`, and
  plain `apigee-20260906.epub` when a book is a single volume — so a downloaded asset identifies
  itself without the release page and a directory of them sorts into reading order. The title
  page says `Issue 20260905.2 · Volume 2 of 3`, and
  `build`/`run` take `--issue YYYYMMDD` so a release built on a later day keeps its date.
  A rebuild removes the book's files from earlier issues.
- **Releases run monthly, and every book has a stable tag.** `release.yml` runs on the 1st of
  every month at 07:00 UTC — every book, issue `YYYYMM01`, which matches the digest's rolling
  `since: 1m` window — and on demand from the Actions tab (`books: all` or a list, an optional
  `issue` date, `full`); tag and branch pushes no longer publish. Each book goes to `<book>-<YYYYMMDD>`, the issue, kept with a table of its
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
- **The agentgateway blog.** `agentgateway.dev/blog/`, the LF project for agent and MCP gateways:
  39 posts and 88 images across 2025 and 2026, as two year volumes. It joins the API Management
  Digest as a thirteenth source — AI gateways being where Kong, Gravitee, MuleSoft and Tyk are all
  writing now. `keep: .prose` because readability picks a wrapper that drops the fourteen code
  blocks and the diagrams out of a typical post.
- **`bin/publish` takes `--jobs N` and `--set KEY=VALUE`.** The cron entry point could reach
  neither, so a scheduled run was stuck with the default parallelism and whatever the file said.
- **`--set KEY=VALUE` overrides any config value for one run.** `KEY=VALUE` sets a `defaults` key,
  `ID.KEY=VALUE` sets it on one blog or book, and a dotted key reaches into a nested mapping
  (`--set apigee.sitemap.max=800`). Repeatable, and accepted either before the subcommand or
  after it. The value is read as YAML, so numbers, booleans, dates and lists all mean what they
  look like. Overrides are applied to the parsed config before anything is built, so they go
  through exactly the checks a line in the file would: an unknown key is refused, `50MB` is
  parsed into bytes, `split` is validated. Trying `--set tyk.split=month` no longer means editing
  `blogs.yaml` and remembering to put it back.
- **The MuleSoft blog.** `blogs.mulesoft.com` from 2008 to today: 2,505 posts and 7,243 images as
  nineteen year volumes, 368 MB, which makes it the largest book here. It joins the API Management
  Digest as a twelfth source. Of the 2,737 posts the API lists, 218 are excluded as
  `/news/events/` and `/news/careers/` — webinar invitations, conference announcements, recruiting
  and staff profiles, which date on publication and crowd out the writing in a year volume — and
  eight more are left out because the site's own API answers 500 for them.
- **Per-blog `user_agent` and `timeout`.** Both override the global setting for one blog, the way
  `request_delay` already did. MuleSoft needs both: its edge answers 403 to any agent string that
  looks like a crawler — a contact URL included, which the default carries — while its
  `robots.txt` disallows only `/wp-admin/`, and its API needs about 40 seconds to assemble a batch
  of 100 embedded posts, so the 30-second default cost four attempts a batch.
- **Collector's editions.** `blog2epub build <book> --collectors`, and `edition: collectors` on
  the release workflow, build a book's whole archive as one file — `<book>-collectors-<issue>.epub`,
  ignoring `split` and `max_book_bytes` — published to `<book>-collectors-<issue>` and
  `<book>-collectors-latest`. The builder treats it as a separate book (`tyk-collectors`), so the
  two editions' files, covers, tags and cleanup never collide and both can be kept. They are large
  by design: the whole Axway archive is 291 MB, past Send to Kindle's limit.
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
- **One unreachable source no longer costs the whole release.** `sync` exits 2 when a blog fails
  and the rest succeed — the point of isolating them — but the release workflow treated that as
  fatal and never reached the build. The first run ever to publish anything lost the API
  Management Digest that way: Substack was briefly unreachable at 04:26, the other twelve blogs
  were fully cached, and a perfectly good issue was never built. Exit 2 now warns and builds from
  the cache; a bad config still stops the job.
- **Relative links in a feed or a sitemap resolve.** A Hugo site whose `baseURL` is relative emits
  `/blog/slug/` rather than a URL, in `<link>` and in `<loc>` alike. Those matched no `include`
  regex and fetched nowhere, so agentgateway.dev read as 39 posts and zero readable pages, and its
  sitemap as none at all. Both sources now resolve a location against the document that listed it,
  which is what a feed reader does; an absolute URL is untouched, so nothing that already worked
  changes.
- **Releasing a book works.** Every release run was failing in the step that clears an issue's
  existing assets, and the repository has no releases to show for it. `gh api` writes its error
  body to STDOUT and skips `--jq` when a request fails, so the guard for "no release at this tag
  yet" — an empty capture — never fired: a 404 handed back the whole
  `{"message":"Not Found",...}` blob as the release id, and the next request was built around it
  (`releases/{"message":"Not Found",...}/assets`, *unsupported protocol scheme ""*). The id is
  now believed only when it is one, whatever gh prints. Covered by `tests/test_release_script.py`,
  which drives the script with a fake `gh` and reproduces the 404 exactly.
- Per-host sync locks are created under a lock of their own. A `defaultdict` lets two threads
  both miss the same host and each build a lock, after which both hold "the" lock for that host
  and the site sees two syncs at once. CPython's GIL makes that unreachable today, so it is not
  a bug anyone has hit — but a free-threaded build would reach it, and the politeness guarantee
  should not rest on an interpreter detail.
- Chapters no longer open with `Reading Time: 7 minutes`. The MuleSoft entry drops the plugin's
  stamp with a `remove` selector; it was on every one of its posts.
- A `Retry-After` is honoured for at most a minute. A post can embed an image from anywhere, and
  one third-party host answering `Retry-After: 1800` parked a whole sync for half an hour over a
  single picture. A skipped image is logged and tried again next sync; a stalled sync is just
  stalled.
- A WordPress batch the API refuses is split rather than dropped. One unserialisable old post — a
  deleted author, a term that no longer exists — makes the API answer 500 for every batch of 100
  it appears in, which says nothing about the other 99. The request now halves until the culprit
  is alone and named in the log. Two such posts were costing 200 of MuleSoft's.
- Bytes beat headers when deciding whether a download is an image. MuleSoft answers a long-deleted
  image with its 404 page under `Content-Type: image/png`; taking that at its word put four HTML
  files into the book as images, which epubcheck reports as corrupt.
- Markup inside a `pre` is put back as text. A `pre` takes phrasing content, so a `table` inside
  one is invalid however it got there — a Splunk dashboard pasted into a 2019 MuleSoft post, whose
  angle brackets the platform parsed instead of escaping. Re-serialising keeps the listing whole,
  where lifting the block out would scatter it across the page.
- The Tyk cover no longer says "Collector's edition" on every volume; the `$volume_label`
  placeholder already says so when it is true.
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
