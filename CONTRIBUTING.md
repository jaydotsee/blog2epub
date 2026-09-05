# Contributing

Thanks for taking an interest. blog2epub is small on purpose: a handful of modules, no framework,
and a test suite that runs offline in a few seconds.

## Setting up

```bash
git clone https://github.com/jaydotsee/blog2epub.git
cd blog2epub
make setup          # venv + editable install with the dev tools
make check          # ruff, mypy, pytest
```

Java is only needed for `make epubcheck` and the optional validator test
(`EPUBCHECK_JAR=... make test`).

## Where things live

| Area | Module | Tests |
| --- | --- | --- |
| Config schema and validation | `src/blog2epub/config.py` | `tests/test_config.py` |
| Sources (WordPress, feed, sitemap) | `src/blog2epub/sources/` | `tests/test_sources.py`, `tests/test_network.py` |
| HTML → XHTML cleaning, site rules | `src/blog2epub/clean.py` | `tests/test_clean.py`, `tests/test_rules.py` |
| EPUB packaging and page rendering | `src/blog2epub/epub.py` | `tests/test_epub.py`, `tests/test_epubcheck.py` |
| Cache and image downloads | `src/blog2epub/store.py`, `images.py` | `tests/test_network.py` |
| CLI | `src/blog2epub/cli.py` | `tests/test_network.py` |

## Adding a source

Subclass `Source` in `src/blog2epub/sources/`, implement `detect`, `discover`, `fetch` and
`describe`, and register it in `sources/__init__.py`. Drive it in tests with the `FakeClient` from
`tests/test_sources.py` so the suite stays offline.

## Fixing an epubcheck complaint

Every book must pass epubcheck with zero errors and zero warnings. Fix the cause in
`clean.py` (for post markup) or `epub.py` (for packaging) and add a regression test with the
offending markup. `make epubcheck` validates everything in `output/`.

## Pull requests

- One topic per pull request, with tests.
- `make check` must pass; CI runs the same plus epubcheck on Python 3.10 and 3.12.
- Keep `blogs.yaml` examples real: if you add a blog, make sure `blog2epub detect` finds it.
- Note user-visible changes in `CHANGELOG.md` under *Unreleased*.

## Reporting a broken blog

Open a *Blog not working* issue with the URL and the output of
`blog2epub detect <url>` and, if it synced, `blog2epub -v sync <id>`.
