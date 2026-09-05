# Security

blog2epub fetches HTML from third-party websites and turns it into EPUB files. The main risks are
malicious markup in fetched pages and the files that end up on your reader.

**What the code does about it**

- Scripts, styles, forms, iframes, objects, event handlers and unknown elements are removed
  before anything is written into a book (`src/blog2epub/clean.py`).
- Hrefs are validated; `javascript:` and `data:` links are dropped.
- Images are size-limited, sniffed by content, and stored under a hash of their URL.
- Nothing fetched is ever executed; the tool only parses.

**Reporting**

If you find a way for fetched content to escape the cleaner, or any other security issue,
please open a private security advisory on GitHub (Security → Advisories → New draft) rather
than a public issue. Expect an acknowledgement within a week.

**Scope notes**

- The GitHub Actions workflows only need `contents: write` to publish releases; they use no
  third-party secrets.
- Cover rendering runs a headless Chromium on HTML that is part of this repository, not on
  fetched content.
