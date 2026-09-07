---
name: add-blog
description: Add a blog to blog2epub and ship it as an EPUB release. Use when someone wants to turn a blog, newsletter or site into an ebook, add a source to blogs.yaml, work out a "recipe" for a new blog (which source, include regex, keep/remove selectors), build a book for a blog, or publish a blog archive as a tagged GitHub release. Triggers on "/add-blog", "add <site> to the books", "make a book from <url>", "create an epub for <blog>", "add a blog", "new recipe".
---

# Add a blog to blog2epub

Turn a blog URL into a configured, built, validated and released EPUB. The full reference for
each step, including the gotchas table, is `AGENTS.md` at the repository root — read it if
anything here is ambiguous.

Work through the phases in order. Do not skip phase 2: it is where books go wrong, and the damage
is invisible until someone reads a chapter that wanders into another article.

## Phase 0 — What are we making?

If the user gave a URL, use it. Otherwise ask for one.

Then ask, with `AskUserQuestion`, only what you cannot infer. Offer sensible defaults and say
which is recommended:

- **Scope** — a *complete archive* (every post ever, like the Tyk and Kong books), a *rolling
  window* (the last month or quarter, rebuilt fresh each time), or a *contributor to the API
  Management Digest* only (no book of its own, `standalone: false`).
- **Layout** — newest first with year → month sections (`order: desc`, `group_by: year-month`,
  what both archives use) or oldest first reading like a book (`order: asc`, `group_by: year`).
- **Cover** — generate one in the blog's own brand palette (recommended), use an image the user
  supplies, or accept the plain generated fallback.
- **Release** — publish a dated release now, or leave it to the weekly monitor.

Skip the question when the user has already answered it in their request.

## Phase 1 — Probe

```bash
uv run scripts/probe_blog.py <url>
```

Read the whole report before deciding anything. It gives you: every source that answers and the
post count each offers, the URL shape and a suggested `include` regex, `keep` and `remove`
candidates, five real extractions, a bleed check, and the site's brand colours.

Two judgement calls are yours, not the tool's:

- **Pick the source by coverage.** A feed usually lists only the latest ten posts. For a complete
  archive that is useless, so prefer the sitemap even though its metadata is thinner. If the site
  has a posts-only sitemap (`/sitemaps/blogs.xml`), point at it directly.
- **Confirm the `include` regex excludes index pages.** Sitemaps list category pages next to
  posts, and those become chapters that are just lists of links.
- **Cut the sections that are not articles.** A vendor blog files webinar invitations under
  `/events/`, recruiting under `/careers/`, press releases under `/press/`. They are the company
  talking about itself, and in a year volume they crowd out the writing. Look at the probe's
  section counts and `exclude` them by *exact path segment* — a loose `/events/` would take every
  post on event-driven architecture with it. Check the regex against what it keeps as well as
  what it drops.

**If the probe lists posts but cannot fetch them, read the URLs.**

```
39 posts
...
(skipping unreadable /blog/2026-08-27-agents-on-every-cloud/: No scheme supplied)
```

That is a **Hugo site with a relative `baseURL`**: `<link>` in the feed and `<loc>` in the
sitemap are paths, not URLs. Both sources resolve them against the document that listed them
now, so this is handled — but the same site will look odd in two other ways, and both are
normal for Hugo:

- **The sitemap covers the whole site**, docs and all, with no separate posts sitemap. Take the
  feed when it carries the full archive: Hugo publishes every post in `index.xml` by default,
  where a WordPress feed stops at ten. Check the counts rather than assuming — if the feed and
  the sitemap agree, the feed is the better source because it has dates and titles.
- **Readability often picks the wrong container.** Hugo themes wrap the article in utility-class
  divs (`.px-6`, `.max-w-3xl`) that a scorer likes as much as the prose. The tell is a sample
  with `images 0` and no code: compare candidates by what they *hold*, not by size.

```bash
# how many code blocks and images does each candidate actually contain?
uv run python -c "
from lxml import html; d = html.parse('/tmp/post.html').getroot()
for sel in ('.prose', '.content', 'article', 'main'):
    for e in d.cssselect(sel)[:1]:
        print(sel, len(e.cssselect('pre')), 'pre', len(e.cssselect('img')), 'img')"
```

  `.prose` is the Tailwind Typography class and is the right answer on most Hugo and Docusaurus
  sites; agentgateway is the worked example, where it is the difference between 0 and 107 code
  blocks across the book.

**If the probe cannot reach the site at all, work out why before giving up.**

- **403 on everything.** Read `robots.txt` first. If crawling is permitted (MuleSoft's disallows
  only `/wp-admin/` and advertises its sitemaps), the edge is filtering on the *shape* of the
  `User-Agent` — a contact URL is enough to trip Akamai. Retry with
  `--user-agent "blog2epub/0.2"` and, if that works, set `user_agent` on the entry. **Never
  impersonate a browser**: if a site does not want to be read, that is its answer, and the point
  is to identify honestly in a shape the filter accepts.
- **Everything times out.** A slow API is not a broken one. Time one request
  (`curl -o /dev/null -w '%{time_total}' '<api>/posts?per_page=100&_embed=...'`) — MuleSoft needs
  about 40 seconds for a batch of 100 — and set `timeout` on the entry rather than shrinking the
  archive.

## Phase 2 — Get the article body right

If the probe reports **bleed**, the page contains other posts (modern sites prerender related-post
cards) and readability has swallowed them. Fix it before going further:

1. Take a `keep` candidate that appears **exactly once** and holds 25–90% of the page's text.
2. Add `remove` selectors for the furniture: share bars, newsletter boxes, related cards,
   breadcrumbs, tag lists, author boxes, calls to action.
3. Re-run the probe with the rules and confirm bleed is zero on **every** sample:

```bash
uv run scripts/probe_blog.py <url> --keep "[class*='Article_body']" \
    --remove "[class*='Card_card']" --remove "[class*='Newsletter']"
```

**Always match class-name prefixes** (`[class*='Article_cta']`), never whole names: CSS-module
builds append a hash that changes on the site's next deploy.

Also read the head and tail of each sample yourself. The tool checks for other posts' titles; only
you can see that a body starts mid-navigation or stops before the conclusion.

`remove` is not only for bleed. After the first build, count how often each chapter's opening 70
characters repeats: a plugin stamp shows up as the same opening on every post. MuleSoft's
`Reading Time: 7 minutes` was on all 2,505 of them, one `.rt-reading-time` selector away. Do the
same for the closing 140 characters, where subscribe boxes and author bios live.

## Phase 3 — Configure

Paste the probe's draft entry into `blogs.yaml`, fill in `title`, `author` and `description`, and
apply the answers from phase 0. Comment every non-obvious rule with *why* it is there.

Then confirm the entry parses and reads as intended:

```bash
bin/blog2epub list
```

Try a value before committing to it rather than editing the file and forgetting to put it back.
`--set` overrides any config key for one run — `KEY=VALUE` for a `defaults` key, `ID.KEY=VALUE`
for one blog or book, dotted for a nested mapping — and goes through the same validation:

```bash
bin/blog2epub build <id> --set <id>.max_posts=20 --set <id>.split=none --set output_dir=/tmp/try
```

A 20-post sample build takes a minute and shows whether the chapters, covers and nav are right
before you spend two hours on the whole archive.

## Phase 4 — Sync

```bash
bin/blog2epub -v sync <id>
```

A large archive takes many minutes at the polite request delay, so **run it in the background** and
get on with the cover while it works. MuleSoft's 2,505 posts and 7,243 images took about two hours.

If you changed an existing blog's `source`, delete its cache first (`rm -rf cache/<id>`): post keys
are namespaced per source, so every post would be cached twice. If you added an `exclude` after a
sync, `sync --prune` drops the posts already cached that the entry no longer lists.

**Read the summary line; do not just watch it finish.** `2737 posts listed ... 2537 new` means 200
posts did not arrive, and the run still exits 0. The warnings above it say which and why: a batch
`splitting` is normal recovery, `post N cannot be fetched` is one post the API refuses (check it by
hand before writing it off — eight of MuleSoft's answer 500 on every attempt, which is their bug),
and `too short (N chars)` is a soft 404 or a genuine stub.

If a run goes quiet for a long time it is usually politeness, not a hang: `Retry-After` from a
third-party image host is honoured, capped at a minute. Check `wchan` before killing it —
`hrtimer_nanosleep` with flat CPU is a sleep.

## Phase 5 — Cover

Copy the closest template in `covers/` to `covers/<id>.html` and restyle it with the brand colours
the probe found. Make it look like its blog and unlike the other books. Keep the
`$volume_label` span beside the issue number: a split archive uses it to say *Vol. 2 of 3*. Set
`cover: covers/<id>.html` on the entry; the build renders the template once per volume. Then:

```bash
make cover
```

Look at the result before moving on. Check that nothing overlaps, the cover lines are real post
titles, and the count and year range are right.

## Phase 6 — Build and validate

```bash
bin/blog2epub build <id>
make epubcheck          # must report zero errors AND zero warnings, for every volume
```

A big archive comes out as several volumes, `output/<id>-<YYYYMMDD>-<volume>.epub`, each under
200 MB with its own cover under `output/covers/`. Validate the collector's edition too
(`build <id> --collectors`): it is one file of the whole archive, and at 300-400 MB epubcheck
may need `java -Xmx3g`. Look at one cover per volume: the label, count
and year span must describe that volume. Warnings are not acceptable: they are how Kindle decides
a book is malformed. Then open two or three chapters and confirm the body starts and ends where
the real article does, including one that links to a post in another volume — the link must
point at the web, not at a chapter file that is not there.

## Phase 7 — Document, commit, release

- Add the book to the README's book table and to `CHANGELOG.md` under *Unreleased*, and fold
  anything the blog taught you into `AGENTS.md`'s gotchas table — the next blog will hit it too.
- `make check` must pass.
- Commit and push to the working branch, then open a draft PR.
- If a fix to shared code (`clean.py`, `images.py`, `http.py`) came out of this blog, rebuild one
  *existing* book and re-validate it. A cleaner change that fixes one archive can break another.
- If the user wanted a release now, run the workflow — releases are manual and nothing else
  publishes:

```bash
gh workflow run release.yml -f books=<id>          # issue defaults to today, UTC
```

  or Actions tab → **Release books** → *Run workflow* → `books: <id>`, and again with
  `edition: collectors` for the one-file edition. Without `gh` or the permission to dispatch —
  which is the usual case from a sandboxed session — say so plainly and give the user those two
  lines rather than pushing a tag or a branch: a push must never publish. A release built before
  the change merges publishes the *old* configuration, so merge first.

`release.yml` syncs, builds with a cover per volume, and publishes to `<id>-<YYYYMMDD>` (the
issue, kept) and `<id>-latest` (moved to the newest issue), with a table of the volumes in the
notes; re-running the same issue replaces the files. Confirm it succeeded rather than assuming;
report both release URLs and the volume count.

## Report back

Tell the user: the source chosen and why, the post count and date range, any extraction rules and
what they were for, the epubcheck result, and the release link. Mention anything you could not
verify.

## Definition of done

The checklist at the end of `AGENTS.md`. In particular: zero bleed, zero epubcheck warnings, a
cover in the blog's own palette, and a spot-check of real chapters.
