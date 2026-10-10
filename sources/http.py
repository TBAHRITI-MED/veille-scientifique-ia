"""Appels HTTP communs : intervalle minimal par source, retries avec backoff."""

from __future__ import annotations

import threading
import time

import requests

from settings import USER_AGENT

RETRY_STATUSES = (429, 500, 502, 503, 504)


class SourceError(RuntimeError):
    """Erreur renvoyée par une source ou erreur réseau persistante."""


class Throttle:
    """Garantit un intervalle minimal entre deux requêtes vers une même source."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self.min_interval - (time.monotonic() - self._last)
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


def get(
    url: str,
    *,
    source: str,
    throttle: Throttle,
    params: dict | None = None,
    headers: dict | None = None,
    max_retries: int = 3,
    timeout: float = 30,
) -> requests.Response:
    """GET avec retries sur 429/5xx et erreurs réseau. Lève SourceError sinon."""
    return _send(lambda h: requests.get(url, params=params, headers=h, timeout=timeout),
                 source=source, throttle=throttle, headers=headers, max_retries=max_retries)


def post(
    url: str,
    *,
    source: str,
    throttle: Throttle,
    json: dict | list | None = None,
    params: dict | None = None,
    headers: dict | None = None,
    max_retries: int = 3,
    timeout: float = 60,
) -> requests.Response:
    """POST JSON, mêmes règles de retries que `get`."""
    return _send(lambda h: requests.post(url, json=json, params=params, headers=h, timeout=timeout),
                 source=source, throttle=throttle, headers=headers, max_retries=max_retries)


def _send(call, *, source: str, throttle: Throttle, headers: dict | None, max_retries: int) -> requests.Response:
    all_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        throttle.wait()
        try:
            response = call(all_headers)
        except requests.RequestException as exc:
            last_error = exc
        else:
            if response.status_code == 200:
                return response
            if response.status_code not in RETRY_STATUSES:
                raise SourceError(
                    f"{source} a répondu {response.status_code} : {response.text[:200]}"
                )
            last_error = SourceError(f"{source} a répondu {response.status_code}")
        time.sleep(throttle.min_interval * attempt)
    raise SourceError(f"{source} injoignable après {max_retries} tentatives : {last_error}")
