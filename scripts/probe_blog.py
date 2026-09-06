#!/usr/bin/env python3
"""Work out the recipe for a new blog: source, URL shape, extraction rules, brand colours.

    scripts/probe_blog.py https://konghq.com/blog
    scripts/probe_blog.py https://konghq.com/blog --keep "[class*='TableOfContents_body']" \
        --remove "[class*='Card_card']" --remove "[class*='Article_cta']"

Runs the checks that decide a `blogs.yaml` entry and prints a ready-to-paste draft:

1. every source that answers (WordPress API, feed, sitemap) with the post count each offers
2. the shape of the post URLs, and an `include` regex that keeps posts and drops index pages
3. a sample of real posts extracted through the actual pipeline: title, date, author,
   featured image, body length
4. **bleed**: whether other posts' titles leak into a body (modern sites prerender related
   cards, which readability mistakes for the story)
5. candidate `remove` selectors, ranked by how much text they hold
6. the site's most-used brand colours, for the cover template

Nothing is written; the draft entry is printed for you to paste and adjust.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lxml import html as lx  # noqa: E402

from blog2epub.clean import clean_html, text_of  # noqa: E402
from blog2epub.config import BlogConfig, load_config  # noqa: E402
from blog2epub.extract import extract_article  # noqa: E402
from blog2epub.http import HttpClient  # noqa: E402
from blog2epub.sources import SOURCES  # noqa: E402

# Class-name fragments that almost always mark furniture rather than the story.
CLUTTER = (
    "share",
    "social",
    "newsletter",
    "subscribe",
    "signup",
    "related",
    "moreon",
    "more-on",
    "cta",
    "breadcrumb",
    "termlist",
    "tag-list",
    "taglist",
    "author",
    "byline",
    "comment",
    "sidebar",
    "cookie",
    "banner",
    "promo",
    "popup",
    "modal",
    "card",
    "recommend",
    "footer",
    "nav",
    "menu",
    "toc-nav",
    "pagination",
    "prevnext",
    "sponsor",
    "advert",
)
UA = "blog2epub-probe/0.2 (+https://github.com/jaydotsee/blog2epub)"


def h(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def detect_sources(url: str, client: HttpClient) -> dict[str, tuple[object, list]]:
    """Try every source against the URL and report how many posts each one lists."""
    found: dict[str, tuple[object, list]] = {}
    for name, cls in SOURCES.items():
        blog = BlogConfig(id="probe", url=url, source=name)
        try:
            src = cls.detect(blog, client)
        except Exception as exc:  # a probe must never die on one bad source
            print(f"  {name:10} detection failed: {exc}")
            continue
        if src is None:
            print(f"  {name:10} not available")
            continue
        try:
            refs = src.discover()
        except Exception as exc:
            print(f"  {name:10} {src.describe()}: listing failed: {exc}")
            continue
        print(f"  {name:10} {src.describe()}\n             -> {len(refs)} posts")
        found[name] = (src, refs)
    return found


def url_shapes(refs: list, blog_url: str) -> str:
    """Report the path shapes of the listed URLs and suggest an `include` regex."""
    root = urlsplit(blog_url)
    depths = Counter()
    prefixes = Counter()
    for r in refs:
        path = urlsplit(r.url).path.strip("/")
        parts = path.split("/") if path else []
        depths[len(parts)] += 1
        prefixes["/".join(parts[:2])] += 1
    print(f"  path depth (segments after the host): {dict(sorted(depths.items()))}")
    print("  most common prefixes:")
    for p, n in prefixes.most_common(8):
        print(f"    {n:5}  /{p}")
    host = re.escape(root.netloc)
    base = root.path.strip("/")
    deepest = max(depths, key=lambda d: depths[d]) if depths else 2
    own = len(base.split("/")) if base else 0
    tail = "/".join(["[^/]+"] * max(1, deepest - own))
    suggested = f"^https://{host}/{base + '/' if base else ''}{tail}"
    if len(depths) > 1:
        print(
            f"  NOTE: mixed depths — index pages are probably in the list; the regex below "
            f"keeps depth {deepest} only"
        )
    print(f'\n  suggested include:  "{suggested}"')
    return suggested


def clutter_candidates(page: str, url: str) -> None:
    """Rank elements that look like furniture, so `remove` selectors can be chosen."""
    doc = lx.fromstring(page)
    rows: dict[str, tuple[int, int]] = {}
    for el in doc.iter():
        cls = (el.get("class") or "").strip()
        if not cls:
            continue
        low = cls.lower()
        for frag in CLUTTER:
            if frag in low:
                # CSS-module class names carry a build hash (Article_cta__EpjTW): match the
                # stable prefix so the rule survives the site's next deploy.
                token = next((c for c in cls.split() if frag in c.lower()), cls.split()[0])
                stem = re.sub(r"__[A-Za-z0-9_-]+$", "", token)
                sel = f"[class*='{stem}']" if stem != token else f".{token}"
                chars = len(" ".join(el.text_content().split()))
                n, tot = rows.get(sel, (0, 0))
                rows[sel] = (n + 1, tot + chars)
                break
    if not rows:
        print("  no obvious furniture found")
        return
    print(f"  {'selector':52} {'n':>4} {'chars':>7}")
    for sel, (n, chars) in sorted(rows.items(), key=lambda kv: -kv[1][1])[:14]:
        print(f"  {sel:52} {n:>4} {chars:>7}")


def keep_candidates(page: str) -> None:
    """Containers that appear exactly once and hold most of the text are `keep` candidates."""
    doc = lx.fromstring(page)
    main = doc.cssselect("main") or doc.cssselect("body")
    main_chars = len(" ".join(main[0].text_content().split())) if main else 0
    seen: dict[str, list[int]] = {}
    for el in doc.iter():
        cls = (el.get("class") or "").strip()
        if not cls or el.tag in ("html", "body", "script", "style"):
            continue
        token = cls.split()[0]
        stem = re.sub(r"__[A-Za-z0-9_-]+$", "", token)
        sel = f"[class*='{stem}']" if stem != token else f".{token}"
        seen.setdefault(sel, []).append(len(" ".join(el.text_content().split())))
    print(f"  main holds {main_chars} chars; a good `keep` matches once and holds 25-90% of it")
    print(f"  {'selector':52} {'n':>4} {'chars':>7}  {'share':>6}")
    rows = [(s, v) for s, v in seen.items() if len(v) == 1 and main_chars and 0.2 < v[0] / main_chars < 0.95]
    for sel, v in sorted(rows, key=lambda kv: -kv[1][0])[:10]:
        print(f"  {sel:52} {len(v):>4} {v[0]:>7}  {v[0] / main_chars:>5.0%}")


def brand_colours(client: HttpClient, url: str) -> list[str]:
    """The colours a site uses most are, in practice, its brand palette."""
    counts: Counter[str] = Counter()
    try:
        page = client.get_text(url)
    except Exception as exc:
        print(f"  could not fetch the page: {exc}")
        return []
    counts.update(c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}\b", page))
    for css in re.findall(r'href="([^"]+\.css[^"]*)"', page)[:4]:
        link = css if css.startswith("http") else f"{urlsplit(url).scheme}://{urlsplit(url).netloc}{css}"
        try:
            counts.update(c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}\b", client.get_text(link)))
        except Exception:
            continue
    top = [c for c, _ in counts.most_common(10)]
    for c, n in counts.most_common(10):
        print(f"  {c}  x{n}")
    return top


def sample_posts(src, refs: list, client: HttpClient, args, all_titles: set[str]) -> None:
    """Run real posts through the pipeline and look for other posts leaking into the body."""
    step = max(1, len(refs) // max(1, args.samples))
    picks = refs[::step][: args.samples]
    worst = 0
    for ref in picks:
        try:
            page, ref.url = client.get_text_tolerant(ref.url)
        except Exception as exc:
            print(f"  {ref.url}: fetch failed: {exc}")
            continue
        art = extract_article(page, ref.url, keep=args.keep or None, remove=args.remove or None)
        if not art["html"]:
            print(f"  {ref.url}: NO BODY EXTRACTED")
            continue
        body, imgs = clean_html(
            art["html"],
            ref.url,
            image_resolver=lambda u: "x",
            keep=args.keep or None,
            remove=args.remove or None,
        )
        t = text_of(body)
        mine = (art["title"] or ref.title or "").strip()
        bleed = [o for o in all_titles if o and o != mine and len(o) > 25 and o in t]
        worst = max(worst, len(bleed))
        print(f"\n  {ref.url}")
        print(f"    title    {art['title'][:66]!r}")
        print(f"    date     {str(art['date'])[:19] or '(none)':20} author {art['author'] or '(none)'}")
        print(
            f"    featured {'yes' if art['featured_image'] else 'no':20} images {len(imgs)}  chars {len(t)}"
        )
        print(f"    head     {t[:96]}")
        print(f"    tail     {t[-96:]}")
        if bleed:
            print(f"    !! BLEED: {len(bleed)} other post title(s) in this body, e.g. {bleed[0][:60]!r}")
    if worst:
        print("\n  >> Other posts are leaking in. Add a `keep` selector for the article body")
        print("     (see the keep candidates above) and re-run with --keep.")
    else:
        print("\n  >> No bleed detected in the sample.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", help="the blog's root URL, e.g. https://konghq.com/blog")
    ap.add_argument("--id", help="blog id for the draft entry (default: derived from the host)")
    ap.add_argument(
        "--from-config",
        action="store_true",
        help="probe the blog that --id names in blogs.yaml using its configured source, include, "
        "keep and remove, instead of auto-detecting. Use this to iterate on an entry.",
    )
    ap.add_argument("-c", "--config", default=str(ROOT / "blogs.yaml"), help="path to blogs.yaml")
    ap.add_argument("--no-draft", action="store_true", help="skip the draft entry and brand colours")
    ap.add_argument("--samples", type=int, default=5, help="how many posts to extract (default 5)")
    ap.add_argument("--keep", action="append", default=[], help="candidate keep selector (repeatable)")
    ap.add_argument("--remove", action="append", default=[], help="candidate remove selector (repeatable)")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests (be polite)")
    ap.add_argument(
        "--user-agent",
        default=UA,
        help="identify as something else; some edges 403 a UA that carries a contact URL",
    )
    args = ap.parse_args(argv)

    client = HttpClient(args.user_agent, delay=args.delay, timeout=30)

    if args.from_config:
        # Iterate on an entry that is already written: use its source and rules, not detection.
        if not args.id:
            ap.error("--from-config needs --id <blog id from blogs.yaml>")
        blog = load_config(args.config).blog(args.id)
        args.url, blog_id = blog.url, blog.id
        args.keep = args.keep or blog.keep
        args.remove = args.remove or blog.remove
        h(f"1. Configured source for {blog.id!r}")
        src = SOURCES[blog.source].detect(blog, client) if blog.source != "auto" else None
        if src is None:
            print(f"  the configured source {blog.source!r} did not answer")
            return 2
        refs = src.discover()
        print(f"  {src.describe()}\n  -> {len(refs)} posts after include/exclude and since/until")
    else:
        if not args.url:
            ap.error("give a URL, or --from-config --id <blog id>")
        blog_id = args.id or urlsplit(args.url).netloc.lower().removeprefix("www.").split(".")[0]
        h("1. Sources that answer")
        found = detect_sources(args.url, client)
        if not found:
            print("\nNo source available. Try the feed or sitemap URL explicitly in blogs.yaml.")
            return 2
        # Prefer the richest source; on a tie prefer the one listing the most posts.
        order = {"wordpress": 3, "feed": 2, "sitemap": 1}
        best = max(found, key=lambda n: (len(found[n][1]), order[n]))
        most = max(found, key=lambda n: len(found[n][1]))
        if most != best:
            print(
                f"\n  NOTE: {best} is the richest source but {most} lists more posts "
                f"({len(found[most][1])} vs {len(found[best][1])})."
            )
        src, refs = found[most]
        print(f"\n  using: {most} ({len(refs)} posts) for the rest of the probe")

    h("2. URL shape")
    include = url_shapes(refs, args.url)

    # Sitemaps carry stale URLs; walk until one actually fetches.
    page = sample_url = ""
    for ref in refs[:8]:
        try:
            page, sample_url = client.get_text_tolerant(ref.url)
            break
        except Exception as exc:
            print(f"  (skipping unreadable {ref.url}: {exc})")
    if not page:
        print("could not fetch any sample page")
        return 2

    h("3. `keep` candidates (containers that appear once and hold the story)")
    keep_candidates(page)

    h("4. `remove` candidates (furniture, ranked by the text it holds)")
    clutter_candidates(page, sample_url)

    h(
        f"5. Extraction on {args.samples} real posts"
        + (f" with keep={args.keep} remove={args.remove}" if args.keep or args.remove else " (no rules yet)")
    )
    sample_posts(src, refs, client, args, {(r.title or "").strip() for r in refs})

    if args.no_draft or args.from_config:
        print(f"\n  requests made: {client.requests_made}")
        return 0

    h("6. Brand colours (most-used first) for the cover template")
    colours = brand_colours(client, args.url)

    h("7. Draft blogs.yaml entry")
    keep_yaml = "".join(f'\n      - "{k}"' for k in args.keep)
    rm_yaml = "".join(f'\n      - "{r}"' for r in args.remove)
    src_line = {
        "sitemap": f"    source: sitemap\n    sitemap: {{ url: {getattr(src, 'sitemap_url', '')} }}",
        "feed": f"    source: feed\n    feed: {{ url: {getattr(src, 'feed_url', '')} }}",
        "wordpress": f"    source: wordpress\n    wordpress: {{ api: {getattr(src, 'api_base', '')} }}",
    }[most]
    print(f"""  - id: {blog_id}
    title: "..."
    url: {args.url}
    author: "..."
    description: "..."
{src_line}
    include:
      - "{include}"{
        f'''
    keep:{keep_yaml}'''
        if args.keep
        else ""
    }{
        f'''
    remove:{rm_yaml}'''
        if args.remove
        else ""
    }
    order: desc
    group_by: year-month
    cover: covers/{blog_id}.jpg""")
    print(f"\n  requests made: {client.requests_made}")
    if colours:
        print(f"  cover palette: {', '.join(colours[:4])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
