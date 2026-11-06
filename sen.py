#!/usr/bin/env python3

import json
import os
import shutil
import signal
import sys
import time
import unicodedata
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

from Ratelimit import (
    ratelimit_get,
    build_session_headers,
    check_token_expiry,
    get_stats,
    configure,
)

INTERVAL_SEC           = int(os.environ.get("SENTIMENT_INTERVAL", "60"))
PRICE_FETCH_EVERY_N    = max(1, int(os.environ.get("SENTIMENT_PRICE_EVERY", "2")))
LOG_FILE               = os.environ.get("SENTIMENT_LOG_FILE", "").strip()
ENV_CONFIG_DIR         = os.environ.get("SENTIMENT_CONFIG_DIR", "").strip()

configure({
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "max_requests_per_second": 2.0,
    "max_requests_per_minute": 20,
    "timeouts": {
        "sentiment": 20,
        "price":     10,
        "news":      15,
        "hmr":       15,
        "default":   15,
    },
    "cache_ttl": {
        "sentiment": 30,
        "price":     120,
        "news":      120,
        "hmr":       300,
        "default":   0,
    },
})

BASE_EXTRA = {"Referer": "https://my.ex-markets.pro/webtrading/"}

API_URL        = "https://my.ex-markets.pro/v4/tex-api/v1/sentiment/all/"
HMR_API_URL    = "https://my.ex-markets.pro/v4/tex-api/v2/forex-news/margin/today/"
NEWS_API_URL   = "https://my.ex-markets.pro/v4/tex-api/v1/trading-central-news/events/en/"
RAW_GIST_URL   = (
    "https://gist.githubusercontent.com/Unknown-Desert/"
    "146a7511ec3f1af5d549ba7fa38e2a26/raw/Sentiment_Dat.txt"
)

COUNTRY_IMPACT_MAP = {
    "US": ["XAUUSD", "DXY", "XAGUSD", "USDJPY", "USDCAD", "USDCHF", "BTCUSD", "ETHUSD"],
    "GB": ["GBPUSD"],
    "EA": ["EURUSD", "XAUUSD"],
    "JP": ["USDJPY"],
    "AU": ["AUDUSD"],
    "NZ": ["NZDUSD"],
    "CN": ["XAUUSD", "AUDUSD", "NZDUSD"],
    "CA": ["USDCAD"],
    "CH": ["USDCHF"],
}

SYMBOLS = [
    "XAUUSD", "DXY", "USDJPY", "XAGUSD", "EURUSD", "GBPUSD",
    "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "BTCUSD", "ETHUSD",
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_LEVERAGE    = 500
NORMAL_MARGIN_PCT   = round(100 / DEFAULT_LEVERAGE, 2)

JWT_TOKEN      = ""
RTAPI_BASE_URL = ""
RTAPI_X_CID    = ""

last_valid_data: dict = {}
_prices_cache: dict = {} 

def _detect_unicode() -> bool:
    try:
        print("\u2b07", end="", flush=True)
        print("\r", end="", flush=True)
        return True
    except UnicodeEncodeError:
        return False

UNICODE_SUPPORT = _detect_unicode()

if UNICODE_SUPPORT:
    ARROW_UP       = "⬆⬆"
    ARROW_DOWN     = "⬇⬇"
    ARROW_SIDEWAYS = "⇕⇕"
    WARNING        = "⚠️"
    CROSS          = "❌"
    CHECK          = "✅"
    DOT_FILL       = "·"
else:
    ARROW_UP = "^"; ARROW_DOWN = "v"; ARROW_SIDEWAYS = "-"
    WARNING = "!!"; CROSS = "XX"; CHECK = "OK"; DOT_FILL = "."

_WIDE_CHARS = set(
    "⬆⬇⇕⚠✅❌🔴🟢🟡⚪📅⏳🔥👀💡💵📉🛢🌏🌅⛔"
)

def _vp(text: str, width: int) -> str:
    visual = 0
    for ch in text:
        if ch == "\ufe0f":
            continue
        if ch in _WIDE_CHARS:
            visual += 2
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            visual += 2
        else:
            visual += 1
    if visual >= width:
        return text
    return text + " " * (width - visual)

def safe_print(text: str, **kwargs):
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"), **kwargs)

def log(message: str):
    safe_print(message)
    if LOG_FILE:
        try:
            Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
        except Exception:
            pass

def _resolve_config_dir() -> str:
    if ENV_CONFIG_DIR:
        return os.path.expanduser(ENV_CONFIG_DIR)
    return os.path.join(os.path.expanduser("~"), ".sentiment")

def _migrate_config(config_path: str, legacy_path: str):
    if os.path.exists(config_path) or not os.path.exists(legacy_path):
        return
    try:
        os.makedirs(os.path.dirname(config_path), mode=0o700, exist_ok=True)
        shutil.copy2(legacy_path, config_path)
        try:
            os.chmod(config_path, 0o600)
        except OSError:
            pass
        log(f"{CHECK} Config dimigrasi: {legacy_path} → {config_path}")
    except Exception as e:
        log(f"{WARNING} Migrasi config gagal: {e}")

CONFIG_DIR = _resolve_config_dir()
try:
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    CONFIG_FILE = os.path.join(CONFIG_DIR, "Sentiment_Dat.txt")
except OSError:
    CONFIG_FILE = os.path.join(SCRIPT_DIR, "Sentiment_Dat.txt")

_migrate_config(CONFIG_FILE, os.path.join(SCRIPT_DIR, "Sentiment_Dat.txt"))

def write_text_safe(filepath: str, text: str) -> bool:
    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        try:
            os.chmod(filepath, 0o600)
        except OSError:
            pass
        return True
    except Exception as e:
        log(f"{WARNING} Gagal menulis {filepath}: {e}")
        return False

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except Exception:
            pass
    return {}

def load_token() -> str:
    return load_config().get("jwt_token", "")

def load_rtapi_config() -> tuple[str, str]:
    cfg = load_config()
    return cfg.get("rtapi_base_url", ""), cfg.get("rtapi_x_cid", "")

def generate_request_id() -> str:
    return str(uuid.uuid4()).replace("-", "")

def download_config_from_gist() -> bool:
    log(f"{WARNING} Mengunduh Sentiment_Dat.txt dari Gist...")
    for attempt in range(1, 4):
        try:
            log(f"   Percobaan {attempt}/3...")
            r = requests.get(RAW_GIST_URL, timeout=30)
            if r.status_code != 200:
                log(f"{CROSS} HTTP {r.status_code}")
                time.sleep(3); continue

            content = r.text.strip()
            try:
                json.loads(content)
            except json.JSONDecodeError:
                log(f"{CROSS} Body bukan JSON valid.")
                time.sleep(3); continue

            if write_text_safe(CONFIG_FILE, content):
                log(f"{CHECK} Config diunduh (percobaan {attempt}).")
                return True
            time.sleep(3)
        except requests.exceptions.Timeout:
            log(f"{CROSS} Timeout."); time.sleep(3)
        except requests.exceptions.ConnectionError:
            log(f"{CROSS} Connection error."); time.sleep(3)
        except Exception as e:
            log(f"{CROSS} Error: {e}"); time.sleep(3)

    log(f"{CROSS} Gagal download setelah 3 percobaan.")
    return False

def predict_candle_direction(buy_pct: float, sell_pct: float) -> str:
    if buy_pct >= 60:  return ARROW_DOWN
    if sell_pct >= 60: return ARROW_UP
    return ARROW_SIDEWAYS

def get_sentiment_flag(buy_pct: float, sell_pct: float) -> str:
    if sell_pct >= 60: return "🔴 SELL"
    if buy_pct >= 60:  return "🟢 BUY"
    return "⚪ BALANCE"

def check_dxy_warning(symbols_data: dict, data_status: dict | None = None):
    if data_status is None:
        data_status = {}
    dxy = symbols_data.get("DXY")
    if dxy is None:
        return True, "DXY not in API"
    if data_status.get("DXY", 1) != 1:
        return True, "DXY fallback data"
    b, s = dxy.get("buy", 0), dxy.get("sell", 0)
    if b == 0 and s == 0:
        return True, "DXY buy/sell = 0"
    if b < 0 or s < 0:
        return True, "DXY negative"
    return False, "DXY normal"

def fetch_price_for_symbol(symbol: str):
    global JWT_TOKEN, RTAPI_BASE_URL, RTAPI_X_CID
    if not JWT_TOKEN or not RTAPI_BASE_URL:
        return None

    for sym in (symbol.upper(), symbol.upper() + "m"):
        url = f"{RTAPI_BASE_URL}/{sym}/candles"
        params = {
            "time_frame": "1",
            "from": "9007199254740991",
            "count": "-300",
            "price": "bid",
        }
        headers = build_session_headers(JWT_TOKEN, extra={
            "Referer":         "https://my.ex-markets.pro/",
            "Origin":          "https://my.ex-markets.pro",
            "Accept-Language": "en-US,en;q=0.9",
            "x-cid":           RTAPI_X_CID,
            "x-request-id":    generate_request_id(),
        })
        resp = ratelimit_get(url, headers=headers, params=params, endpoint="price")

        if resp.status_code == 200 and resp.data is not None:
            ph = resp.data.get("price_history") or []
            if ph:
                return ph[0]["c"]
        if resp.status_code == 400 and resp.data is not None:
            try:
                if resp.data.get("code") == 10013:
                    continue
            except Exception:
                pass
        return None
    return None

def fetch_all_prices() -> dict:
    return {sym: fetch_price_for_symbol(sym) for sym in SYMBOLS}

def format_price(symbol: str, price) -> str:
    if price is None:
        return "N/A"
    if symbol in ("XAUUSD", "XAGUSD", "DXY", "BTCUSD", "ETHUSD"):
        return f"{price:,.2f}"
    if symbol == "USDJPY":
        return f"{price:,.3f}"
    return f"{price:.5f}"

def find_matching_symbols(data: dict):
    global last_valid_data
    matched, status = {}, {}
    keys = list(data.keys())
    for want in SYMBOLS:
        found = next((k for k in keys if want.upper() == k.upper()), None)
        if not found:
            found = next((k for k in keys if want.upper() in k.upper()), None)
        if found:
            matched[want] = data[found]
            status[want] = 1
            if data[found].get("buy", 0) > 0 or data[found].get("sell", 0) > 0:
                last_valid_data[want] = data[found]
        elif want in last_valid_data:
            matched[want] = last_valid_data[want]
            status[want] = 0
        else:
            matched[want] = {"buy": 0.0, "sell": 0.0}
            status[want] = -1
    return matched, status

def fetch_sentiment():
    headers = build_session_headers(JWT_TOKEN, extra=BASE_EXTRA)
    resp = ratelimit_get(API_URL, headers=headers, endpoint="sentiment")
    if resp.status_code == 401:
        log(f"{CROSS} 401 — token expired")
        return 401, None
    if resp.error == "circuit_open":
        log(f"{WARNING} circuit open, skip")
        return 0, None
    if resp.status_code != 200:
        log(f"{CROSS} HTTP {resp.status_code}: {resp.text[:120]}")
        return resp.status_code, None
    if resp.data is None:
        log(f"{CROSS} body not JSON (cf={resp.cf_challenge}, err={resp.error})")
        return -1, None
    if resp.from_cache:
        log("   (cached)")
    return 200, resp.data

def fetch_hmr_today() -> list:
    if not JWT_TOKEN:
        return []
    resp = ratelimit_get(
        HMR_API_URL,
        headers=build_session_headers(JWT_TOKEN, extra=BASE_EXTRA),
        endpoint="hmr",
    )
    if resp.status_code == 200 and resp.data is not None:
        return resp.data.get("hmr_periods", [])
    log(f"{WARNING} HMR fail: HTTP {resp.status_code}")
    return []

def check_hmr_for_symbols(periods: list) -> dict:
    now = int(time.time())
    result = {s: (False, None, None, None) for s in SYMBOLS}
    for p in periods:
        start, end = p.get("start", 0), p.get("end", 0)
        if not (start <= now <= end):
            continue
        pats = p.get("symbols", [])
        lev  = p.get("leverage", "?")
        if not pats:
            for s in SYMBOLS:
                result[s] = (True, lev, start, end)
            continue
        for pat in pats:
            clean = pat.replace("*", "").upper().strip()
            for s in SYMBOLS:
                su = s.upper()
                hit = False
                if clean == su:
                    hit = True
                elif pat.startswith("*") and pat.endswith("*"):
                    hit = bool(clean) and clean in su
                elif pat.endswith("*"):
                    hit = bool(clean) and su.startswith(clean)
                elif pat.startswith("*"):
                    hit = bool(clean) and su.endswith(clean)
                if hit:
                    result[s] = (True, lev, start, end)
    return result

def fetch_trading_central_news():
    if not JWT_TOKEN:
        return [], []
    params = {"after": "0h", "before": "48h",
              "ids_only": "false", "limit": 200, "offset": 0}
    resp = ratelimit_get(
        NEWS_API_URL,
        headers=build_session_headers(JWT_TOKEN, extra=BASE_EXTRA),
        params=params, endpoint="news",
    )
    if resp.status_code != 200 or resp.data is None:
        return [], []

    now = datetime.now(timezone.utc)
    wib_now = now + timedelta(hours=7)
    today_start_wib = wib_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end_wib   = today_start_wib + timedelta(days=1)
    tomorrow_end_wib = today_end_wib + timedelta(days=1)
    today_end_utc    = today_end_wib - timedelta(hours=7)
    tomorrow_end_utc = tomorrow_end_wib - timedelta(hours=7)

    today, tomorrow = [], []
    for ev in resp.data:
        ds = ev.get("date_utc", "")
        if not ds:
            continue
        t = datetime.fromisoformat(ds.replace("Z", "+00:00"))
        if t <= now or ev.get("volatility", 0) < 2:
            continue
        item = {
            "time": t,
            "name": ev.get("name", "Unknown"),
            "country": ev.get("country", ""),
            "volatility": ev.get("volatility", 0),
            "vol_label": "HIGH" if ev.get("volatility") == 3 else "MEDIUM",
            "consensus": ev.get("consensus"),
            "previous": ev.get("previous"),
            "unit": ev.get("unit", ""),
        }
        if t < today_end_utc:
            today.append(item)
        elif t < tomorrow_end_utc:
            tomorrow.append(item)
    today.sort(key=lambda x: x["time"])
    tomorrow.sort(key=lambda x: x["time"])
    return today, tomorrow

def get_affected_symbols(country: str) -> list:
    return COUNTRY_IMPACT_MAP.get(country, [])

def get_news_time_for_symbol(sym: str, news_list: list):
    if not news_list:
        return None, None, 0
    affected = [n for n in news_list if sym in get_affected_symbols(n["country"])]
    if not affected:
        return None, None, 0
    affected.sort(key=lambda x: (x["time"], -x["volatility"]))
    t0 = affected[0]["time"]
    same_time = [n for n in affected if n["time"] == t0]
    top_vol = max(n["volatility"] for n in same_time)
    t_str = (t0 + timedelta(hours=7)).strftime("%H:%M")
    icon = "🔴" if top_vol == 3 else "🟡"
    display = f"{t_str}+{icon}" if len(same_time) > 1 else f"{t_str} {icon}"
    return display, top_vol, len(same_time)

def calculate_candle_statistics(symbols_data: dict, dxy_warning: bool,
                                data_status: dict):
    preds, stats = {}, {"bullish": 0, "bearish": 0,
                        "sideways": 0, "total": 0, "excluded_dxy": False}
    for sym, val in symbols_data.items():
        bp = round(val["buy"] * 100, 2)
        sp = round(val["sell"] * 100, 2)

        if sym == "DXY" and data_status.get("DXY", 1) != 1:
            preds[sym] = {"direction": WARNING, "buy_pct": bp, "sell_pct": sp}
            stats["excluded_dxy"] = True
            continue

        d = predict_candle_direction(bp, sp)
        preds[sym] = {"direction": d, "buy_pct": bp, "sell_pct": sp}
        if d == ARROW_UP:    stats["bullish"] += 1
        elif d == ARROW_DOWN: stats["bearish"] += 1
        else:                 stats["sideways"] += 1
        stats["total"] += 1
    return preds, stats

def _terminal_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80

def _fmt_margin_hmr(leverage, start_ts, end_ts) -> str:
    try:
        lev = int(leverage)
        pct = round(100 / lev, 2)
    except Exception:
        lev, pct = leverage, "?"
    def wib(ts):
        return (datetime.fromtimestamp(ts, tz=timezone.utc)
                + timedelta(hours=7)).strftime("%d/%m %H:%M")
    return f"⚠️ HMR 1:{lev} ({pct}%) {wib(start_ts)}→{wib(end_ts)}"

def _news_compact(sym: str, today: list, tomorrow: list) -> str:
    disp, _, _ = get_news_time_for_symbol(sym, today)
    if disp:
        return disp
    disp2, _, _ = get_news_time_for_symbol(sym, tomorrow)
    if disp2:
        return "Tmr" + disp2[:5]
    return "--"

def display_compact(symbols_data, dxy_warning, title,
                    data_status, hmr_status, today_news, tomorrow_news, prices):
    preds, stats = calculate_candle_statistics(symbols_data, dxy_warning, data_status)
    width = _terminal_width()

    log("")
    log(title)
    log("─" * 78)

    if width >= 78:
        log(f"{'SYM':<6} | {'Buy':>6} | {'Sell':>6} | {'Candle':^8} | "
            f"{'News':^8} | {'Price':>11} | {'Flag':^12}")
        log("─" * 78)

        for sym in SYMBOLS:
            if sym not in symbols_data:
                log(f"{sym:<6} | {'N/A':>6} | {'N/A':>6} | {'N/A':^8} | "
                    f"{'--':^8} | {'N/A':>11} | {'NO DATA':^12}")
                continue

            v = symbols_data[sym]
            bp = round(v["buy"] * 100, 2)
            sp = round(v["sell"] * 100, 2)

            if sym == "DXY" and data_status.get("DXY", 1) != 1:
                candle = WARNING
                flag = "⛔ WARNING"
            else:
                candle = preds.get(sym, {}).get("direction", "N/A")
                flag = get_sentiment_flag(bp, sp)

            news  = _news_compact(sym, today_news, tomorrow_news)
            price = format_price(sym, prices.get(sym))

            log(f"{sym:<6} | {bp:>5.1f}% | {sp:>5.1f}% | "
                f"{_vp(candle, 8):^8} | {_vp(news, 8):^8} | "
                f"{price:>11} | {_vp(flag, 12):^12}")
            is_hmr, lev, st, en = hmr_status.get(sym, (False, None, None, None))
            if is_hmr and lev and st and en:
                log(f"   {_fmt_margin_hmr(lev, st, en)}")

        log("─" * 78)
    else:
        log(f"{'SYM':<6} | {'B/S%':^10} | {'C':^4} | {'News':^8} | {'Price':>11}")
        log("─" * 78)
        for sym in SYMBOLS:
            if sym not in symbols_data:
                log(f"{sym:<6} | {'N/A':^10} | {'':^4} | {'--':^8} | {'N/A':>11}")
                continue
            v = symbols_data[sym]
            bp, sp = round(v["buy"]*100, 1), round(v["sell"]*100, 1)
            candle = preds.get(sym, {}).get("direction", "")
            news = _news_compact(sym, today_news, tomorrow_news)
            price = format_price(sym, prices.get(sym))
            log(f"{sym:<6} | {bp:>4.0f}/{sp:<4.0f} | {_vp(candle,4):^4} | "
                f"{_vp(news,8):^8} | {price:>11}")
            is_hmr, lev, st, en = hmr_status.get(sym, (False, None, None, None))
            if is_hmr and lev:
                log(f"   ⚠️ HMR 1:{lev}")
        log("─" * 78)

    if stats["total"] > 0:
        label = f"{stats['total']} Pair"
        if stats["excluded_dxy"]:
            label += " (DXY Excluded)"
        tot = stats["total"]
        log(f"\nCANDLE STATS ({label}):")
        log(f"  {ARROW_UP} Bull : {stats['bullish']:>2} ({stats['bullish']/tot*100:.0f}%)")
        log(f"  {ARROW_DOWN} Bear : {stats['bearish']:>2} ({stats['bearish']/tot*100:.0f}%)")
        log(f"  {ARROW_SIDEWAYS} Side : {stats['sideways']:>2} ({stats['sideways']/tot*100:.0f}%)")

    if dxy_warning:
        log(f"\n{WARNING} REKOMENDASI: TIDAK ADA ENTRY — DXY warning")
    log("")

def display_news_compact(symbols_data, today_news, tomorrow_news):
    try:
        if today_news:
            top = today_news[:2]
            log(f"\n📅 {len(top)} BERITA TERDEKAT:")
            for i, n in enumerate(top, 1):
                icon = "🔴" if n["volatility"] == 3 else "🟡"
                t = (n["time"] + timedelta(hours=7)).strftime("%H:%M")
                log(f"  {i}. {icon} {t} {n['name']} ({n['country']})")
                if n.get("consensus") is not None and n.get("previous") is not None:
                    c, p = n["consensus"], n["previous"]
                    bias = "🟢" if c > p else ("🔴" if c < p else "⚪")
                    log(f"     Cons {c} vs Prev {p} → {bias}")

            first = today_news[0]["time"]
            total_sec = int((first - datetime.now(timezone.utc)).total_seconds())
            if total_sec < 1800:
                log("  🔴 <30 MENIT! JANGAN OVERTRADE!")
            elif total_sec < 3600:
                log("  🟠 <1 jam. Waspada.")
        else:
            log("\n✅ Tidak ada berita High/Medium hari ini.")

        if tomorrow_news:
            t0 = (tomorrow_news[0]["time"] + timedelta(hours=7)).strftime("%H:%M")
            log(f"📅 BESOK: {len(tomorrow_news)} berita, mulai {t0} WIB")
    except Exception as e:
        log(f"{WARNING} News display error: {e}")

def display_legend():
    log("=" * 65)
    log("LEGENDA")
    log("  ⬆⬆ = Bullish (mayoritas Sell retail)")
    log("  ⬇⬇ = Bearish (mayoritas Buy retail)")
    log("  ⇕⇕ = Sideways")
    log("  News: HH:MM🔴 = high impact hari ini | Tmr = besok | -- = tidak ada")
    log("=" * 65)

_shutdown_requested = False

def _on_signal(signum, _frame):
    global _shutdown_requested
    _shutdown_requested = True
    safe_print(f"\n[signal {signum}] shutdown diminta...")

for _sig in (signal.SIGINT, signal.SIGTERM):
    try:
        signal.signal(_sig, _on_signal)
    except (ValueError, OSError):
        pass


def _try_wake_lock():
    if not shutil.which("termux-wake-lock"):
        return
    try:
        os.system("termux-wake-lock")
        log("🔒 termux-wake-lock aktif")
    except Exception:
        pass

def _try_wake_unlock():
    if not shutil.which("termux-wake-unlock"):
        return
    try:
        os.system("termux-wake-unlock")
    except Exception:
        pass

def bootstrap_token() -> bool:
    global JWT_TOKEN, RTAPI_BASE_URL, RTAPI_X_CID

    cfg = load_config()
    JWT_TOKEN      = cfg.get("jwt_token", "")
    RTAPI_BASE_URL = cfg.get("rtapi_base_url", "")
    RTAPI_X_CID    = cfg.get("rtapi_x_cid", "")

    if JWT_TOKEN:
        return True

    log(f"{WARNING} Token tidak ditemukan di {CONFIG_FILE}")
    if download_config_from_gist():
        cfg = load_config()
        JWT_TOKEN      = cfg.get("jwt_token", "")
        RTAPI_BASE_URL = cfg.get("rtapi_base_url", "")
        RTAPI_X_CID    = cfg.get("rtapi_x_cid", "")
        return bool(JWT_TOKEN)

    return False

def handle_401_refresh() -> bool:
    global JWT_TOKEN, RTAPI_BASE_URL, RTAPI_X_CID
    old = JWT_TOKEN
    log("   Mencoba unduh ulang dari Gist...")
    try:
        os.remove(CONFIG_FILE)
    except Exception:
        pass
    if not download_config_from_gist():
        return False
    cfg = load_config()
    new = cfg.get("jwt_token", "")
    if not new or new == old:
        log(f"{CROSS} Gist masih berisi token yang sama/expired.")
        return False
    JWT_TOKEN      = new
    RTAPI_BASE_URL = cfg.get("rtapi_base_url", "")
    RTAPI_X_CID    = cfg.get("rtapi_x_cid", "")
    return True

def run_cycle(cycle_num: int, dxy_state: dict):
    status, data = fetch_sentiment()

    if status == 401:
        if handle_401_refresh():
            status, data = fetch_sentiment()
        if status != 200 or data is None:
            return False, dxy_state

    if status != 200 or data is None:
        log(f"{WARNING} fetch gagal (status={status})")
        return False, dxy_state

    symbols_data, data_status = find_matching_symbols(data)
    dxy_warning, _ = check_dxy_warning(symbols_data, data_status)

    # HMR
    hmr_data = fetch_hmr_today()
    hmr_status = check_hmr_for_symbols(hmr_data) if hmr_data else {}

    # News
    today_news, tomorrow_news = fetch_trading_central_news()

    global _prices_cache
    if cycle_num % PRICE_FETCH_EVERY_N == 1:
        try:
            fresh = fetch_all_prices()
            for k, v in fresh.items():
                if v is not None:
                    _prices_cache[k] = v
        except Exception as e:
            log(f"{WARNING} price fetch error: {e}")
    prices = _prices_cache

    if dxy_warning and not dxy_state["prev"]:
        log(f"\n{WARNING} DXY MULAI WARNING")
    elif not dxy_warning and dxy_state["prev"]:
        log(f"\n{CHECK} DXY KEMBALI NORMAL setelah {dxy_state['cycles']} siklus")
    dxy_state["prev"] = dxy_warning
    dxy_state["cycles"] = dxy_state["cycles"] + 1 if dxy_warning else 0

    title = "SIKLUS SENTIMEN"
    if dxy_warning:
        title += " [DXY WARNING]"

    display_compact(symbols_data, dxy_warning, title, data_status,
                    hmr_status, today_news, tomorrow_news, prices)
    display_news_compact(symbols_data, today_news, tomorrow_news)
    return True, dxy_state

def main():
    if not bootstrap_token():
        log(f"{CROSS} Token tidak tersedia.")
        log(f"{WARNING} Hubungi Admin untuk Sentiment_Dat.txt.")
        return

    should_refresh, secs_left = check_token_expiry(JWT_TOKEN, buffer_seconds=300)
    if should_refresh:
        if secs_left is None:
            log(f"{WARNING} Token tanpa 'exp' — tidak dapat verifikasi.")
        elif secs_left <= 0:
            log(f"{CROSS} Token sudah expired {-secs_left}s lalu.")
        else:
            log(f"{WARNING} Token expired dalam {secs_left}s.")

    log("=" * 60)
    log("SENTIMENT MONITOR — TERMUX MOBILE")
    log(f"  Symbols   : {len(SYMBOLS)}")
    log(f"  Interval  : {INTERVAL_SEC}s")
    log(f"  Price     : setiap {PRICE_FETCH_EVERY_N} siklus")
    log(f"  Config    : {CONFIG_FILE}")
    if LOG_FILE:
        log(f"  Log file  : {LOG_FILE}")
    log("=" * 60)

    display_legend()
    _try_wake_lock()

    log("\nKoneksi awal...")
    status, data = fetch_sentiment()

    if status == 401:
        if handle_401_refresh():
            status, data = fetch_sentiment()
        if status != 200 or data is None:
            log(f"{CROSS} Gagal memperoleh token valid. Hubungi Admin.")
            _try_wake_unlock()
            return

    dxy_state = {"prev": False, "cycles": 0}
    cycle_num = 0
    fail_streak = 0
    last_clear = time.time()

    if status == 200 and data is not None:
        cycle_num = 1
        ok, dxy_state = run_cycle(cycle_num, dxy_state)
        fail_streak = 0 if ok else 1

    log(f"\nMenunggu {INTERVAL_SEC}s...")
    print()

    while not _shutdown_requested:
        try:
            wait = INTERVAL_SEC
            if fail_streak >= 3:
                wait = min(INTERVAL_SEC * 2 ** min(fail_streak - 2, 4), 600)
                log(f"{WARNING} {fail_streak} kegagalan berturut — backoff {wait}s")

            for _ in range(wait):
                if _shutdown_requested:
                    break
                time.sleep(1)

            if _shutdown_requested:
                break

            cycle_num += 1

            if time.time() - last_clear >= 600:
                os.system("clear")
                log("=== LAYAR DIBERSIHKAN (10 menit) ===\n")
                display_legend()
                last_clear = time.time()

            ok, dxy_state = run_cycle(cycle_num, dxy_state)
            fail_streak = 0 if ok else fail_streak + 1

        except Exception as e:
            fail_streak += 1
            log(f"{CROSS} cycle error: {e}")
            time.sleep(5)

    log("\nClean shutdown...")
    log(f"Total siklus: {cycle_num}")
    log("--- Ratelimit Stats ---")
    try:
        s = get_stats()
        log(f"  uptime        : {s['uptime_sec']}s")
        log(f"  cache hit     : {s['cache_hit_rate_pct']}%")
        log(f"  status counts : {s['status_counts']}")
        log(f"  backoffs      : {s['backoff_events']}")
        log(f"  fallbacks     : {s['fallback_events']}")
    except Exception as e:
        log(f"  stats error   : {e}")
    _try_wake_unlock()


if __name__ == "__main__":
    main()