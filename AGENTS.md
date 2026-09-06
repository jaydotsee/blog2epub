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
uv run scripts/probe_blog.py https://example.com/blog
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

**Cut the sections that are not articles.** A vendor blog is not only writing: MuleSoft files
218 posts under `/news/events/` (webinar invitations, conference announcements) and
`/news/careers/` (recruiting, staff profiles). They are the company talking about itself, they
date the moment they are published, and in a year volume they crowd out the writing someone
opened the book for. Look at the section counts the probe reports and exclude them:

```yaml
# the second path segment has to match exactly, so event-*driven architecture* articles stay
exclude: ["^https://blogs\\.mulesoft\\.com/[^/]+/(events|careers)/"]
```

Then check what the regex would drop before trusting it. Count the URLs it matches, and read the
ones it *keeps* that mention the same words: a loose `/events/` would take every post on
event-driven design with it. `sync --prune` removes posts already cached that the entry no
longer lists.

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

Bleed is not the only thing `remove` is for. After the first build, take the first 70 characters
of every chapter body and count how often each one repeats: a plugin's stamp shows up as the same
opening on every post. MuleSoft's `Reading Time: 7 minutes` was on all 2,505 of them, one
`.rt-reading-time` selector away. Do the same for the last 140 characters, where subscribe boxes
and author bios live.

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
bin/blog2epub -v sync kong             # minutes for a large archive; run it in the background
```

**If you changed a blog's `source`, delete its cache first** (`rm -rf cache/<id>`). Post keys are
namespaced per source (`wp-`, `feed-`, `sm-`), so the same post arrives under a new key and you
get every post twice.

**Read the summary line, do not just watch it finish.** `2737 posts listed ... 2537 new` means
200 posts did not arrive, and the run still exits 0. The warnings above it say which and why:

- `batch of 100 posts starting N failed, splitting` — the API refused a whole batch, so the
  request was halved until the culprit was alone. Normal; the other 99 still land.
- `post N cannot be fetched, skipping` — that post alone is unserveable. Check it by hand
  (`curl -o /dev/null -w '%{http_code}' <api>/posts/N`) before writing it off: eight of
  MuleSoft's answer 500 on every attempt, which is their bug and nothing to work around.
- `not fetched:` / `too short (N chars)` — a soft 404 or a genuine stub. Read a couple.

**A stalled sync is usually politeness, not a hang.** A post can embed an image from any host,
and `Retry-After` is honoured — capped at a minute since MuleSoft's archive turned up one that
asks for 1800 seconds. If a run goes quiet, check `wchan` before killing it: `hrtimer_nanosleep`
with flat CPU is a sleep, not a deadlock.

**A 403 is not always a refusal.** MuleSoft's edge rejects any `User-Agent` that looks like a
crawler — a contact URL included, which the default carries — while its `robots.txt` disallows
only `/wp-admin/` and advertises the sitemaps. Read `robots.txt` first. If crawling is permitted,
set a per-blog `user_agent` that is shorter but still honest (`blog2epub/0.2`). Never impersonate
a browser: if a site does not want to be read, that is its answer.

**A slow API is not a broken one.** MuleSoft needs about 40 seconds to assemble a batch of 100
embedded posts, so the 30-second default cost four attempts a batch. Time one request before
concluding anything, and set a per-blog `timeout`.

### 7. Cover

Take the palette from the probe's brand colours (a site's most-used hex values *are* its brand)
and copy the closest existing template in `covers/`. Each book should look like its blog and
unlike the others: Tyk is purple with hexagons, Kong is acid lime on near-black with a service
mesh, the digest is teal and amber with a diagonal month band.

Point the entry's `cover:` at the template. The build renders it **once per volume**, from that
volume's posts: `$count`, `$years` (`2015 – 2026`, or `2015` for one year), `$years_prose`,
`$first_year`, `$last_year`, `$issue`, `$issue_number` (`20260905.2`),
`$volume`, `$volumes`, `$volume_label` (`Vol. 2 of 3`, empty for a single volume), `$month`,
`$year`, `$url`, `$title`, `$blog_count`, `$blog_list`, and `$kicker1`/`$title1` … for cover lines
drawn from the newest posts. Put `$volume_label` beside the issue number, as the shipped templates
do, so a split archive says which volume it is. The rendering lives in `blog2epub.covers`;
`scripts/render_cover.py` only refreshes the whole-book previews in `covers/`:

```bash
make cover        # renders every covers/<id>.html whose id names a configured blog or book
```

Fonts are bundled under `covers/fonts/` so rendering needs no network and is identical everywhere.

Books are cut into one volume per year by default (`split: year`); `month`, `size` and `none`
are the alternatives, and except with `none` no volume exceeds `max_book_bytes` (200 MB): a year
that outgrows it is cut inside the year. A digest with a rolling window wants `split: size`, or a
January issue is cut in two at New Year. Output is `<id>-<issue>-<volume>.epub` (`tyk-20260906-2024.epub`, `kong-20260906-vol2.epub`;
no suffix when the book is one volume), the issue being the build date as `YYYYMMDD`;
`build --issue` pins it. `OUTPUT_RE` still recognises the older `<id>-<issue>.<n>.epub` so a
rebuild cleans up files from the first issues. See `plan_volumes` in `epub.py` for how posts
are weighed.

### 8. Build and validate

```bash
bin/blog2epub build kong
make epubcheck                          # zero errors, zero warnings
```

Then actually look at the book: open two or three chapters and confirm the body starts at the real
first paragraph, ends at the real conclusion, and contains no other post.

### 9. Ship it as a release

Releases run on the 1st of every month (every book, issue `YYYYMM01`) and on demand. To publish
now: Actions tab → **Release books** → *Run workflow* with `books: kong` (or `all`) and,
optionally, an `issue` date; or from a terminal:

```bash
gh workflow run release.yml -f books=kong            # issue defaults to today, UTC
gh workflow run release.yml -f books=all -f issue=20260906
```

`release.yml` syncs, builds (rendering a cover per volume) and publishes each book to two tags:
`<book>-<YYYYMMDD>`, the issue, kept for good with its volumes `<book>-<YYYYMMDD>.<n>.epub` and
a table of them in the notes; and `<book>-latest`, moved to the same files on every run so there
is one stable link per book. Re-running an issue clears its assets first, so it replaces rather
than accumulates. Books run one after another so each sync lands in the shared cache, which the
weekly `sync.yml` keeps warm without building or publishing anything. Do not add tag or branch
triggers back: a push must never publish, only the schedule and the button.

A collector's edition is the same book with `split: none` under the id `<book>-collectors`:
`build --collectors`, or `edition: collectors` on the release workflow. Deriving it by id rather
than by a second blogs.yaml entry is what keeps the two editions' files, covers and cleanup from
colliding — `book_outputs` matches the id exactly — so do not "simplify" it into a shared name.

Books release in parallel, and `sync --jobs N` (default 4) syncs a book's blogs at once, so one
throttled source delays only itself. Two rules hold that together and are easy to break:
`sync.yml` is the **only** writer of the download cache — release jobs use `actions/cache/restore`,
because parallel savers would fork the lineage — and blogs sharing a host are serialised by a
per-host lock in `_sync_blogs`, so concurrency never turns into extra load on a site.

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
| Book too large to email | The book has `split: none`; otherwise no volume passes `max_book_bytes` | Drop `split: none`, or lower `max_image_width` / `image_quality`; a build that reports no optimisation saving has a Pillow error in the log |
| A link in one volume points at a chapter in another | It cannot; `package` rewrites those to the post's URL | Nothing, unless a test shows `ch-NNNN.xhtml` surviving across the cut |
| Chapters are lists of links | `include` matched index pages | Tighten the regex to the post depth |
| `include` matches nothing at all | The URL given is a **tag page**, not a section | Find where posts really live (see below) |
| The feed is "not available" but you know it exists | It is on another host | Set `feed.url` explicitly |
| Chapters read "404. That's an error." | The site answers 200 for missing pages | `min_chars` (default 150) skips them |
| A huge sitemap index stops early | More than 200 partitions | `sitemap: { include: [...], max: N }` |
| A blog fails and the run stops | — | It should not: failures are isolated per blog, exit code 2 |
| Every request 403s, but `robots.txt` welcomes crawlers | The edge filters on `User-Agent` shape, the contact URL included | Per-blog `user_agent`, shorter and still honest; never a browser string |
| Batches of posts time out and retry forever | The API is slow, not down: 100 embedded posts can take 40s | Per-blog `timeout`; time one request to pick it |
| 100 posts missing and the sync still exits 0 | One unserveable post makes the API 500 for its whole batch | Handled: the batch is halved until the culprit is named. Read the warnings |
| A sync goes quiet for half an hour | A third-party image host answered `Retry-After: 1800` | Handled: capped at a minute. Check `wchan` before killing a quiet run |
| An image is "corrupt" in epubcheck | The site served its 404 page under `Content-Type: image/png` | Handled: the bytes are sniffed first, and a web page is not an image |
| A `table` inside a `pre` fails RSC-005 | A pasted config snippet was parsed rather than escaped | Handled: markup inside a `pre` is re-serialised as text |
| Volumes full of webinar invitations and job posts | The archive includes `/events/` and `/careers/` sections | `exclude` them by exact path segment, then `sync --prune` |
| The same sentence opens every chapter | A plugin stamp (`Reading Time: 7 minutes`) inside the body | A `remove` selector. Count repeated chapter openings after the first build |

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
- [ ] Sync completes; `blog2epub status` shows the expected posts and few failed images, and the
      summary line's post count is the one you expect — its warnings read, not skimmed
- [ ] Sections that are not articles (`/events/`, `/careers/`, press releases) are excluded, and
      the regex checked against what it keeps as well as what it drops
- [ ] The book builds and passes epubcheck with zero errors and zero warnings
- [ ] A cover template exists in the blog's own palette, `cover:` points at it, `make cover`
      regenerates the preview, and the volume covers under `output/covers/` carry the right label
- [ ] Chapters spot-checked: right start, right end, no other post, and no boilerplate repeated
      across every one of them
- [ ] README book table and `CHANGELOG.md` updated
- [ ] `make check` passes, and the change is committed and pushed
