"""Wayback Machine CDX API client.

Prefix queries with resume-key pagination, retry/backoff, and a polite
global throttle. The CDX index is the discovery layer: it tells us every
capture the archive holds for a URL pattern without fetching any pages.
"""

import time

import requests

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
USER_AGENT = (
    "tweet-recovery/1.0 (archival research tool; contact: repo operator)"
)
PAGE_LIMIT = 15000
RETRY_STATUSES = {429, 500, 502, 503, 504}


class CdxClient:
    def __init__(self, throttle: float = 1.5, max_retries: int = 5):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.throttle = throttle
        self.max_retries = max_retries
        self._last_request = 0.0

    def query(self, url_pattern: str, extra_params: dict | None = None):
        """Yield capture dicts (timestamp, original, statuscode, digest)
        for a CDX prefix query, following resume keys until exhausted."""
        resume_key = None
        while True:
            params = {
                "url": url_pattern,
                "output": "json",
                "fl": "timestamp,original,statuscode,digest",
                "collapse": "digest",
                "limit": PAGE_LIMIT,
                "showResumeKey": "true",
            }
            if extra_params:
                # List values become repeated params (CDX's filter= is repeatable).
                params.update(extra_params)
            if resume_key:
                params["resumeKey"] = resume_key
            rows = self._get_json(params)
            if not rows:
                return

            header, body = rows[0], rows[1:]
            # Resume key arrives as: ...data rows..., [], ["<key>"]
            resume_key = None
            while body and not body[-1]:
                body.pop()
            if body and len(body[-1]) == 1:
                resume_key = body.pop()[0]
                while body and not body[-1]:
                    body.pop()

            for row in body:
                if len(row) == len(header):
                    yield dict(zip(header, row))

            if not resume_key:
                return

    def _get_json(self, params):
        for attempt in range(self.max_retries):
            self._wait_turn()
            try:
                resp = self.session.get(CDX_ENDPOINT, params=params, timeout=60)
            except requests.RequestException:
                self._backoff(attempt, None)
                continue
            if resp.status_code == 200:
                if not resp.text.strip():
                    return []
                return resp.json()
            if resp.status_code in RETRY_STATUSES:
                self._backoff(attempt, resp.headers.get("Retry-After"))
                continue
            resp.raise_for_status()
        raise RuntimeError(f"CDX query failed after {self.max_retries} retries: {params['url']}")

    def _wait_turn(self):
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.throttle:
            time.sleep(self.throttle - elapsed)
        self._last_request = time.monotonic()

    def _backoff(self, attempt, retry_after):
        try:
            delay = float(retry_after)
        except (TypeError, ValueError):
            delay = min(2 ** attempt * 3, 60)
        time.sleep(delay)
