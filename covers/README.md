# covers/

Cover images referenced from `blogs.yaml` (`cover: covers/<name>.jpg`), plus the HTML
templates that generate them.

## tyk.jpg

A magazine-style cover for the Tyk Blog archive in Tyk's brand palette, rendered from
`tyk.html` by `scripts/render_cover.py`. The template is a `string.Template`: the render
script fills `$count`, `$first_year`, `$last_year`, `$issue`, `$url` and three cover lines
(`$kicker1`/`$title1` ...) from the newest cached posts, so the cover lines change as the
blog does.

```bash
make cover                       # or:
.venv/bin/pip install -e ".[covers]"
.venv/bin/python scripts/render_cover.py --blog tyk --template covers/tyk.html --out covers/tyk.jpg
```

Rendering uses Playwright's Chromium (`playwright install chromium`, or point `CHROMIUM_PATH`
at an existing binary). Output is 1600×2133 (3:4) JPEG, which suits Kobo, Kindle and Apple Books.

## fonts/

Bebas Neue, Barlow and Barlow Condensed (latin subsets), bundled so covers render offline and
identically everywhere. All three are published under the SIL Open Font License 1.1.

## Your own covers

Drop a JPG or PNG here and reference it from `blogs.yaml`. A 1200×1600 or larger portrait image
(3:4) fits most readers. Copy `tyk.html` as a starting point for another generated cover; the
placeholders work for any blog id.
