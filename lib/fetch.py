"""Shared polite-HTTP helpers for snapshot fetching.

A global throttle keeps a minimum spacing between requests across all
worker threads, and polite_get retries transient failures with backoff,
honoring Retry-After.
"""

import threading
import time

import requests

USER_AGENT = "tweet-recovery/1.0 (archival research tool; contact: repo operator)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class Throttle:
    """Global minimum spacing between requests across worker threads."""

    def __init__(self, interval: float):
        self.interval = interval
        self.lock = threading.Lock()
        self.last = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            delay = self.last + self.interval - now
            self.last = max(now, self.last + self.interval)
        if delay > 0:
            time.sleep(delay)


def polite_get(session, url, throttle, max_retries=4):
    """GET with throttle + backoff. Returns Response or None on network failure."""
    for attempt in range(max_retries):
        throttle.wait()
        try:
            resp = session.get(url, timeout=30, allow_redirects=True)
        except requests.RequestException:
            time.sleep(min(2 ** attempt * 2, 30))
            continue
        if resp.status_code in RETRY_STATUSES:
            retry_after = resp.headers.get("Retry-After")
            try:
                time.sleep(min(float(retry_after), 120))
            except (TypeError, ValueError):
                time.sleep(min(2 ** attempt * 3, 60))
            continue
        return resp
    return None
