"""Shared HTTP client with per-host rate limiting and retries."""

from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

# Requests per minute per host. DexScreener: 60/min for profile/boost endpoints, 300/min for pair endpoints.
DEFAULT_RPM = {
    "api.dexscreener.com": 55,
    "api.rugcheck.xyz": 30,
    "api.gopluslabs.io": 25,
    "api.etherscan.io": 240,  # free tier is 5/s
    "api.telegram.org": 25,
    "api.mainnet-beta.solana.com": 60,  # public RPC is strict; use a private RPC for many wallets
}


class HttpClient:
    def __init__(self, rpm: dict[str, int] | None = None, timeout: float = 15, retries: int = 3):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "whalebot/0.1 (+https://github.com/mehtab958/crypto-signal)"
        self.rpm = {**DEFAULT_RPM, **(rpm or {})}
        self.timeout = timeout
        self.retries = retries
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _throttle(self, host: str) -> None:
        rpm = self.rpm.get(host)
        if not rpm:
            return
        interval = 60.0 / rpm
        with self._lock:
            wait = self._last.get(host, 0) + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()

    def request(self, method: str, url: str, **kwargs):
        host = urlparse(url).hostname or ""
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            self._throttle(host)
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code == 429 or resp.status_code >= 500:
                    delay = float(resp.headers.get("Retry-After") or 2 ** (attempt + 1))
                    log.debug("HTTP %s from %s, retrying in %.1fs", resp.status_code, host, delay)
                    time.sleep(min(delay, 30))
                    last_exc = requests.HTTPError(f"{resp.status_code} from {url}")
                    continue
                resp.raise_for_status()
                if not resp.content:
                    return None
                return resp.json()
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                time.sleep(2 ** attempt)
        raise last_exc or RuntimeError(f"request failed: {url}")

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def head_ok(self, url: str) -> bool:
        """True if the URL responds with a non-error status (used for website liveness)."""
        try:
            resp = self.session.get(url, timeout=8, allow_redirects=True, stream=True)
            resp.close()
            return resp.status_code < 400
        except requests.RequestException:
            return False
