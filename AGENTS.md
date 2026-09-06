# AGENTS.md

Working notes for anyone — human or agent — changing this repository. The README explains what
blog2epub does and documents every configuration key; this file covers **how to work on it** and,
above all, **how to add a blog**, which is the task that comes up most and the one with the
non-obvious traps.

## Ground rules

- `make check` (ruff, ruff format, mypy, pytest) must pass before every commit. CI runs the same
  on Python 3.10 and 3.12.
- **Images are downscaled on every build.** Blogs serve desktop-sized images and a complete
  archive of them is unreadably large, so optimisation is a standard step rather than an option:
  Pillow is a core dependency and `optimize_images` defaults to on. Each build reports what it
  saved; a build that reports nothing is a bug worth chasing.
- **Every generated book passes epubcheck with zero errors *and* zero warnings.** Warnings are not
  acceptable here: they are how Kindle and other converters decide a book is malformed. Validate
  with `make epubcheck`.
- The test suite runs **offline**. Network code is driven by `FakeClient` in
  `tests/test_sources.py`; add to it rather than reaching for the real internet.
- Be polite to the sites we read: keep `request_delay` at 0.5s or higher, and put a contact URL in
  the user agent. We are guests.
- The books are for personal reading. Every chapter links back to the original and the title page
  says the content belongs to its authors. Keep it that way.

## Adding a blog: the recipe pattern

A "recipe" here is one entry in `blogs.yaml`. Getting it right is an investigation, not a guess.
Run `/add-blog` to be walked through it, or follow the steps below.

### 1. Probe before you configure

```bash
.venv/bin/python scripts/probe_blog.py https://example.com/blog
```

This one command answers everything the entry needs: which sources answer and how many posts each
lists, the shape of the post URLs with a suggested `include` regex, candidate `keep` and `remove`
selectors, a real extraction of five posts, a **bleed** check, the site's brand colours, and a
draft entry to paste. Re-run it with `--keep`/`--remove` to test rules before committing to them.

### 2. Choose the source by post count, not by rank

Auto-detection prefers WordPress → feed → sitemap, because that is the order of metadata quality.
**But a feed usually lists only the latest ten posts.** For a complete archive, what matters is
coverage:

| Blog | Feed | Sitemap | Chosen |
| --- | --- | --- | --- |
| tyk.io | — | — | WordPress API, 627 posts in 7 requests |
| konghq.com | 10 posts | 901 posts | sitemap |
| gravitee.io | 10 posts | 668 posts | sitemap |

If the site publishes a sitemap dedicated to posts (`/sitemaps/blogs.xml`), point `sitemap.url`
straight at it instead of the sitemap index. It is fewer requests and no filtering guesswork.

### 3. Pin the URL shape

Sitemaps list category and index pages alongside posts. Look at the path depth the probe reports
and write an `include` regex that keeps only posts:

```yaml
# Kong posts are /blog/<category>/<slug>; /blog/<category> is an index page
include: ["^https://konghq\\.com/blog/[^/]+/[^/]+"]
```

Without this you get chapters that are lists of links.

**Check that the URL you were given is a section, not a tag.** `cloud.google.com/blog/products/apigee`
looks like a section and is really a tag page: not one post lives under that path. The posts are
filed under `/blog/products/api-management/` and other product sections, and merely *surfaced* on
the Apigee page. An `include` regex built from the given URL would have matched nothing. Take the
URLs from the source listing (or the feed) and see where they actually point before writing the
regex.

Large sites partition their sitemap index by date and language. Google Cloud's blog has 1058
fortnightly files across a dozen languages; walking them all would blow past the safety cap and
waste hundreds of requests on translations. Narrow it:

```yaml
    sitemap:
      url: https://cloud.google.com/transform/sitemapsummary/cloudblog
      include: ["/cloudblog/en/"]   # skip ja, ko, fr, ...
      max: 400                      # the default cap is 200
```

### 4. Get the article body, and check for bleed

This is the step that is easy to get wrong and hard to notice.

Readability is good at finding the story on a classic page. On a modern JavaScript-rendered site
it often is not, because **the page contains other posts**: Kong prerenders twenty related-post
cards into every article, complete with their full text. Readability happily includes them, so a
chapter about API linting ends mid-sentence in an unrelated article about Kafka.

The probe checks for this by looking for *other posts' titles* inside each extracted body. If it
reports bleed:

1. Find the container that holds only the story. The probe's `keep` candidates list ranks
   containers that appear **exactly once** and hold 25–90% of the page's text.
2. Add it as `keep`. It is applied to the whole page *before* readability when a page is scraped,
   and again to the cached body at build time.
3. Add `remove` selectors for what remains: share bars, newsletter boxes, related cards,
   breadcrumbs, tag lists, author boxes, calls to action.
4. Re-run the probe with the rules and confirm bleed is zero **across all samples**, not one.

**Match class-name prefixes, never whole names.** CSS-module builds append a content hash
(`Article_cta__EpjTW`) that changes on the site's next deploy. Use attribute matching:

```yaml
keep:   ["[class*='TableOfContents_body']"]
remove: ["[class*='Card_card']", "[class*='Article_cta']", "[class*='Breadcrumbs_']"]
```

Verify against posts from **different years and categories**. Sites change templates; a rule that
fits 2026 may miss 2019.

### 5. Write the entry

Paste the probe's draft into `blogs.yaml` and fill in `title`, `author` and `description`. For a
complete archive, match the shape the other archives use:

```yaml
  - id: kong
    title: "Kong Blog"
    url: https://konghq.com/blog
    author: "Kong Inc."
    description: "Every post from the Kong blog: ..."
    source: sitemap
    sitemap: { url: https://konghq.com/sitemaps/blogs.xml }
    include: ["^https://konghq\\.com/blog/[^/]+/[^/]+"]
    keep: ["[class*='TableOfContents_body']"]
    remove: ["[class*='Card_card']", "[class*='Article_cta']"]
    order: desc               # newest first
    group_by: year-month      # year → month → posts
    cover: covers/kong.html   # rendered once per volume at build time
```

Add `standalone: false` if the blog should only feed combined books and not get one of its own.
Comment *why* a rule exists; a bare selector is unreadable in six months.

### 6. Sync

```bash
.venv/bin/blog2epub -v sync kong        # minutes for a large archive; run it in the background
```

**If you changed a blog's `source`, delete its cache first** (`rm -rf cache/<id>`). Post keys are
namespaced per source (`wp-`, `feed-`, `sm-`), so the same post arrives under a new key and you
get every post twice.

### 7. Cover

Take the palette from the probe's brand colours (a site's most-used hex values *are* its brand)
and copy the closest existing template in `covers/`. Each book should look like its blog and
unlike the others: Tyk is purple with hexagons, Kong is acid lime on near-black with a service
mesh, the digest is teal and amber with a diagonal month band.

Point the entry's `cover:` at the template. The build renders it **once per volume**, from that
volume's posts: `$count`, `$first_year`, `$last_year`, `$issue`, `$issue_number` (`20260905.2`),
`$volume`, `$volumes`, `$volume_label` (`Vol. 2 of 3`, empty for a single volume), `$month`,
`$year`, `$url`, `$title`, `$blog_count`, `$blog_list`, and `$kicker1`/`$title1` … for cover lines
drawn from the newest posts. Put `$volume_label` beside the issue number, as the shipped templates
do, so a split archive says which volume it is. The rendering lives in `blog2epub.covers`;
`scripts/render_cover.py` only refreshes the whole-book previews in `covers/`:

```bash
make cover        # renders every covers/<id>.html whose id names a configured blog or book
```

Fonts are bundled under `covers/fonts/` so rendering needs no network and is identical everywhere.

Books are cut into volumes by size by default (`split: size`, each under `max_book_bytes`,
200 MB); `year`, `month` and `none` are the alternatives. Output is `<id>-<issue>.<n>.epub`, the
issue being the build date as `YYYYMMDD`; `build --issue` pins it. See `plan_volumes` in
`epub.py` for how posts are weighed.

### 8. Build and validate

```bash
.venv/bin/blog2epub build kong
make epubcheck                          # zero errors, zero warnings
```

Then actually look at the book: open two or three chapters and confirm the body starts at the real
first paragraph, ends at the real conclusion, and contains no other post.

### 9. Ship it as a release

```bash
git checkout main && git pull
git tag -a kong-20260905 -m "Kong Blog, issue 20260905"
git push origin kong-20260905
```

`release.yml` syncs, builds (rendering a cover per volume) and publishes the release tagged
`<book>-<YYYYMMDD>` with the volumes attached as `<book>-<YYYYMMDD>.<n>.epub` and a table of
them in the notes. Re-running an issue clears its assets first, so it replaces rather than
accumulates. A `release/<book>-<YYYYMMDD>` branch push or the Actions tab do the same thing. The
weekly `monitor.yml` keeps every book fresh on the rolling `latest` release regardless.

## Gotchas, and what they look like

| Symptom | Cause | Fix |
| --- | --- | --- |
| Only ~10 posts in the book | The blog is feed-only | Use the sitemap source |
| A chapter drifts into an unrelated article | Prerendered related-post cards | `keep` the article container |
| Rules stop working after the site redeploys | CSS-module hash in the class name | Match the prefix: `[class*='Article_cta']` |
| Every post appears twice | `source` changed; keys are namespaced per source | `rm -rf cache/<id>` and re-sync |
| Kindle says "original layout preserved" | SVG images in the book | `svg_images: raster` (the default) with the `svg` extra |
| Every sitemap URL 404s | Sitemap lists `/slug/`, server serves `/slug` | Handled: `HttpClient.get_text_tolerant` |
| epubcheck NAV-011 warnings | A TOC link points backwards past earlier chapters | Section pages go in the spine right before their chapters |
| Book too large to email | The book has `split: none` or `year`; with the default `split: size` no volume passes `max_book_bytes` | Use `split: size`, or lower `max_image_width` / `image_quality`; a build that reports no optimisation saving has a Pillow error in the log |
| A link in one volume points at a chapter in another | It cannot; `package` rewrites those to the post's URL | Nothing, unless a test shows `ch-NNNN.xhtml` surviving across the cut |
| Chapters are lists of links | `include` matched index pages | Tighten the regex to the post depth |
| `include` matches nothing at all | The URL given is a **tag page**, not a section | Find where posts really live (see below) |
| The feed is "not available" but you know it exists | It is on another host | Set `feed.url` explicitly |
| Chapters read "404. That's an error." | The site answers 200 for missing pages | `min_chars` (default 150) skips them |
| A huge sitemap index stops early | More than 200 partitions | `sitemap: { include: [...], max: N }` |
| A blog fails and the run stops | — | It should not: failures are isolated per blog, exit code 2 |

## Where to change what

| Change | File | Tests |
| --- | --- | --- |
| A config key | `src/blog2epub/config.py` | `tests/test_config.py` |
| A new source | `src/blog2epub/sources/` + register in `__init__.py` | `tests/test_sources.py` |
| Anything epubcheck complains about in post markup | `src/blog2epub/clean.py` | `tests/test_clean.py`, `tests/test_rules.py` |
| Anything epubcheck complains about in packaging | `src/blog2epub/epub.py` | `tests/test_epub.py`, `tests/test_epubcheck.py` |
| Fetching, retries, failure handling | `src/blog2epub/http.py`, `images.py` | `tests/test_network.py` |
| A CLI command | `src/blog2epub/cli.py` | `tests/test_network.py` |

`clean.clean_html` is the only place untrusted HTML becomes XHTML. Fix markup problems there, with
a regression test carrying the offending markup.

## Definition of done for a new blog

- [ ] The probe reports the expected post count and **zero bleed** across samples from several years
- [ ] `blogs.yaml` entry has a title, author, description, and a comment on every non-obvious rule
- [ ] Sync completes; `blog2epub status` shows the expected posts and few failed images
- [ ] The book builds and passes epubcheck with zero errors and zero warnings
- [ ] A cover template exists in the blog's own palette, `cover:` points at it, `make cover`
      regenerates the preview, and the volume covers under `output/covers/` carry the right label
- [ ] Chapters spot-checked: right start, right end, no other post
- [ ] README book table and `CHANGELOG.md` updated
- [ ] `make check` passes, and the change is committed and pushed
