# Design: blog2epub as a service — an API first, a web app on top

Status: **proposal**, for discussion. Nothing here is built yet.
Companion contract: [`openapi.yaml`](openapi.yaml).

## 1. What we are building

Today blog2epub is a CLI driven by one `blogs.yaml`, run by a maintainer and by GitHub Actions,
publishing a fixed shelf of nine books as releases. The proposal is to let anyone do what the
maintainer does — point it at the blogs they read and get books on their e-reader — through a
web app in the spirit of [RSS to Kindle](https://www.rsstokindle.com/app):

1. **Add a blog** by pasting a URL, and see what blog2epub would make of it before committing.
2. **Compose a book**: one blog's archive, or a digest of several over a rolling window.
3. **Get it**: download now, deliver on a schedule to a Kindle address, or pull it from an OPDS
   catalogue on the reader itself.

It is **API first**: every one of those actions is an HTTP endpoint with a published OpenAPI
contract, and the web app is just one client of it, with no private back door. The CLI, a
future mobile client, scripts and other agents all use the same surface.

### Requirements

These are fixed; the rest of the document is how to meet them.

| # | Requirement | Where it is met |
| --- | --- | --- |
| R1 | **Multi-user** from the first release: sign-up, sign-in, per-user books and settings | [§5.1](#51-accounts-and-authentication), [§4](#4-domain-model) |
| R2 | **Single-source or combined books**: one blog, or several blogs rendered into one book or digest, exactly as `blogs:` and `books:` work in `blogs.yaml` today | [§4](#4-domain-model) (Book) |
| R3 | **Daily, weekly and monthly digests delivered to a Kindle by email** | [§6](#6-jobs-scheduling-and-delivery) |
| R4 | **Each user schedules their own deliveries**, per book, in their own timezone | [§4](#4-domain-model) (Schedule), [§6](#6-jobs-scheduling-and-delivery) |
| R5 | **One cache shared by every user**: a blog is fetched and stored once, however many people read it | [§2](#2-principles-carried-over-from-the-cli), [§6](#6-jobs-scheduling-and-delivery) |
| R6 | **The API covers the full lifecycle**: sign-up, verification, sign-in, password reset, adding blogs, books, schedules, delivery targets, account settings, account deletion | [§5](#5-the-api), [`openapi.yaml`](openapi.yaml) |

### What blog2epub already does better than a feed-to-Kindle service

RSS to Kindle and similar services send *the latest items in a feed*. blog2epub's pipeline does
three things they do not, and the product should lead with them:

- **Complete archives, not the last ten posts.** Source choice by coverage (WordPress API →
  sitemap → feed) means a book can hold 2,505 posts back to 2008.
- **Clean chapters.** `keep`/`remove` recipes and the bleed check mean a chapter is the article,
  not the article plus twenty prerendered related-post cards.
- **Real books.** Year → month navigation, excerpts, per-volume covers, epubcheck-clean output,
  and volume splitting that already knows about Send to Kindle's size limits.

### Non-goals (for now)

- Paywalled or logged-in content. We never hold third-party credentials.
- Public sharing of user-built books. A user's books are private to them; the public shelf stays
  the curated releases.
- Replacing `blogs.yaml`. It remains a first-class format: the service imports and exports it.
- Arbitrary user-supplied cover templates or CSS (see [§8](#8-security-and-abuse)).

## 2. Principles carried over from the CLI

These are the rules in `AGENTS.md`, restated for a service with many users. They shape the design
more than any framework choice does.

| Rule today | What it becomes in a service |
| --- | --- |
| Be polite: ≥ 0.5 s between requests, honest User-Agent, one host at a time | **One shared cache per blog, not per user.** A thousand subscribers to Kong cost Kong one sync. Syncs are scheduled by the service, never triggered directly by users. Per-host locks become distributed locks. |
| Read `robots.txt` before crawling | Checked automatically for every user-submitted blog; a disallow blocks the source. |
| Books are for personal reading; every chapter links back | User books are private and never listed publicly. Attribution stays on the title page and every chapter. A per-host opt-out list honours takedown requests. |
| Every book passes epubcheck with zero warnings | Unchanged. The worker builds with exactly the library code the CLI uses; CI keeps the epubcheck suite. |
| Images are always optimised | Unchanged, and optimised images are cached per `(url, width, quality)` so a digest built for 500 users re-encodes each image once. |
| A recipe is an investigation, not a guess | User-added blogs start as **auto** recipes (source detection + readability). Curated recipes — the ones in `blogs.yaml` — are promoted by a maintainer after the `/add-blog` checks. The UI says which a blog is. |

## 3. Architecture

```mermaid
flowchart LR
  subgraph Clients
    WEB[Web app<br/>SPA]
    CLI[blog2epub CLI]
    EXT[Scripts / agents]
    READER[E-reader<br/>OPDS]
  end

  subgraph Service
    API[API server<br/>FastAPI · /v1]
    SCHED[Scheduler<br/>cron tick]
    Q[(Job queue<br/>Postgres SKIP LOCKED)]
    W1[Worker: probe / sync]
    W2[Worker: build / deliver]
  end

  subgraph Core["blog2epub library (existing)"]
    SRC[sources · extract · clean]
    SYNC[sync_blog]
    EPUB[build_book · covers]
  end

  DB[(Postgres<br/>users, blogs, books,<br/>jobs, builds)]
  OBJ[(Object storage<br/>post cache, images,<br/>EPUBs, covers)]
  MAIL[Email provider<br/>Send to Kindle]
  WEBSITES((Blogs))

  WEB & CLI & EXT --> API
  READER --> API
  API --> DB
  API --> Q
  SCHED --> Q
  Q --> W1 & W2
  W1 --> SRC & SYNC
  W2 --> EPUB
  SYNC --> WEBSITES
  W1 & W2 --> OBJ
  W1 & W2 --> DB
  W2 --> MAIL
```

Four deployable pieces, all from one Python package so they can never drift apart:

| Piece | What it does | Scales with |
| --- | --- | --- |
| **API server** (`blog2epub.api`) | Auth, validation, CRUD, enqueues jobs, streams job progress, serves signed download links and OPDS | requests; stateless |
| **Worker** (`blog2epub.worker`) | Runs `probe`, `sync`, `build`, `deliver` jobs by calling the existing library | CPU (image optimisation, builds) and politeness budget (syncs) |
| **Scheduler** | Every minute: enqueue due deliveries; keep blog caches fresh | one instance (leader lock) |
| **Web app** | Static SPA built against the generated TypeScript client | CDN |

The CLI keeps working exactly as it does today against local files. A later `--remote` mode can
point it at the API, but that is not needed for anything below.

### Technology choices, with the reason for each

- **FastAPI + Pydantic v2.** Python, so it imports the library directly; OpenAPI and JSON Schema
  come out of the models, and the web app's forms are generated from that schema.
- **Postgres** for everything relational *and* the job queue (`SELECT … FOR UPDATE SKIP LOCKED`,
  e.g. via Procrastinate). One stateful dependency instead of Postgres + Redis. Advisory locks
  give us the distributed per-host lock for free.
- **Object storage (S3/R2/MinIO)** for the post cache, images, EPUBs and covers. Local filesystem
  on a single machine, so `docker compose up` needs no cloud.
- **Web app: React + Vite + TanStack Query** with a client generated by `openapi-typescript`.
  The generated client is the enforcement of API-first: if the web app needs something the
  contract lacks, the contract changes first. (SvelteKit in static mode is an equally good
  choice; the point is a static SPA with no server of its own.)
- **Playwright/Chromium in the worker image** only, for cover rendering, as `release.yml` does
  today.

## 4. Domain model

```mermaid
erDiagram
  USER ||--o{ BOOK : owns
  USER ||--o{ DELIVERY_TARGET : has
  USER ||--o{ API_TOKEN : has
  USER ||--o{ SESSION : has
  BLOG ||--o{ POST : caches
  BOOK }o--|{ BLOG : "draws from (1 = single, 2+ = combined)"
  BOOK ||--o{ SCHEDULE : "delivered by"
  SCHEDULE }o--|{ DELIVERY_TARGET : "sends to"
  BOOK ||--o{ BUILD : produces
  SCHEDULE ||--o{ BUILD : triggers
  BUILD ||--|{ VOLUME : "split into"
  BUILD ||--o{ DELIVERY : "sent as"
  DELIVERY }o--|| DELIVERY_TARGET : "sent to"
  JOB }o--o| BLOG : "probe/sync"
  JOB }o--o| BUILD : "build"
  JOB }o--o| DELIVERY : "deliver"
```

Everything a user owns (books, schedules, targets, builds, tokens) carries `user_id` and every
query is scoped by it. Blogs, posts and the blob cache carry **no** `user_id`: they are the shared
layer (R5), and a user reaches them only through the books that reference them.

| Entity | Maps to today | Notes |
| --- | --- | --- |
| **Blog** | a `blogs:` entry → `BlogConfig` | **Shared across users**, unique by canonical URL. Holds the recipe (`source`, `include`, `exclude`, `keep`, `remove`, `sitemap`, …) as JSON validated by `BlogConfig`. `tier`: `curated` (from `blogs.yaml`, maintainer-owned) or `auto` (user-submitted, detection + readability only). Also: `status` (`active`, `blocked_robots`, `failing`, `opted_out`), `last_sync`, `post_count`, `first_date`/`last_date`. |
| **Post** | `cache/<id>/index.json` entries | The index moves to a table (key, url, title, date, modified, fetched_at, **first_seen**, which
never changes on a re-fetch and is what digests key on) so the API can list, search and count posts without reading JSON files. The body and images stay in the blob cache, exactly as `BlogStore` lays them out. |
| **User** | — | email (verified), password hash (argon2id) or none for magic-link-only accounts, `timezone`, `locale`, default delivery target, notification preferences, `role` (`user`/`admin`), `status` (`pending_verification`, `active`, `suspended`, `deleted`). |
| **Book** | a `books:` entry → `BookConfig`, or a standalone blog → `BlogConfig.as_book()` | **Per user.** `blogs` (one or more) + the book options (`since`, `until`, `max_posts`, `group_by`, `order`, `split`, `max_book_bytes`, `cover` from the curated set, `featured_images`, …). `kind` is derived: **single** with one blog, **combined** with several (R2). Both go through the same `BookConfig` and the same `build_book`, which is why one model serves both. |
| **Schedule** | the monthly cron in `release.yml` | **Per user, per book, any number** (R4): "Kong weekly to my Paperwhite" and "Kong monthly to my Scribe" are two schedules on one book. `frequency` (`daily` / `weekly` + weekday / `monthly` + day), local `time`, `timezone` (default: the user's), `targets`, `content` (`new_posts` — a digest of what arrived since this schedule last delivered — or `window`, which uses the book's own `since`/`until`), `skip_if_empty`, `paused`, `start_from`, `last_delivered_through` (the first-seen time of the newest post sent; see [§6](#6-jobs-scheduling-and-delivery)), `next_run_at`. |
| **Build** | one `build_book` call / one release issue | `issue` (YYYYMMDD), `edition` (`standard`/`collectors`), status, the `BuildResult` of every volume. Files expire after 30 days; the book can always be rebuilt. |
| **Volume** | one `BuildResult` | path in object storage, `label`, `posts`, `images`, `bytes`, `first_date`, `last_date`, cover image. |
| **DeliveryTarget** | — | `kindle_email` (`…@kindle.com`), `email`, `webhook`. `max_bytes` per kind drives the volume split (see [§6](#6-delivery)). |
| **Delivery** | — | one build → one target: status, provider message id, error. |
| **Job** | a CLI invocation | `probe`, `sync`, `build`, `deliver`; status, progress, log lines, result. |

**The schedule, not the book, decides what a digest covers.** A book says *which* blogs and *how*
the book looks; a schedule says *when* and *how much*. With `content: new_posts` a daily schedule
delivers yesterday's posts, a weekly one the week's, a monthly one the month's — from one book
definition, with no `since` window to keep in step with the cadence, and a missed run (an outage,
a paused schedule) catches up next time instead of dropping posts. `content: window` keeps
today's behaviour for a book that already has `since: 1m` or is a full archive.

The book-to-blog relationship is many-to-many **by reference**: a user's book never copies a
recipe. When a maintainer fixes Kong's `remove` selectors, every user's Kong book gets cleaner
at its next build, because `keep`/`remove` are applied to the cached body at build time.

## 5. The API

Base path `/v1`. JSON everywhere; errors are RFC 9457 `application/problem+json`. The full
contract is in [`openapi.yaml`](openapi.yaml); this section is the shape and the reasoning.

### Resources

| Resource | Endpoints | Notes |
| --- | --- | --- |
| Auth | `POST /auth/signup` · `POST /auth/verify-email` · `POST /auth/login` · `POST /auth/magic-link` · `POST /auth/logout` · `POST /auth/password-reset` · `POST /auth/password-reset/confirm` · `POST /auth/token` | See [§5.1](#51-accounts-and-authentication). |
| Account | `GET/PATCH/DELETE /me` · `POST /me/password` · `POST /me/email` · `GET /me/export` · `GET/DELETE /me/sessions/{id}` | Settings (timezone, locale, default target, notifications) are fields on `/me`, changed with `PATCH`. `DELETE /me` removes the user's books, schedules, targets and builds; the shared cache is untouched. |
| Tokens | `GET/POST /tokens` · `DELETE /tokens/{id}` | Personal API tokens, scoped (`books:read`, `books:write`, `blogs:write`, `deliveries:write`, `account`). |
| Probes | `POST /probes` → 202 · `GET /probes/{id}` | Wraps `scripts/probe_blog.py`: sources that answer with post counts, URL shape and suggested `include`, sample extractions, bleed, brand colours, a draft recipe. Also how a blog gets added. |
| Blogs | `GET /blogs?q=&tier=&mine=` · `GET /blogs/{id}` · `POST /blogs` · `GET /blogs/{id}/posts` · `GET /blogs/{id}/posts/{key}` | `POST /blogs` takes a completed probe id; a URL that already exists returns `303 See Other` to the existing blog. Post bodies come back cleaned, as the chapter would render them — that is the preview. Users cannot edit a shared recipe; they can *propose* one (`POST /blogs/{id}/recipe-proposals`). |
| Catalogue | `GET /catalogue` | The curated shelf (today's nine books) with links to the latest release files. Needs no account. |
| Books | `GET/POST /books` · `GET/PATCH/DELETE /books/{id}` · `GET /books/{id}/preview` | `PATCH` is JSON Merge Patch. `preview` returns what a build would contain — volumes, post counts, TOC — without building, from `select_entries` + `plan_volumes`. |
| Builds | `POST /books/{id}/builds` → 202 · `GET /books/{id}/builds` · `GET /builds/{id}` · `GET /builds/{id}/volumes/{n}/epub` → 302 · `…/cover` | `Idempotency-Key` honoured. The download is a short-lived signed object-storage URL. |
| Schedules | `GET/POST /books/{id}/schedules` · `GET /schedules` · `GET/PATCH/DELETE /schedules/{id}` · `POST /schedules/{id}/run` | Any number per book. `GET /schedules` lists all of a user's, soonest first, for the dashboard. `run` delivers now, outside the cadence, and counts as a delivery for `new_posts`. |
| Delivery targets | `GET/POST /delivery-targets` · `DELETE /delivery-targets/{id}` · `POST /delivery-targets/{id}/test` | `test` sends a one-page EPUB so the user can confirm their approved-sender list. |
| Deliveries | `POST /builds/{id}/deliveries` → 202 · `GET /deliveries?book=` | Send an existing build somewhere. Scheduled runs create these themselves. |
| Jobs | `GET /jobs/{id}` · `GET /jobs/{id}/events` (SSE) · `POST /jobs/{id}/cancel` | Every 202 above returns `Location: /v1/jobs/{id}`. |
| Config interop | `GET /config.yaml` · `POST /config.yaml` | Export the user's books and the recipes they use as a valid `blogs.yaml`; import one. The round trip goes through `load_config`, so it is validated the same way. |
| OPDS | `GET /opds/{feed_token}/catalog.xml` | An OPDS 1.2 acquisition feed of the user's latest builds, for KOReader, Kobo (via plugins), Moon+ and others. Token in the path, because readers cannot send headers; revocable. |
| Webhooks | outbound `build.succeeded`, `build.failed`, `delivery.failed` | Signed (HMAC) and retried. |
| Admin | `POST /admin/blogs/{id}/promote` · `…/block` · `GET /admin/recipe-proposals` · `PATCH /admin/users/{id}` | Maintainers turn an `auto` blog into a `curated` one after the `/add-blog` checks. |

### 5.1 Accounts and authentication

The whole account lifecycle is in the API (R6); the web app has no endpoints of its own.

```mermaid
stateDiagram-v2
  [*] --> pending_verification: POST /auth/signup
  pending_verification --> active: POST /auth/verify-email
  pending_verification --> [*]: unverified after 7 days, purged
  active --> active: PATCH /me · password / email change
  active --> suspended: admin (abuse, bounces)
  suspended --> active: admin
  active --> deleted: DELETE /me
  deleted --> [*]: owned data purged after 30 days
```

| Step | Call | Behaviour |
| --- | --- | --- |
| Sign up | `POST /auth/signup {email, password?, timezone}` | Always `202` with the same body, whether or not the address is taken, so sign-up cannot be used to find out who has an account. Sends a verification link. Password optional: without one the account signs in by magic link only. |
| Verify | `POST /auth/verify-email {token}` | Single-use token, 24 h. Until verified the account can build and download but **cannot deliver by email**: an unverified account must not be able to make us send mail. |
| Sign in | `POST /auth/login {email, password}` or `POST /auth/magic-link {email}` then `POST /auth/login {magic_token}` | Browser: sets an `HttpOnly; Secure; SameSite=Lax` session cookie, with a CSRF token for unsafe methods. |
| Programmatic | `POST /auth/token` (exchanges a session for a personal token) or `POST /tokens` | `Authorization: Bearer b2e_…`. Tokens are stored hashed, scoped, and listed with last use. |
| Sign out | `POST /auth/logout`; `DELETE /me/sessions/{id}` signs out another device | |
| Reset password | `POST /auth/password-reset {email}` → `POST /auth/password-reset/confirm {token, password}` | Same anti-enumeration response as sign-up. A reset ends all sessions. |
| Change email | `POST /me/email {email}` | Takes effect when the new address is verified; the old address is told. |
| Settings | `PATCH /me {timezone, locale, default_target, notifications}` | Changing the timezone moves every schedule that uses the user's timezone. |
| Export | `GET /me/export` | The user's books, schedules and targets as JSON, plus their books as a `blogs.yaml`. |
| Delete | `DELETE /me` (re-authentication within the last 10 min) | Schedules stop at once; owned rows and build files are purged after 30 days. Blogs the user added stay: they are shared, and another user's book may use them. |

Admins are users with `role: admin`: they promote and block blogs, review recipe proposals and
suspend accounts, through `/admin/…` endpoints in the same contract. OIDC sign-in ("Sign in with
Google/GitHub") can be added later as another way to reach the same session; nothing else depends
on how the user signed in.

### Conventions

- **Long work is a job, never a long request.** Probe, sync, build and deliver take seconds to
  hours (a full MuleSoft sync is ~40 s *per batch*). They return `202 Accepted` with the job, and
  progress streams over SSE (`GET /jobs/{id}/events`), which a browser `EventSource` and `curl -N`
  both read. Events are the library's own milestones: `listed 2737`, `fetched 120/2737`,
  `images 40 fetched, 2 failed`, `volume 2 of 3 written`.
- **Validation errors name the field.** `ConfigError` messages are already precise
  (`book 'x': \`split\` must be one of [...]`). The API raises them as 422 problems with an
  `errors[].pointer` (`/split`) so the web form can put the message next to the input.
- **Cursor pagination** (`?cursor=&limit=`, `next` in the body and in `Link`) on every list. Post
  lists get long: Axway is 1,968 posts.
- **ETags + `If-Match`** on books and schedules, so two tabs cannot silently overwrite each other.
- **Idempotency-Key** on every `POST` that starts work. A retried "build now" must not build twice.
- **Rate limits** with `RateLimit` headers: probes and builds are the expensive calls.
- **Versioning**: `/v1` in the path; additive changes only within it.

### Example: from sign-up to a weekly digest on a Kindle

```http
POST /v1/auth/signup
{"email": "reader@example.com", "password": "…", "timezone": "Europe/London"}
→ 202 Accepted   (verification email sent)

POST /v1/auth/verify-email
{"token": "…"}
→ 200 OK, Set-Cookie: b2e_session=…
```

```http
POST /v1/probes
{"url": "https://konghq.com/blog"}

202 Accepted
Location: /v1/jobs/job_7Qx
{"id": "prb_3Kd", "status": "running", "job": "job_7Qx"}
```

```http
GET /v1/probes/prb_3Kd

200 OK
{
  "id": "prb_3Kd",
  "status": "succeeded",
  "url": "https://konghq.com/blog",
  "existing_blog": null,
  "robots": {"allowed": true},
  "sources": [
    {"name": "feed",    "posts": 10,  "note": "a feed lists only the latest posts"},
    {"name": "sitemap", "posts": 901, "url": "https://konghq.com/sitemaps/blogs.xml", "recommended": true}
  ],
  "url_shape": {"depths": {"2": 12, "3": 889}, "suggested_include": ["^https://konghq\\.com/blog/[^/]+/[^/]+"]},
  "samples": [
    {"url": "https://konghq.com/blog/engineering/…", "title": "…", "date": "2026-08-14", "chars": 9120, "bleed": ["Kafka at the edge"]}
  ],
  "bleed_count": 5,
  "draft": {"source": "sitemap", "sitemap": {"url": "https://konghq.com/sitemaps/blogs.xml"}, "include": ["…"]},
  "brand_colours": ["#ccff00", "#0b0d0f"]
}
```

```http
POST /v1/blogs
{"probe": "prb_3Kd", "title": "Kong Blog"}
→ 201 Created, Location: /v1/blogs/blg_kong   (tier: auto; first sync queued)

POST /v1/books
{"title": "Kong, every post", "blogs": ["blg_kong"], "order": "desc",
 "group_by": "year-month", "split": "year"}
→ 201 Created, Location: /v1/books/bk_9f

POST /v1/books/bk_9f/builds
Idempotency-Key: 5d0c…
→ 202 Accepted, Location: /v1/jobs/job_Bq2
```

A combined book is the same call with more blogs. Blogs other users have already added are
found with `GET /v1/blogs?q=`, and are already synced:

```http
POST /v1/books
{"title": "API gateways weekly", "blogs": ["blg_kong", "blg_tyk", "blg_gravitee"],
 "group_by": "blog", "order": "desc", "split": "size"}
→ 201 Created, Location: /v1/books/bk_2m   (kind: combined)

POST /v1/delivery-targets
{"kind": "kindle_email", "name": "Paperwhite", "address": "reader_123@kindle.com"}
→ 201 Created  {"id": "tgt_pw", "max_bytes": 45000000,
                "sender": "books@blog2epub.example", ...}   (add this sender on Amazon)

POST /v1/books/bk_2m/schedules
{"frequency": "weekly", "weekday": 0, "time": "07:00",
 "targets": ["tgt_pw"], "content": "new_posts", "skip_if_empty": true}
→ 201 Created  {"id": "sch_w1", "next_run_at": "2026-09-28T06:00:00Z", ...}
```

Every Monday at 07:00 London time, the posts those three blogs gained since the last delivery
arrive on the Paperwhite as one digest.

A probe with bleed on an `auto` blog is not a dead end: the UI says "chapters from this site may
include related posts; ask for a curated recipe", which files a recipe proposal the maintainer
works through with `/add-blog`.

## 6. Jobs, scheduling and delivery

### Job types

| Job | Unit | Concurrency rule | Library call |
| --- | --- | --- | --- |
| `probe` | URL | ≤ 2 per user at once; 1 per host globally | probe functions moved from `scripts/probe_blog.py` into `blog2epub.probe` |
| `sync` | blog | **1 per blog** (it is the single writer of that blog's cache); **1 per host** (advisory lock on the host name) | `sync_blog` |
| `build` | book × issue | many in parallel; reads caches only | `build_book` |
| `deliver` | build × target | per provider rate limit | new `blog2epub.deliver` |

### Keeping caches fresh without users driving the crawl

Users never cause a sync directly; they declare what they want and the scheduler decides when a
blog is fetched. Each blog has a freshness target set by demand — hourly checks are pointless for
a blog that posts monthly:

- blogs in any book due for delivery in the next few hours: synced shortly before the earliest one
- blogs with subscribers: daily
- blogs nobody reads any more: paused, not deleted

A build job first asks "is every blog in this book fresh enough for this delivery?" and, if not,
waits on the sync already queued for it rather than starting its own. This is `_sync_blogs`'
per-host lock lifted into Postgres, plus de-duplication: a hundred Monday-morning digests that
include Kong wait on one Kong sync.

### A scheduled delivery

```mermaid
sequenceDiagram
  participant S as Scheduler
  participant Q as Queue
  participant W as Worker
  participant C as Blog cache
  participant K as Send to Kindle

  S->>Q: schedule sch_w1 (book bk_2m) due at 07:00 Europe/London
  Q->>W: build(bk_2m, posts first seen after last_delivered_through)
  W->>C: blogs fresh? (last_sync vs deadline)
  alt stale
    W->>Q: await sync(blg_kong, blg_tyk, …) (dedupe with queued syncs)
    Q->>W: sync each blog under its host lock
    W->>C: new posts + images (shared by every user)
  end
  W->>W: build_book(max_book_bytes = target limit)
  alt no new posts since last delivery and skip_if_empty
    W-->>Q: build skipped
  else
    W->>Q: deliver(build, kindle target)
    Q->>W: deliver
    W->>K: email, one volume per message
    W-->>Q: delivered (message ids)
  end
```

### Delivery targets and size limits

| Target | How | Size limit | Consequence |
| --- | --- | --- | --- |
| Kindle email | Email from `books@<our domain>`, which the user adds to Amazon's *Approved Personal Document E-mail List* | 50 MB per message | Build with `max_book_bytes: 45MB` for this target. The existing splitter already cuts volumes by size, so a large archive becomes several messages rather than a bounce. |
| Download / OPDS | Signed URL | none that matters | Standard split (by year, ≤ 200 MB) or collector's edition. |
| Other email (Kobo via Dropbox, PocketBook, …) | Email | provider-dependent (≈ 25 MB) | Same mechanism, different `max_bytes`. |
| Webhook | POST with signed URL | none | For people wiring it into their own automation. |

The per-target limit is the one new idea the build needs: `max_book_bytes` stops being only a
book option and becomes `min(book, target)`. Since `plan_volumes` already honours it, no
packaging change is required.

**Digest semantics.** A `new_posts` schedule delivers every post of the book's blogs that the
service **first saw** after the schedule's `last_delivered_through` mark, then moves the mark to
the newest post it sent. It keys on first-seen time, not publication date, because a post can be
backdated or reach the cache a day late; keyed on its date it would fall between two digests and
never be sent. Consequences:

- a daily, weekly and monthly schedule on one book each get every post exactly once;
- a missed or paused run catches up at the next one rather than dropping a week;
- a new schedule starts from its creation (or from a `start_from` date the user picks, to get
  the last month as a first issue);
- `skip_if_empty: true` sends nothing when nothing is new, and the mark does not move;
- the mark only moves when the delivery succeeds, so a bounced email is retried with the same
  posts plus anything newer.

A `window` schedule builds the book with its own `since`/`until` every time, which is how today's
monthly API Management Digest (`since: 1m`) and whole-archive books behave. For a whole archive
sent by email, the size limit splits it into several messages; the UI warns before scheduling
one that would need more than a handful.

**Timezones.** `next_run_at` is stored in UTC and recomputed from the local time after each run,
so a 07:00 delivery stays at 07:00 across daylight-saving changes. Monthly `day` is capped at 28
so every month has one.

**Who pays for a sync.** Scheduling is per user; fetching is not. The scheduler groups the next
few hours of due schedules by blog, so a blog in two hundred users' Monday digests is synced once
before 06:00 and the two hundred builds read the same cache (R5).

## 7. Changes to the library

The library is in good shape for this: sources, sync and build are functions of `(config, client,
store)` and nothing outside `cli.py` prints. The changes are about **inputs, outputs and shared
state**, and each lands on its own with tests, before any API code exists.

| # | Change | Where | Why |
| --- | --- | --- | --- |
| 1 | `settings_from_mapping(raw, base=…)`; `load_config` becomes a thin wrapper over it | `config.py` | The API holds configs in the database, not in a file. All validation stays in `BlogConfig`/`BookConfig.__post_init__`, so the API cannot drift from the CLI. |
| 2 | Pydantic DTOs mirroring `BlogConfig`/`BookConfig`, with a test asserting the field sets match (as `_BLOG_KEYS` already does for YAML) | `api/schemas.py`, `tests/test_api_schema.py` | The OpenAPI schema and the web forms come from these; the parity test stops a new config key from being forgotten. |
| 3 | A progress callback: `sync_blog(…, on_event=)` and `build_book(…, on_event=)` emitting structured events | `sync.py`, `epub.py` | SSE progress. The CLI passes a callback that logs as today. |
| 4 | Move `_sync_blogs` and its per-host lock into the library behind a `LockProvider` (thread locks for the CLI, Postgres advisory locks for the service) | `cli.py` → `sync.py` | One implementation of the politeness rule. |
| 5 | `BlogStore` behind a small protocol with the current filesystem class as the default; an object-storage implementation that keeps a local read-through cache, because `prepare` wants file `Path`s for images | `store.py` | Workers on more than one machine. Single-machine installs keep using the filesystem class unchanged. |
| 6 | `build_book` takes the list of files it may replace, instead of globbing the output directory | `epub.py` (`book_outputs`) | In a shared output store, cleanup by glob could delete another user's files. `book_outputs`' exact-id matching is right for one user and not enough for many. |
| 7 | Move `_build`'s write of `index["builds"]` out of the blog cache | `cli.py` | Many users' builds would contend on one blog's `index.json`; build history belongs to the Build table. The CLI keeps writing it for `status`. |
| 8 | `probe_blog.py`'s logic becomes `blog2epub.probe` returning a dataclass; the script prints it | `scripts/` → `src/` | `POST /probes` needs structured results, not stdout. |
| 9 | Guarded HTTP: an `HttpClient` option that refuses private, loopback and link-local addresses, re-checked on every redirect, and a `robots.txt` check | `http.py` | SSRF (see §8). Off for the CLI, on in the service. |
| 10 | Optimised-image cache keyed by `(url, max_width, quality)` | `images.py` | A digest built for many users re-encodes each image once. |
| 11 | `build_book(…, keys=)`: build from an explicit set of post keys, in addition to `since`/`until`/`max_posts` | `epub.py` (`select_entries`) | `new_posts` schedules pick posts by first-seen time, which the service knows and the book config does not. |
| 12 | Record `first_seen` in the cache index when a post is first stored, and keep it on re-fetch | `store.py` (`put_post`) | The digest mark ([§6](#6-jobs-scheduling-and-delivery)). `fetched_at` is overwritten on every re-fetch, so it cannot serve. |

None of this changes what a book looks like; the epubcheck suite is the guard.

## 8. Security and abuse

A service that fetches URLs its users type in, and renders HTML it fetched, has problems the CLI
does not.

- **SSRF.** Every user-supplied URL — blog, feed, sitemap, and every image a post references — is
  fetched from inside our network. The guarded client (change 9) resolves the host, refuses
  private/loopback/link-local/metadata ranges, pins the connection to the address it checked, and
  re-checks every redirect hop. Only `http` and `https`.
- **User-supplied rules.** `include`/`exclude`/`title_strip` are Python regexes and `keep`/`remove`
  are CSS selectors, run over untrusted input. On `auto` blogs users set only `include`/`exclude`,
  checked with a length cap and a match timeout (the `regex` module supports one); selectors and
  other rules are curated-only. Recipe proposals are text a maintainer reads, never code the
  service runs.
- **Cover templates and `extra_css` are curated-only.** A cover template is HTML executed in
  Chromium; a user-supplied one is an SSRF and code-execution vector. Users choose from the
  templates in `covers/` and a generic one that takes a colour pair (the probe's brand colours).
- **Untrusted HTML into EPUB.** Already handled: `clean.clean_html` is the single choke point and
  strips scripts, handlers and foreign markup. It stays the only path.
- **Email abuse.** Delivery only to a verified address, or to `@kindle.com` (Amazon drops mail from
  senders the owner has not approved, so an unverified Kindle address cannot be spammed). Per-user
  daily send caps. SPF, DKIM and DMARC on the sending domain, or Amazon will junk it.
- **Accounts.** Passwords hashed with argon2id; sign-in, sign-up, magic-link and reset endpoints
  rate-limited per IP and per address, with the same response whether or not an address exists.
  Verification and reset tokens are single-use, short-lived and stored hashed. Session cookies
  are `HttpOnly`, `Secure`, `SameSite=Lax`, with CSRF tokens on unsafe methods. Every owned row is
  read through a query scoped by `user_id`, with a test per endpoint that another user's id
  answers 404, not 403.
- **Bounces.** A Kindle address that hard-bounces pauses its schedules and tells the user by email,
  rather than retrying into a reputation problem for every user sharing the sender.
- **Quotas** per user: blogs added per day, probes per hour, builds per day, posts per book
  (a 2,505-post archive is fine monthly, not hourly), storage retained.
- **Copyright.** Books stay private; no public link to a user's build, signed URLs expire; the
  opt-out list stops syncing a host and deletes its cache; attribution is in every chapter.

## 9. The web app

A static SPA, built only against the generated client. Screens, and the API calls behind them:

| Screen | Shows | Calls |
| --- | --- | --- |
| **Sign up / sign in** | Email and password or magic link; verification; password reset | `/auth/*` |
| **Onboarding** | Timezone, then "add your Kindle": the address, the sender to approve on Amazon with a link to the right Amazon page, and a test book | `PATCH /me`, `POST /delivery-targets`, `…/test` |
| **Library** (home) | Your books, each with its next delivery, last issue, volume files to download; the curated catalogue below | `GET /books`, `GET /schedules`, `GET /books/{id}/builds?limit=1`, `GET /catalogue` |
| **Add a blog** | Paste a URL → live probe progress → the verdict in plain words: *"901 posts via the sitemap, 2008–2026; chapters look clean"* or *"feed only: the latest 10 posts"*; three sample chapters rendered as they would read | `POST /probes`, SSE, `GET /probes/{id}`, `POST /blogs` |
| **Blog** | Post list by year and month, search, a chapter preview, tier badge, "propose a better recipe" | `GET /blogs/{id}`, `GET /blogs/{id}/posts`, `…/posts/{key}` |
| **Book editor** | Pick blogs; *Archive* or *Digest* preset; window (`1w`, `1m`, dates); order; grouping; split; cover; a live preview of volumes and TOC as options change | `POST/PATCH /books`, `GET /books/{id}/preview` |
| **Schedules** | Per book: add daily / weekly / monthly, local time, which Kindle(s), "new posts since last time" or "the whole window", skip when empty, pause; "send now" | `POST /books/{id}/schedules`, `PATCH/DELETE /schedules/{id}`, `POST /schedules/{id}/run` |
| **Issues** | Every build: volumes, sizes, delivery status per target, the job log when something failed | `GET /books/{id}/builds`, `GET /deliveries`, `GET /jobs/{id}` |
| **Settings** | Profile, email, password, timezone, notifications; Kindle addresses and other targets; signed-in devices; API tokens; OPDS link; export; delete account | `/me`, `/me/*`, `/delivery-targets`, `/tokens`, `/config.yaml` |

The book editor's form is generated from the JSON Schema of the book DTO, with a small UI map
for labels and grouping, so a new `BookConfig` option appears in the web app when it appears in
the contract. Two presets hide most of it: **Archive** (`order: desc`, `group_by: year-month`,
`split: year`) and **Digest** (`since: 1m`, `group_by: blog`, `split: size`), matching what the
shipped books use.

## 10. Deployment

**Hosted, multi-user** (the target): API behind a CDN that also serves the SPA; workers split
into two pools (`sync`/`probe`, which is network-bound and politeness-limited, and
`build`/`deliver`, which is CPU-bound and autoscaled on queue depth); Postgres; object storage for
the one shared cache and the build files; a transactional email provider (SES, Postmark) with
SPF/DKIM/DMARC on the sending domain and bounce webhooks. `blogs.yaml` is imported as the curated
tier at first start, so today's nine books and their blogs are in the catalogue on day one.

**Development and small installs:** the same images under `docker compose up` → `api`, `worker`
(with Chromium), `postgres`, `mailpit`; filesystem storage on a volume. It is still multi-user;
it just runs on one machine. The GitHub Actions release pipeline keeps publishing the curated
shelf and can later read its cache from the service's store instead of `actions/cache`.

## 11. Phases

Each phase ships something usable and leaves `make check` and epubcheck green. Multi-user is not
a late phase: accounts and `user_id` scoping are in the first schema, because retrofitting them
means rewriting every query.

| Phase | Delivers | Main work |
| --- | --- | --- |
| **0. Library seams** | No visible change | Changes 1, 3, 4, 6, 7, 8, 11, 12 from §7, with tests |
| **1. Multi-user API** | Sign-up to download over the API alone: accounts, blogs via probe into the shared cache, single and combined books, builds and downloads; `blogs.yaml` imported as the curated tier | FastAPI app, auth (§5.1), Postgres schema + migrations, job queue, SSE, guarded HTTP (change 9), quotas, OpenAPI published in CI with a breaking-change check |
| **2. Scheduled Kindle delivery** | Daily, weekly and monthly digests to Kindle by email, per user and per book | Scheduler, `new_posts` marks, delivery targets and test send, per-target size limits, freshness planner, email provider with bounce handling |
| **3. Web app** | Everything above in a browser: sign-up, onboarding, library, add a blog, book editor with preview, schedules, settings | SPA, generated client |
| **4. Scale and curation** | More users on more machines | Object storage (change 5), optimised-image cache (change 10), recipe proposals and admin, opt-out list, OPDS, webhooks |

The API comes before the web app on purpose: phases 1 and 2 are usable from `curl` and the
generated client, and the web app is then built against a contract that has already carried real
traffic.

## 12. Open questions

Settled: hosted and multi-user; one shared cache; single and combined books; per-user
daily/weekly/monthly Kindle delivery by email; the full account lifecycle in the API.

1. **Recipe contributions.** Should an accepted recipe proposal become a PR against `blogs.yaml`
   (the repo stays the source of truth for curated recipes) or live only in the database?
   Recommendation: the repo, so curated recipes keep their review, comments and history.
2. **Can any user add any blog?** Every blog a user adds is fetched into the shared cache and
   costs a sync for as long as someone reads it. Options: anyone can add (with quotas and the
   robots/opt-out checks), or new blogs wait for an admin's approval before their first full
   sync. Recommendation: anyone can add, but the first sync of an `auto` blog is capped at its
   most recent 200 posts until an admin promotes it.
3. **How much of a blog does a book get by default?** A 2,500-post archive is ~1 GB of images.
   Default a new single-source book to the last year, with "whole archive" as an explicit choice?
4. **Cost and payment.** Builds, storage and email are the cost. A free tier (e.g. 3 books, weekly
   at most) with a paid tier for daily schedules, more books and collector's editions, or free
   with fixed quotas?
5. **Sign-in methods.** Email + password and magic link are in the design; is Google/GitHub sign-in
   wanted at launch?
