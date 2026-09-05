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
.venv/bin/python scripts/probe_blog.py <url>
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

## Phase 2 — Get the article body right

If the probe reports **bleed**, the page contains other posts (modern sites prerender related-post
cards) and readability has swallowed them. Fix it before going further:

1. Take a `keep` candidate that appears **exactly once** and holds 25–90% of the page's text.
2. Add `remove` selectors for the furniture: share bars, newsletter boxes, related cards,
   breadcrumbs, tag lists, author boxes, calls to action.
3. Re-run the probe with the rules and confirm bleed is zero on **every** sample:

```bash
.venv/bin/python scripts/probe_blog.py <url> --keep "[class*='Article_body']" \
    --remove "[class*='Card_card']" --remove "[class*='Newsletter']"
```

**Always match class-name prefixes** (`[class*='Article_cta']`), never whole names: CSS-module
builds append a hash that changes on the site's next deploy.

Also read the head and tail of each sample yourself. The tool checks for other posts' titles; only
you can see that a body starts mid-navigation or stops before the conclusion.

## Phase 3 — Configure

Paste the probe's draft entry into `blogs.yaml`, fill in `title`, `author` and `description`, and
apply the answers from phase 0. Comment every non-obvious rule with *why* it is there.

Then confirm the entry parses and reads as intended:

```bash
.venv/bin/blog2epub list
```

## Phase 4 — Sync

```bash
.venv/bin/blog2epub -v sync <id>
```

A large archive takes many minutes at the polite request delay, so **run it in the background** and
get on with the cover while it works.

If you changed an existing blog's `source`, delete its cache first (`rm -rf cache/<id>`): post keys
are namespaced per source, so every post would be cached twice.

## Phase 5 — Cover

Copy the closest template in `covers/` to `covers/<id>.html` and restyle it with the brand colours
the probe found. Make it look like its blog and unlike the other books. Then:

```bash
make cover
```

Look at the result before moving on. Check that nothing overlaps, the cover lines are real post
titles, and the count and year range are right.

## Phase 6 — Build and validate

```bash
.venv/bin/blog2epub build <id>
make epubcheck          # must report zero errors AND zero warnings
```

Warnings are not acceptable: they are how Kindle decides a book is malformed. Then open two or
three chapters and confirm the body starts and ends where the real article does.

## Phase 7 — Document, commit, release

- Add the book to the README's book table and to `CHANGELOG.md` under *Unreleased*.
- `make check` must pass.
- Commit and push to `main`.
- If the user wanted a release now:

```bash
git tag -a <id>-$(date -u +%Y.%m.%d) -m "<Title>, issue $(date -u +%Y.%m.%d)"
git push origin <id>-$(date -u +%Y.%m.%d)
```

`release.yml` syncs, renders the cover, builds and publishes the release with the EPUB attached.
Confirm it succeeded rather than assuming; report the release URL.

## Report back

Tell the user: the source chosen and why, the post count and date range, any extraction rules and
what they were for, the epubcheck result, and the release link. Mention anything you could not
verify.

## Definition of done

The checklist at the end of `AGENTS.md`. In particular: zero bleed, zero epubcheck warnings, a
cover in the blog's own palette, and a spot-check of real chapters.
