from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class HttpClient:
    """A small polite HTTP client: one User-Agent, retries with backoff, a delay between requests."""

    def __init__(self, user_agent: str, delay: float = 0.5, timeout: int = 30) -> None:
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Language": "en"})
        retry = Retry(
            total=4,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._last_request = 0.0
        self.requests_made = 0

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        wait = self._last_request + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        stream: bool = False,
        allow_404: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        self._throttle()
        log.debug("GET %s %s", url, params or "")
        resp = self.session.get(url, params=params, timeout=self.timeout, stream=stream, **kwargs)
        self._last_request = time.monotonic()
        self.requests_made += 1
        if allow_404 and resp.status_code == 404:
            return resp
        resp.raise_for_status()
        return resp

    def get_text(self, url: str, **kwargs: Any) -> str:
        resp = self.get(url, **kwargs)
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text

    def get_text_tolerant(self, url: str, **kwargs: Any) -> tuple[str, str]:
        """GET text, retrying the other trailing-slash form on 404.

        Sitemaps and the servers behind them disagree about trailing slashes often enough to
        matter: Gravitee, for one, lists `/blog/slug/` but serves only `/blog/slug`.
        Returns (text, the URL that actually worked).
        """
        try:
            return self.get_text(url, **kwargs), url
        except requests.HTTPError as exc:
            resp = getattr(exc, "response", None)
            alt = url.rstrip("/") if url.endswith("/") else url + "/"
            if resp is None or resp.status_code != 404 or alt == url:
                raise
            log.debug("404 on %s, trying %s", url, alt)
            return self.get_text(alt, **kwargs), alt

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.get(url, **kwargs).json()

    def try_get(self, url: str, **kwargs: Any) -> requests.Response | None:
        """GET that returns None instead of raising, for probing optional endpoints."""
        try:
            resp = self.get(url, allow_404=True, **kwargs)
        except requests.RequestException as exc:
            log.debug("probe %s failed: %s", url, exc)
            return None
        if resp.status_code != 200:
            return None
        return resp
