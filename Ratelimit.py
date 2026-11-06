# Ratelimit.py
from __future__ import annotations

import base64
import json
import random
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests


DEFAULT_CONFIG: Dict[str, Any] = {
    "max_requests_per_second": 4.0,
    "max_requests_per_minute": 30,
    "jitter_min": 0.10,
    "jitter_max": 0.50,
    "backoff_base": 2,
    "backoff_max": 30,
    "backoff_retries": 4,
    "circuit_fail_threshold": 3,
    "circuit_open_seconds": 300,
    "cache_ttl": {
        "sentiment": 30, "price": 60, "news": 120,
        "hmr": 300, "default": 0,
    },
    "timeouts": {
        "sentiment": 15, "price": 5, "news": 10,
        "hmr": 10, "default": 10,
    },
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "accept_language": "en-US,en;q=0.9",
    "legacy_accept_language": "id-ID,id;q=0.9",
    "token_refresh_buffer": 300,
}


_LEGACY_MODE: bool = True
_ENCODING_CACHE: Optional[str] = None
_ENCODING_LOCK = threading.Lock()


def _detect_accept_encoding() -> str:
    global _ENCODING_CACHE
    if _ENCODING_CACHE is not None:
        return _ENCODING_CACHE
    with _ENCODING_LOCK:
        if _ENCODING_CACHE is not None:
            return _ENCODING_CACHE
        encodings = ["gzip", "deflate"]
        try:
            import brotli  # noqa: F401
            encodings.append("br")
        except ImportError:
            try:
                import brotlicffi  # noqa: F401
                encodings.append("br")
            except ImportError:
                pass
        try:
            import zstandard  # noqa: F401
            encodings.append("zstd")
        except ImportError:
            pass
        _ENCODING_CACHE = ", ".join(encodings)
        return _ENCODING_CACHE


class CircuitOpenError(Exception):
    pass


class RateLimiter:
    def __init__(self, max_per_sec: float, max_per_min: int):
        self.max_per_sec = max_per_sec
        self.max_per_min = max_per_min
        self._lock = threading.Lock()
        self._sec: deque = deque()
        self._min: deque = deque()

    def acquire(self):
        while True:
            with self._lock:
                now = time.monotonic()
                while self._sec and now - self._sec[0] > 1.0:
                    self._sec.popleft()
                while self._min and now - self._min[0] > 60.0:
                    self._min.popleft()
                if (len(self._sec) < self.max_per_sec and
                        len(self._min) < self.max_per_min):
                    self._sec.append(now)
                    self._min.append(now)
                    return
                wait = 0.0
                if len(self._sec) >= self.max_per_sec:
                    wait = max(wait, 1.0 - (now - self._sec[0]))
                if len(self._min) >= self.max_per_min:
                    wait = max(wait, 60.0 - (now - self._min[0]))
                wait = max(wait, 0.05)
            time.sleep(wait)


class TTLCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._store: Dict[str, Tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            value, expires = entry
            if time.monotonic() > expires:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: int):
        if ttl <= 0:
            return
        with self._lock:
            self._store[key] = (value, time.monotonic() + ttl)


class _CircuitState:
    __slots__ = ("failures", "open_until")

    def __init__(self):
        self.failures = 0
        self.open_until = 0.0


class CircuitBreaker:
    def __init__(self, fail_threshold: int, open_seconds: int):
        self.threshold = fail_threshold
        self.open_seconds = open_seconds
        self._lock = threading.Lock()
        self._states: Dict[str, _CircuitState] = defaultdict(_CircuitState)

    def check(self, endpoint: str):
        with self._lock:
            st = self._states[endpoint]
            if st.open_until > time.monotonic():
                raise CircuitOpenError(
                    f"Circuit '{endpoint}' open, "
                    f"retry in {st.open_until - time.monotonic():.1f}s"
                )

    def record_failure(self, endpoint: str):
        with self._lock:
            st = self._states[endpoint]
            st.failures += 1
            if st.failures >= self.threshold:
                st.open_until = time.monotonic() + self.open_seconds

    def record_success(self, endpoint: str):
        with self._lock:
            st = self._states[endpoint]
            st.failures = 0
            st.open_until = 0.0


class Metrics:
    def __init__(self, ring_size: int = 200):
        self._lock = threading.Lock()
        self._ring: deque = deque(maxlen=ring_size)
        self._status: Dict[int, int] = defaultdict(int)
        self._endpoints: Dict[str, int] = defaultdict(int)
        self._hits = 0
        self._misses = 0
        self._backoffs = 0
        self._fallbacks = 0
        self._started = time.time()

    def record(self, endpoint: str, status: int, latency: float,
               from_cache: bool, retried: int):
        with self._lock:
            self._ring.append({
                "ts": time.time(), "endpoint": endpoint, "status": status,
                "latency_ms": round(latency * 1000, 1),
                "cache": from_cache, "retried": retried,
            })
            self._status[status] += 1
            self._endpoints[endpoint] += 1
            if from_cache:
                self._hits += 1
            else:
                self._misses += 1
            if retried:
                self._backoffs += 1

    def record_fallback(self):
        with self._lock:
            self._fallbacks += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total else 0.0
            return {
                "uptime_sec": round(time.time() - self._started, 1),
                "status_counts": dict(self._status),
                "endpoint_counts": dict(self._endpoints),
                "cache_hits": self._hits,
                "cache_misses": self._misses,
                "cache_hit_rate_pct": round(hit_rate, 2),
                "backoff_events": self._backoffs,
                "fallback_events": self._fallbacks,
                "legacy_mode": _LEGACY_MODE,
                "accept_encoding": _ENCODING_CACHE,
                "recent": list(self._ring)[-10:],
            }


class CachedResponse:
    __slots__ = ("status_code", "data", "text", "from_cache", "error",
                 "content_type", "cf_challenge", "used_fallback",
                 "exception_type")

    def __init__(self, status_code: int, data: Any = None,
                 text: str = "", from_cache: bool = False,
                 error: Optional[str] = None,
                 content_type: str = "",
                 cf_challenge: bool = False,
                 used_fallback: bool = False,
                 exception_type: Optional[str] = None):
        self.status_code = status_code
        self.data = data
        self.text = text
        self.from_cache = from_cache
        self.error = error
        self.content_type = content_type
        self.cf_challenge = cf_challenge
        self.used_fallback = used_fallback
        self.exception_type = exception_type

    def json(self):
        if self.data is not None:
            return self.data
        return json.loads(self.text)

    def __repr__(self):
        return (f"<CachedResponse status={self.status_code} "
                f"cache={self.from_cache} fallback={self.used_fallback} "
                f"err={self.error}>")


def _looks_like_cloudflare(resp: requests.Response) -> bool:
    hl = {k.lower(): v for k, v in resp.headers.items()}
    cf_mitigated = hl.get("cf-mitigated", "").lower()
    if cf_mitigated in ("challenge", "managed_challenge"):
        return True
    ct = hl.get("content-type", "").lower()
    if "html" in ct or not ct:
        body = (resp.text or "")[:2000].lower()
        markers = (
            "just a moment", "checking your browser",
            "attention required", "cf-browser-verification",
            "challenge-platform", "<title>access denied",
            "please enable cookies",
        )
        if any(m in body for m in markers):
            return True
    return False


def _safe_json(resp: requests.Response) -> Tuple[Optional[Any], Optional[str]]:
    if not resp.content:
        return None, "empty_body"
    try:
        return resp.json(), None
    except Exception as parse_err:
        pass
    if _looks_like_cloudflare(resp):
        preview = (resp.text or "")[:150].replace("\n", " ").strip()
        return None, f"cloudflare_challenge preview={preview!r}"
    ct = resp.headers.get("Content-Type", "").lower()
    preview = (resp.text or "")[:200].replace("\n", " ").strip()
    try:
        raw = resp.content
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                cand = raw.decode(enc)
                if cand.lstrip()[:1] in ("{", "["):
                    return json.loads(cand), None
            except Exception:
                continue
    except Exception:
        pass
    return None, f"json_error={parse_err} ct={ct!r} preview={preview!r}"


def _parse_retry_after(resp: requests.Response) -> Optional[float]:
    v = resp.headers.get("Retry-After")
    if not v:
        return None
    try:
        return float(v.strip())
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max((dt - datetime.now(timezone.utc)).total_seconds(), 0.0)
    except Exception:
        return None


def _build_legacy_headers(token: Optional[str],
                          extra: Optional[Dict[str, str]],
                          config: Dict[str, Any]) -> Dict[str, str]:
    h = {
        "User-Agent": config["user_agent"],
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": config["legacy_accept_language"],
        "Referer": "https://my.exness.com/webtrading/",
        "dnt": "1",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    if extra:
        h.update(extra)
    return h


def _build_modern_headers(token: Optional[str],
                          extra: Optional[Dict[str, str]],
                          config: Dict[str, Any]) -> Dict[str, str]:
    h = {
        "User-Agent": config["user_agent"],
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": config["accept_language"],
        "Accept-Encoding": _detect_accept_encoding(),
        "Referer": "https://my.exness.com/webtrading/",
        "Origin": "https://my.exness.com",
        "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "dnt": "1",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    if extra:
        h.update(extra)
    return h


def build_headers(token: Optional[str] = None,
                  extra: Optional[Dict[str, str]] = None,
                  config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    cfg = config or DEFAULT_CONFIG
    if _LEGACY_MODE:
        return _build_legacy_headers(token, extra, cfg)
    return _build_modern_headers(token, extra, cfg)


def check_token_expiry(token: str,
                       buffer_seconds: int = 300
                       ) -> Tuple[bool, Optional[int]]:
    if not token:
        return True, None
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return True, None
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload))
        exp = payload.get("exp")
        if not exp:
            return False, None
        left = int(exp - time.time())
        return left < buffer_seconds, left
    except Exception:
        return False, None


class RateLimitedClient:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.rate_limiter = RateLimiter(
            self.config["max_requests_per_second"],
            self.config["max_requests_per_minute"],
        )
        self.cache = TTLCache()
        self.circuit = CircuitBreaker(
            self.config["circuit_fail_threshold"],
            self.config["circuit_open_seconds"],
        )
        self.metrics = Metrics()
        self._init_session()

    def _init_session(self):
        try:
            if getattr(self, "session", None) is not None:
                self.session.close()
        except Exception:
            pass
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=4, pool_maxsize=8, max_retries=0,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _timeout_for(self, endpoint: str) -> float:
        return self.config["timeouts"].get(
            endpoint, self.config["timeouts"]["default"])

    def _ttl_for(self, endpoint: str, override: Optional[int]) -> int:
        if override is not None:
            return override
        return self.config["cache_ttl"].get(
            endpoint, self.config["cache_ttl"]["default"])

    @staticmethod
    def _cache_key(url: str, params: Optional[Dict[str, Any]]) -> str:
        return f"{url}|{json.dumps(params or {}, sort_keys=True)}"

    @staticmethod
    def _backoff_wait(attempt: int, base: int, cap: int) -> float:
        return min(base ** (attempt + 1), cap) + random.uniform(0.0, 0.5)

    def _switch_to_legacy(self, reason: str):
        global _LEGACY_MODE
        print(f"[Ratelimit] Switch to LEGACY mode ({reason})")
        _LEGACY_MODE = True
        self._init_session()
        time.sleep(1.0)

    def _probe_mode(self, url, headers, params, endpoint, timeout):
        if _LEGACY_MODE:
            return
        self.rate_limiter.acquire()
        time.sleep(random.uniform(self.config["jitter_min"],
                                  self.config["jitter_max"]))
        try:
            resp = self.session.get(url, headers=headers, params=params,
                                    timeout=timeout)
        except requests.RequestException as e:
            self._switch_to_legacy(
                f"probe network: {type(e).__name__}: {e}")
            return
        if _looks_like_cloudflare(resp):
            print("[Ratelimit] Probe: CF challenge (not switching)")
            return
        data, reason = _safe_json(resp)
        if resp.status_code == 200 and data is None:
            self._switch_to_legacy(f"probe invalid body: {reason}")

    def _rebuild_legacy_headers(self, modern_headers):
        token = None
        auth = (modern_headers.get("Authorization")
                or modern_headers.get("authorization") or "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
        extra = {k: v for k, v in modern_headers.items()
                 if k.lower().startswith("x-")}
        return build_headers(token, extra=extra)

    def get(self, url: str, *,
            headers: Optional[Dict[str, str]] = None,
            params: Optional[Dict[str, Any]] = None,
            endpoint: str = "default",
            cache_ttl: Optional[int] = None,
            bypass_cache: bool = False) -> CachedResponse:
        try:
            self.circuit.check(endpoint)
        except CircuitOpenError as e:
            return CachedResponse(0, error="circuit_open", text=str(e))

        key = self._cache_key(url, params)
        ttl = self._ttl_for(endpoint, cache_ttl)
        if not bypass_cache and ttl > 0:
            cached = self.cache.get(key)
            if cached is not None:
                self.metrics.record(endpoint, cached.status_code, 0.0,
                                    True, 0)
                return CachedResponse(
                    cached.status_code, cached.data, cached.text,
                    from_cache=True, error=cached.error,
                    content_type=cached.content_type,
                    cf_challenge=cached.cf_challenge,
                    used_fallback=cached.used_fallback,
                )

        eff_headers = headers or build_headers()
        timeout = self._timeout_for(endpoint)

        if not _LEGACY_MODE:
            self._probe_mode(url, eff_headers, params, endpoint, timeout)
            if _LEGACY_MODE:
                eff_headers = self._rebuild_legacy_headers(eff_headers)

        retries = self.config["backoff_retries"]
        base = self.config["backoff_base"]
        cap = self.config["backoff_max"]
        last_exc: Optional[Exception] = None

        for attempt in range(retries + 1):
            self.rate_limiter.acquire()
            time.sleep(random.uniform(self.config["jitter_min"],
                                      self.config["jitter_max"]))

            start = time.monotonic()
            try:
                resp = self.session.get(url, headers=eff_headers,
                                        params=params, timeout=timeout)
            except requests.RequestException as e:
                last_exc = e
                self.metrics.record(endpoint, 0,
                                    time.monotonic() - start, False, attempt)
                if attempt >= 1:
                    self.circuit.record_failure(endpoint)
                print(f"[Ratelimit] {endpoint} attempt {attempt+1}: "
                      f"{type(e).__name__}: {e}")
                if not _LEGACY_MODE:
                    self._switch_to_legacy(
                        f"request network: {type(e).__name__}")
                    eff_headers = self._rebuild_legacy_headers(eff_headers)
                    continue
                if attempt >= retries:
                    return CachedResponse(
                        0, error="network", text=str(e),
                        exception_type=type(e).__name__)
                time.sleep(self._backoff_wait(attempt, base, cap))
                continue

            latency = time.monotonic() - start

            if resp.status_code in (429, 503):
                self.circuit.record_failure(endpoint)
                self.metrics.record(endpoint, resp.status_code, latency,
                                    False, attempt)
                if attempt >= retries:
                    d, r = _safe_json(resp)
                    return CachedResponse(
                        resp.status_code, d, resp.text,
                        error=r or "rate_limited")
                wait = _parse_retry_after(resp) or \
                    self._backoff_wait(attempt, base, cap)
                time.sleep(wait)
                continue

            if 500 <= resp.status_code < 600:
                self.circuit.record_failure(endpoint)
                self.metrics.record(endpoint, resp.status_code, latency,
                                    False, attempt)
                if attempt >= retries:
                    return CachedResponse(
                        resp.status_code, None, resp.text,
                        error="server_error")
                time.sleep(self._backoff_wait(attempt, base, cap))
                continue

            data, reason = _safe_json(resp)
            cf = _looks_like_cloudflare(resp)
            used_fallback = False

            if resp.status_code == 200 and cf:
                self.metrics.record(endpoint, resp.status_code, latency,
                                    False, attempt)
                if attempt < retries:
                    cf_wait = min(5 * (attempt + 1), 20) + \
                              random.uniform(1.0, 3.0)
                    print(f"[Ratelimit] CF challenge on '{endpoint}' "
                          f"(attempt {attempt+1}/{retries+1}), "
                          f"cooldown {cf_wait:.1f}s...")
                    time.sleep(cf_wait)
                    continue
                else:
                    preview = (resp.text or "")[:150].replace("\n", " ")
                    return CachedResponse(
                        resp.status_code, None, resp.text,
                        error=f"cf_challenge_exhausted preview={preview!r}",
                        content_type=resp.headers.get("Content-Type", ""),
                        cf_challenge=True,
                    )

            if (resp.status_code == 200 and data is None and not cf
                    and not _LEGACY_MODE):
                self.metrics.record_fallback()
                self._switch_to_legacy(f"body invalid: {reason}")
                eff_headers = self._rebuild_legacy_headers(eff_headers)
                self.rate_limiter.acquire()
                time.sleep(random.uniform(self.config["jitter_min"],
                                          self.config["jitter_max"]))
                try:
                    fb_resp = self.session.get(url, headers=eff_headers,
                                               params=params, timeout=timeout)
                    fb_data, fb_reason = _safe_json(fb_resp)
                    if fb_data is not None:
                        resp = fb_resp
                        data = fb_data
                        reason = None
                        used_fallback = True
                except requests.RequestException:
                    pass

            result = CachedResponse(
                resp.status_code, data, resp.text,
                error=reason,
                content_type=resp.headers.get("Content-Type", ""),
                cf_challenge=cf,
                used_fallback=used_fallback,
            )

            if (resp.status_code == 200 and ttl > 0
                    and not bypass_cache and data is not None):
                self.cache.set(key, result, ttl)

            if resp.status_code < 500:
                self.circuit.record_success(endpoint)

            self.metrics.record(endpoint, resp.status_code, latency,
                                False, attempt)
            return result

        return CachedResponse(0, error="exhausted",
                              text=str(last_exc or "unknown"),
                              exception_type=(type(last_exc).__name__
                                              if last_exc else None))


_CLIENT: Optional[RateLimitedClient] = None
_CLIENT_LOCK = threading.Lock()


def get_client() -> RateLimitedClient:
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = RateLimitedClient()
    return _CLIENT


def configure(overrides: Dict[str, Any]):
    global _CLIENT
    with _CLIENT_LOCK:
        _CLIENT = RateLimitedClient(overrides)


def ratelimit_get(url: str, **kwargs) -> CachedResponse:
    return get_client().get(url, **kwargs)


def build_session_headers(token: Optional[str] = None,
                          extra: Optional[Dict[str, str]] = None
                          ) -> Dict[str, str]:
    return build_headers(token, extra, get_client().config)


def get_stats() -> Dict[str, Any]:
    return get_client().metrics.snapshot()