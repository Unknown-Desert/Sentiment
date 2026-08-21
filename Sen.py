#!/usr/bin/env python3
# =============================================================
# SENTIMENT MONITOR - TERMUX
# =============================================================

import asyncio
import uuid
import time
import os
import sys
import requests
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

def get_unicode_support():
    try:
        print("\u2b07", end="", flush=True)
        print("\r", end="", flush=True)
        return True
    except UnicodeEncodeError:
        return False

UNICODE_SUPPORT = get_unicode_support()

if UNICODE_SUPPORT:
    ARROW_UP = "⬆⬆"
    ARROW_DOWN = " ⬇⬇"
    ARROW_SIDEWAYS = "⇕⇕"
    WARNING = "⚠️"
    CROSS = "❌"
    CHECK = "✅"
else:
    ARROW_UP = "^"
    ARROW_DOWN = "v"
    ARROW_SIDEWAYS = "-"
    WARNING = "!!"
    CROSS = "XX"
    CHECK = "OK"

SHOW_TIMESTAMP = False

API_URL = "https://my.ex-markets.pro/v4/tex-api/v1/sentiment/all/"
HMR_API_URL = "https://my.ex-markets.pro/v4/tex-api/v2/forex-news/margin/today/"
TRADING_CENTRAL_NEWS_URL = "https://my.ex-markets.pro/v4/tex-api/v1/trading-central-news/events/en/"

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
    "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "BTCUSD", "ETHUSD"
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "Sentiment_Dat.txt")

RAW_GIST_URL = "https://gist.githubusercontent.com/Unknown-Desert/146a7511ec3f1af5d549ba7fa38e2a26/raw/Sentiment_Dat.txt"

JWT_TOKEN = ""
RTAPI_BASE_URL = ""
RTAPI_X_CID = ""

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://my.ex-markets.pro/webtrading/",
    "Accept-Language": "id-ID,id;q=0.9",
    "dnt": "1",
}

last_valid_data = {}
market_status_history = []

DEFAULT_LEVERAGE = 500
NORMAL_MARGIN_PCT = round(100 / DEFAULT_LEVERAGE, 2)

def safe_print(text, **kwargs):
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        text_ascii = text.encode('ascii', errors='replace').decode('ascii')
        print(text_ascii, **kwargs)

def log(message):
    if SHOW_TIMESTAMP:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        safe_print(f"[{timestamp}] {message}")
    else:
        safe_print(message)

def write_text_safe(filepath, text):
    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        os.chmod(filepath, 0o600)
        return True
    except Exception as e:
        safe_print(f"{WARNING} Gagal menulis file {filepath}: {e}")
        return False

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except:
            pass
    return {}

def save_config(config_dict):
    try:
        json_text = json.dumps(config_dict, indent=2)
        return write_text_safe(CONFIG_FILE, json_text)
    except Exception as e:
        safe_print(f"{WARNING} Gagal menyimpan config: {e}")
        return False

def load_token():
    cfg = load_config()
    return cfg.get("jwt_token", "")

def load_rtapi_config():
    cfg = load_config()
    return cfg.get("rtapi_base_url", ""), cfg.get("rtapi_x_cid", "")

def generate_request_id():
    return str(uuid.uuid4()).replace('-', '')

def download_config_from_gist():

    log(f"{WARNING} Sentiment_Dat.txt tidak ditemukan atau perlu diunduh ulang.")
    log(f"   Mencoba mengunduh dari Gist (raw URL)...")

    max_retries = 3
    retry_delay = 3

    for attempt in range(1, max_retries + 1):
        try:
            log(f"   Percobaan {attempt}/{max_retries}...")
            response = requests.get(RAW_GIST_URL, timeout=30)

            if response.status_code == 200:
                content = response.text.strip()
                try:
                    json.loads(content)
                except json.JSONDecodeError:
                    log(f"{CROSS} File yang diunduh bukan format JSON yang valid.")
                    if attempt < max_retries:
                        log(f"   Menunggu {retry_delay} detik sebelum mencoba ulang...")
                        time.sleep(retry_delay)
                    continue

                if write_text_safe(CONFIG_FILE, content):
                    log(f"{CHECK} Sentiment_Dat.txt berhasil diunduh dari Gist (percobaan {attempt}).")
                    return True
                else:
                    log(f"{CROSS} Gagal menyimpan file Sentiment_Dat.txt.")
                    if attempt < max_retries:
                        log(f"   Menunggu {retry_delay} detik sebelum mencoba ulang...")
                        time.sleep(retry_delay)
                    continue

            else:
                log(f"{CROSS} Gagal mengunduh dari Gist: HTTP {response.status_code}")
                if attempt < max_retries:
                    log(f"   Menunggu {retry_delay} detik sebelum mencoba ulang...")
                    time.sleep(retry_delay)
                continue

        except requests.exceptions.Timeout:
            log(f"{CROSS} Timeout koneksi saat mengunduh dari Gist.")
            if attempt < max_retries:
                log(f"   Menunggu {retry_delay} detik sebelum mencoba ulang...")
                time.sleep(retry_delay)
            continue

        except requests.exceptions.ConnectionError:
            log(f"{CROSS} Gagal terhubung ke server Gist (ConnectionError).")
            if attempt < max_retries:
                log(f"   Menunggu {retry_delay} detik sebelum mencoba ulang...")
                time.sleep(retry_delay)
            continue

        except Exception as e:
            log(f"{CROSS} Error tak terduga saat mengunduh dari Gist: {e}")
            if attempt < max_retries:
                log(f"   Menunggu {retry_delay} detik sebelum mencoba ulang...")
                time.sleep(retry_delay)
            continue

    log(f"{CROSS} Gagal mengunduh Sentiment_Dat.txt setelah {max_retries} kali percobaan.")
    return False

def predict_candle_direction(buy_pct, sell_pct):
    if buy_pct >= 60:
        return ARROW_DOWN
    if sell_pct >= 60:
        return ARROW_UP
    return ARROW_SIDEWAYS

def get_candle_prediction_detail(buy_pct, sell_pct):
    direction = predict_candle_direction(buy_pct, sell_pct)
    if direction == ARROW_DOWN:
        detail = "Bearish (Mayoritas Buy)"
    elif direction == ARROW_UP:
        detail = "Bullish (Mayoritas Sell)"
    else:
        detail = "Sideways (Seimbang)"
    return direction, detail

def get_sentiment_flag(buy_pct, sell_pct):
    if sell_pct >= 60:
        return "🔴 SELL"
    elif buy_pct >= 60:
        return "🟢 BUY"
    else:
        return "⚪ BALANCE"

def check_dxy_warning(symbols_data, data_status=None):
    if data_status is None:
        data_status = {}
    dxy_data = symbols_data.get("DXY")
    if dxy_data is None:
        return True, "DXY tidak ditemukan di API"
    if data_status.get("DXY", 1) != 1:
        return True, "DXY menggunakan data fallback (tidak segar)"
    buy_val = dxy_data.get('buy', 0)
    sell_val = dxy_data.get('sell', 0)
    if buy_val == 0 and sell_val == 0:
        return True, "DXY buy dan sell = 0 (tidak ada posisi)"
    if buy_val < 0 or sell_val < 0:
        return True, "Data DXY tidak valid (nilai negatif)"
    return False, "DXY normal"

def fetch_price_for_symbol(symbol):
    global JWT_TOKEN, RTAPI_BASE_URL, RTAPI_X_CID
    if not JWT_TOKEN:
        return None

    candidates = [
        symbol.upper(),
        symbol.upper() + "m",
    ]

    for sym in candidates:
        url = f"{RTAPI_BASE_URL}/{sym}/candles"
        params = {
            "time_frame": "1",
            "from": "9007199254740991",
            "count": "-300",
            "price": "bid"
        }
        headers = {
            "Authorization": f"Bearer {JWT_TOKEN}",
            "x-cid": RTAPI_X_CID,
            "x-request-id": generate_request_id(),
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://my.ex-markets.pro/",
            "Origin": "https://my.ex-markets.pro",
            "dnt": "1",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            response = requests.get(url, params=params, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if 'price_history' in data and len(data['price_history']) > 0:
                    return data['price_history'][0]['c']
            if response.status_code == 400:
                try:
                    err = response.json()
                    if err.get("code") == 10013:
                        continue
                except:
                    pass
            return None
        except:
            return None

    return None

def fetch_all_prices():
    prices = {}
    for sym in SYMBOLS:
        try:
            prices[sym] = fetch_price_for_symbol(sym)
        except:
            prices[sym] = None
    return prices

def format_price(symbol, price):
    if price is None:
        return "N/A"
    if symbol in ("XAUUSD", "XAGUSD", "DXY", "BTCUSD", "ETHUSD"):
        return f"{price:,.2f}"
    elif symbol == "USDJPY":
        return f"{price:,.3f}"
    else:
        return f"{price:.5f}"

def find_matching_symbols(data):
    global last_valid_data
    matched = {}
    data_status = {}
    available_keys = list(data.keys())

    for desired_sym in SYMBOLS:
        found = None
        for key in available_keys:
            if desired_sym.upper() == key.upper():
                found = key
                break

        if not found:
            for key in available_keys:
                if desired_sym.upper() in key.upper():
                    found = key
                    log(f"{WARNING} {desired_sym} -> dipetakan ke {key}")
                    break

        if found:
            matched[desired_sym] = data[found]
            data_status[desired_sym] = 1
            if data[found].get('buy', 0) > 0 or data[found].get('sell', 0) > 0:
                last_valid_data[desired_sym] = data[found]
        else:
            if desired_sym in last_valid_data:
                matched[desired_sym] = last_valid_data[desired_sym]
                data_status[desired_sym] = 0
                log(f"{WARNING} {desired_sym} tidak ditemukan, pakai data terakhir.")
            else:
                matched[desired_sym] = {'buy': 0.0, 'sell': 0.0}
                data_status[desired_sym] = -1
                log(f"{WARNING} {desired_sym} tidak ditemukan dan tidak ada histori.")

    return matched, data_status

def fetch_sentiment():
    global JWT_TOKEN
    headers = COMMON_HEADERS.copy()
    headers["Authorization"] = f"Bearer {JWT_TOKEN}"

    try:
        response = requests.get(API_URL, headers=headers, timeout=15)
        if response.status_code == 401:
            log(f"{CROSS} ERROR 401: Token expired!")
            return (401, None)
        elif response.status_code == 403:
            log(f"{CROSS} ERROR 403: Forbidden.")
            return (403, None)
        elif response.status_code != 200:
            log(f"{CROSS} ERROR {response.status_code}: {response.text[:200]}")
            return (response.status_code, None)
        return (200, response.json())
    except requests.exceptions.Timeout:
        log(f"{WARNING} Timeout")
        return (0, None)
    except requests.exceptions.ConnectionError:
        log(f"{WARNING} Connection error")
        return (0, None)
    except Exception as e:
        log(f"{CROSS} Error: {e}")
        return (-1, None)

def fetch_hmr_today():
    global JWT_TOKEN
    if not JWT_TOKEN:
        return []
    headers = COMMON_HEADERS.copy()
    headers["Authorization"] = f"Bearer {JWT_TOKEN}"
    try:
        resp = requests.get(HMR_API_URL, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('hmr_periods', [])
        else:
            log(f"{WARNING} Gagal fetch HMR: HTTP {resp.status_code}")
            return []
    except Exception as e:
        log(f"{WARNING} Error fetch HMR: {e}")
        return []

def check_hmr_for_symbols(hmr_periods):
    now = int(time.time())
    result = {sym: (False, None, None, None) for sym in SYMBOLS}

    for period in hmr_periods:
        start = period.get('start', 0)
        end = period.get('end', 0)
        if not (start <= now <= end):
            continue

        symbols_in_period = period.get('symbols', [])
        leverage = period.get('leverage', '?')

        if not symbols_in_period:
            for sym in SYMBOLS:
                result[sym] = (True, leverage, start, end)
            continue

        for pattern in symbols_in_period:
            pattern_clean = pattern.replace('*', '').upper().strip()
            for sym in SYMBOLS:
                sym_upper = sym.upper()
                if pattern_clean == sym_upper:
                    result[sym] = (True, leverage, start, end)
                    continue
                if pattern.startswith('*') and pattern.endswith('*'):
                    if pattern_clean and pattern_clean in sym_upper:
                        result[sym] = (True, leverage, start, end)
                        continue
                elif pattern.endswith('*'):
                    if pattern_clean and sym_upper.startswith(pattern_clean):
                        result[sym] = (True, leverage, start, end)
                        continue
                elif pattern.startswith('*'):
                    if pattern_clean and sym_upper.endswith(pattern_clean):
                        result[sym] = (True, leverage, start, end)
                        continue
    return result

def fetch_trading_central_news():
    global JWT_TOKEN
    if not JWT_TOKEN:
        return [], []

    headers = COMMON_HEADERS.copy()
    headers["Authorization"] = f"Bearer {JWT_TOKEN}"
    params = {
        "after": "0h",
        "before": "48h",
        "ids_only": "false",
        "limit": 200,
        "offset": 0
    }
    try:
        resp = requests.get(TRADING_CENTRAL_NEWS_URL, headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            events = resp.json()
            now = datetime.now(timezone.utc)
            wib_now = now + timedelta(hours=7)
            today_start_wib = wib_now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end_wib = today_start_wib + timedelta(days=1)
            tomorrow_end_wib = today_end_wib + timedelta(days=1)
            today_start_utc = today_start_wib - timedelta(hours=7)
            today_end_utc = today_end_wib - timedelta(hours=7)
            tomorrow_end_utc = tomorrow_end_wib - timedelta(hours=7)

            today_news = []
            tomorrow_news = []

            for ev in events:
                date_str = ev.get('date_utc', '')
                if not date_str:
                    continue
                ev_time = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                if ev_time <= now:
                    continue
                vol = ev.get('volatility', 0)
                if vol < 2:
                    continue

                news_item = {
                    'time': ev_time,
                    'name': ev.get('name', 'Unknown'),
                    'country': ev.get('country', ''),
                    'volatility': vol,
                    'vol_label': 'HIGH' if vol == 3 else 'MEDIUM',
                    'consensus': ev.get('consensus'),
                    'previous': ev.get('previous'),
                    'unit': ev.get('unit', '')
                }

                if ev_time < today_end_utc:
                    today_news.append(news_item)
                elif ev_time < tomorrow_end_utc:
                    tomorrow_news.append(news_item)

            today_news.sort(key=lambda x: x['time'])
            tomorrow_news.sort(key=lambda x: x['time'])
            return today_news, tomorrow_news
        else:
            return [], []
    except Exception as e:
        log(f"{WARNING} Error fetch berita: {e}")
        return [], []

def get_affected_symbols(country_code):
    return COUNTRY_IMPACT_MAP.get(country_code, [])

def get_news_time_for_symbol(sym, news_list):
    if not news_list:
        return None, None, 0

    affected = [n for n in news_list if sym in get_affected_symbols(n['country'])]
    if not affected:
        return None, None, 0

    affected.sort(key=lambda x: (x['time'], -x['volatility']))
    nearest = affected[0]
    target_time = nearest['time']
    same_time_count = sum(1 for n in affected if n['time'] == target_time)
    highest_vol = max(n['volatility'] for n in affected if n['time'] == target_time)

    utc7_time = target_time + timedelta(hours=7)
    time_str = utc7_time.strftime('%H:%M')
    impact_icon = "🔴" if highest_vol == 3 else "🟡"

    if same_time_count > 1:
        display = f"{time_str}+{impact_icon}"
    else:
        display = f"{time_str} {impact_icon}"

    return display, highest_vol, same_time_count

def get_news_display_for_symbol(sym, today_news, tomorrow_news):
    news_display, _, _ = get_news_time_for_symbol(sym, today_news)
    if news_display is not None:
        return news_display
    tomorrow_display, _, _ = get_news_time_for_symbol(sym, tomorrow_news)
    if tomorrow_display is not None:
        return "Tomorrow "
    return "❌"

def calculate_candle_statistics(symbols_data, dxy_warning=False, data_status=None):
    if data_status is None:
        data_status = {}

    predictions = {}
    stats = {
        'bullish': 0,
        'bearish': 0,
        'sideways': 0,
        'total': 0,
        'excluded_dxy': False
    }

    for sym, val in symbols_data.items():
        buy_pct = round(val['buy'] * 100, 2)
        sell_pct = round(val['sell'] * 100, 2)

        is_dxy_warning = (sym == "DXY" and data_status.get("DXY", 1) != 1)

        if sym == "DXY" and is_dxy_warning:
            direction = WARNING
            detail = "DXY Warning - Data tidak valid"
            predictions[sym] = {
                'direction': direction,
                'detail': detail,
                'buy_pct': buy_pct,
                'sell_pct': sell_pct
            }
            stats['excluded_dxy'] = True
            continue

        direction, detail = get_candle_prediction_detail(buy_pct, sell_pct)
        predictions[sym] = {
            'direction': direction,
            'detail': detail,
            'buy_pct': buy_pct,
            'sell_pct': sell_pct
        }

        if direction == ARROW_UP:
            stats['bullish'] += 1
        elif direction == ARROW_DOWN:
            stats['bearish'] += 1
        else:
            stats['sideways'] += 1
        stats['total'] += 1

    return predictions, stats

def display_all_sentiments(symbols_data, dxy_warning=False, title="SENTIMEN SEMUA SIMBOL", data_status=None, hmr_status=None, today_news=None, tomorrow_news=None, prices=None):
    if data_status is None:
        data_status = {}
    if hmr_status is None:
        hmr_status = {}
    if today_news is None:
        today_news = []
    if tomorrow_news is None:
        tomorrow_news = []
    if prices is None:
        prices = {}

    candle_predictions, candle_stats = calculate_candle_statistics(symbols_data, dxy_warning, data_status)

    def to_wib_str(ts):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=7)
        return dt.strftime('%d/%m %H:%M')

    log(title)
    log("-" * 120)
    log(f"{'SYMBOL':<6} |{'Buy':>5}   | {'Sell':>5}  | {'Candle':^6} | {'Margin':^41} |  {'News':^8} | {'Price':^10} | {'Flag':^12}")
    log("-" * 120)

    for sym in SYMBOLS:
        if sym in symbols_data:
            val = symbols_data[sym]
            buy_pct = round(val['buy'] * 100, 2)
            sell_pct = round(val['sell'] * 100, 2)

            if sym == "DXY" and data_status.get("DXY", 1) != 1:
                flag = "⛔ WARNING"
                candle_display = WARNING
            else:
                flag = get_sentiment_flag(buy_pct, sell_pct)
                if sym in candle_predictions:
                    candle_display = candle_predictions[sym]['direction']
                else:
                    candle_display = "N/A"

            is_hmr, leverage, start_ts, end_ts = hmr_status.get(sym, (False, None, None, None))
            if is_hmr and leverage and start_ts and end_ts:
                try:
                    lev = int(leverage)
                    margin_pct = round(100 / lev, 2)
                except:
                    lev = leverage
                    margin_pct = "?"
                start_str = to_wib_str(start_ts)
                end_str = to_wib_str(end_ts)
                margin_display = f"⚠️ 1:{lev} ({margin_pct}%) {start_str} → {end_str}"
            else:
                margin_display = f"1:{DEFAULT_LEVERAGE} ({NORMAL_MARGIN_PCT}%)"

            news_display = get_news_display_for_symbol(sym, today_news, tomorrow_news)

            if sym in prices:
                price_display = format_price(sym, prices[sym])
            else:
                price_display = "N/A"

            log(f"{sym:<6} | {buy_pct:5.2f}% | {sell_pct:5.2f}% | {candle_display:^6} | {margin_display:<41} | {news_display:^8} | {price_display:<10} | {flag:<12}")
        else:
            price_display = "N/A"
            if sym == "DXY":
                log(f"{sym:<6} | {'N/A':>5} | {'N/A':>5} | {WARNING:^6} | {'1:500 (0.2%)':<41} | {'❌':^8} | {price_display:<10} | {'⛔ WARNING':<12}")
            else:
                log(f"{sym:<6} | {'N/A':>5} | {'N/A':>5} | {'N/A':^6} | {'1:500 (0.2%)':<41} | {'❌':^8} | {price_display:<10} | {'NO DATA':<12}")

    log("-" * 120)

    if candle_stats['total'] > 0:
        pair_count = candle_stats['total']
        pair_label = f"{pair_count} Pair"
        if candle_stats.get('excluded_dxy', False):
            pair_label += " (DXY Excluded)"

        bull_pct = candle_stats['bullish']/candle_stats['total']*100
        bear_pct = candle_stats['bearish']/candle_stats['total']*100
        side_pct = candle_stats['sideways']/candle_stats['total']*100

        log(f"\nSTATISTIK PREDIKSI CANDLE ({pair_label}):")
        log(f"   {ARROW_UP} Bullish  : {candle_stats['bullish']:>2} simbol ({bull_pct:.1f}%)")
        log(f"  {ARROW_DOWN} Bearish  : {candle_stats['bearish']:>2} simbol ({bear_pct:.1f}%)")
        log(f"   {ARROW_SIDEWAYS} Sideways : {candle_stats['sideways']:>2} simbol ({side_pct:.1f}%)")

        if candle_stats['bullish'] > candle_stats['bearish'] and candle_stats['bullish'] > candle_stats['sideways']:
            log(f"   Dominasi: Sinyal Bearish - Predict Going Down Multiple Pair")
        elif candle_stats['bearish'] > candle_stats['bullish'] and candle_stats['bearish'] > candle_stats['sideways']:
            log(f"   Dominasi: Sinyal Bullish - Predict Going Up Multiple Pair")
        else:
            log(f"   Dominasi: Mixed/Sideways - Market Unpredictable")
    else:
        log(f"\n{WARNING} Tidak ada data cukup untuk statistik dominasi")

    log("")

    if dxy_warning:
        log(f"{WARNING} REKOMENDASI: TIDAK ADA ENTRY")
        log(f"   * DXY dalam kondisi Warning - Market tidak stabil")
        log(f"   * Sinyal 11 pair lain tetap normal, pertimbangkan risiko")
        log(f"   * Tunggu hingga DXY kembali normal")

    log("")

def display_news_and_hmr(hmr_periods, symbols_data=None, today_news=None, tomorrow_news=None):
    try:
        if today_news:
            sorted_news = sorted(today_news, key=lambda x: (x['time'], -x['volatility']))

            if sorted_news:
                top_news = sorted_news[:3]
                first_news = top_news[0]
                target_time = first_news['time']

                now = datetime.now(timezone.utc)
                time_left = target_time - now
                total_sec = int(time_left.total_seconds())
                hours, rem = divmod(total_sec, 3600)
                mins = rem // 60

                log(f"\n{'='*60}")
                log(f"📅 {len(top_news)} BERITA TERDEKAT:")
                log(f"{'='*60}")
                log(f"")

                for i, news in enumerate(top_news, 1):
                    impact_icon = "🔴" if news['volatility'] == 3 else "🟡"
                    news_time_wib = news['time'] + timedelta(hours=7)
                    time_str = news_time_wib.strftime('%H:%M')
                    log(f"   {i}. {impact_icon} {news['name']} ({news['country']})")
                    log(f"      Jam: {time_str} WIB | Dampak: {news['vol_label']}")
                    if news.get('consensus') is not None and news.get('previous') is not None:
                        cons = news['consensus']
                        prev = news['previous']
                        if cons > prev:
                            exp = "🟢 BULLISH"
                        elif cons < prev:
                            exp = "🔴 BEARISH"
                        else:
                            exp = "⚪ NETRAL"
                        log(f"      Consensus {cons} vs Previous {prev} → {exp}")
                    else:
                        log(f"      Consensus/Previous tidak tersedia")

                utc7_time = target_time + timedelta(hours=7)
                log(f"\n⏰ Waktu berita pertama: {utc7_time.strftime('%d %b %Y %H:%M')} WIB")
                if hours > 0:
                    log(f"⏳ Sisa waktu: {hours} jam {mins} menit lagi")
                else:
                    log(f"⏳ Sisa waktu: {mins} menit lagi")

                analysis_news = first_news
                if analysis_news.get('consensus') is not None and analysis_news.get('previous') is not None:
                    consensus = analysis_news['consensus']
                    previous = analysis_news['previous']
                    if consensus > previous:
                        exp_direction = "🟢 Ekspektasi BULLISH"
                        exp_detail = f"Consensus {consensus} > Previous {previous}"
                    elif consensus < previous:
                        exp_direction = "🔴 Ekspektasi BEARISH"
                        exp_detail = f"Consensus {consensus} < Previous {previous}"
                    else:
                        exp_direction = "⚪ Ekspektasi NETRAL"
                        exp_detail = f"Consensus = Previous ({consensus})"

                    log(f"   📊 {exp_direction} ({analysis_news['name']})")
                    log(f"      {exp_detail}")

                    if symbols_data:
                        affected = get_affected_symbols(analysis_news['country'])
                        our_affected = [s for s in SYMBOLS if s in affected]
                        if our_affected:
                            sym = our_affected[0]
                            if sym in symbols_data:
                                buy_pct = round(symbols_data[sym]['buy'] * 100, 2)
                                sell_pct = round(symbols_data[sym]['sell'] * 100, 2)
                                sent_flag = get_sentiment_flag(buy_pct, sell_pct)
                                log(f"      Sentimen {sym}: {sent_flag}")

                all_affected = set()
                for n in top_news:
                    all_affected.update(get_affected_symbols(n['country']))
                our_affected = sorted([s for s in SYMBOLS if s in all_affected])
                if our_affected:
                    log(f"   ⚠️  Pair terdampak: {', '.join(our_affected)}")

                if total_sec < 1800:
                    log(f"   🔴 HATI-HATI! Kurang dari 30 menit. JANGAN OVERTRADE!")
                elif total_sec < 3600:
                    log(f"   🟠 WASPADA! Kurang dari 1 jam. Pertimbangkan risiko.")
                elif total_sec < 7200:
                    log(f"   🟡 Perhatian! Kurang dari 2 jam menjelang berita.")
        else:
            log(f"\n✅ Tidak ada berita High/Medium untuk HARI INI.")

        if tomorrow_news:
            count_tomorrow = len(tomorrow_news)
            first_tomorrow = tomorrow_news[0]
            utc7_tomorrow = first_tomorrow['time'] + timedelta(hours=7)
            log(f"\n📅 BESOK: {count_tomorrow} berita, mulai {utc7_tomorrow.strftime('%H:%M')} WIB")

    except Exception as e:
        log(f"{WARNING} Gagal menampilkan berita: {e}")

def display_legend():
    safe_print("\n" + "="*65)
    safe_print("LEGENDA SIMBOL & PREDIKSI CANDLE")
    safe_print("")
    if not UNICODE_SUPPORT:
        safe_print(f"\n  {WARNING} Terminal tidak mendukung Unicode, menggunakan simbol ASCII")
    safe_print("="*65)
    safe_print("")

def main():
    global JWT_TOKEN, RTAPI_BASE_URL, RTAPI_X_CID

    cfg = load_config()
    JWT_TOKEN = cfg.get("jwt_token", "")
    RTAPI_BASE_URL, RTAPI_X_CID = load_rtapi_config()

    if not JWT_TOKEN:
        log(f"{WARNING} Token tidak ditemukan di {CONFIG_FILE}")
        if download_config_from_gist():
            cfg = load_config()
            JWT_TOKEN = cfg.get("jwt_token", "")
            RTAPI_BASE_URL, RTAPI_X_CID = load_rtapi_config()
        else:
            log(f"{CROSS} Tidak dapat memperoleh token.")
            log(f"{WARNING} Tolong hubungi Admin untuk mendapatkan file Sentiment_Dat.txt")
            log(f"   Lalu letakkan di folder yang sama dengan script ini.")
            return

    if not JWT_TOKEN:
        log(f"{CROSS} Token masih kosong setelah download.")
        log(f"{WARNING} Tolong hubungi Admin.")
        return

    if not RTAPI_BASE_URL or not RTAPI_X_CID:
        log(f"{WARNING} RT-API config tidak lengkap. Harga real-time tidak akan tersedia.")

    log("=" * 60)
    log("Sentiment Data Realtime Monitor - TERMUX")
    log(f"{len(SYMBOLS)} Symbols: {', '.join(SYMBOLS)}")
    log("=" * 60)

    display_legend()

    log("\nMencoba koneksi ke API...")
    status, data = fetch_sentiment()

    if status == 401:
        log(f"{CROSS} Token expired atau tidak valid.")
        log(f"   Mencoba menghapus file lama dan mengunduh ulang dari Gist...")

        try:
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
                log(f"   {CHECK} File lama {CONFIG_FILE} berhasil dihapus.")
            else:
                log(f"   File lama tidak ditemukan, lanjut ke download.")
        except Exception as e:
            log(f"{WARNING} Gagal menghapus file lama: {e}")

        if download_config_from_gist():
            cfg = load_config()
            new_token = cfg.get("jwt_token", "")
            new_rtapi_base, new_rtapi_cid = load_rtapi_config()

            if new_token:
                log(f"   Mencoba ulang koneksi dengan token baru...")
                JWT_TOKEN = new_token
                RTAPI_BASE_URL = new_rtapi_base
                RTAPI_X_CID = new_rtapi_cid

                retry_status, retry_data = fetch_sentiment()

                if retry_status == 200 and retry_data:
                    status = retry_status
                    data = retry_data
                    log(f"{CHECK} Koneksi berhasil dengan token baru.")
                else:
                    log(f"{CROSS} Token baru dari Gist masih tidak valid atau koneksi gagal.")
                    if retry_status == 401:
                        log(f"{WARNING} Token di Gist juga sudah expired. Tolong hubungi Admin untuk memperbarui Gist.")
                    else:
                        log(f"{WARNING} Tolong hubungi Admin untuk mendapatkan token baru.")
                    return
            else:
                log(f"{CROSS} Token kosong setelah download ulang.")
                log(f"{WARNING} Tolong hubungi Admin.")
                return
        else:
            log(f"{CROSS} Gagal mengunduh ulang Sentiment_Dat.txt dari Gist.")
            log(f"{WARNING} Tolong hubungi Admin untuk mendapatkan token baru.")
            return

    if status == 200 and data:
        symbols_data, data_status = find_matching_symbols(data)
        dxy_warning, dxy_reason = check_dxy_warning(symbols_data, data_status)

        if symbols_data:
            log(f"{CHECK} {len(symbols_data)} dari {len(SYMBOLS)} simbol ditemukan.")

            hmr_data_init = fetch_hmr_today()
            hmr_status_init = check_hmr_for_symbols(hmr_data_init) if hmr_data_init else {}
            today_news_init, tomorrow_news_init = fetch_trading_central_news()

            prices_init = {}
            try:
                prices_init = fetch_all_prices()
                if prices_init:
                    price_count = sum(1 for p in prices_init.values() if p is not None)
                    log(f"{CHECK} Harga real-time: {price_count}/{len(SYMBOLS)} simbol berhasil diambil")
            except Exception as e:
                log(f"{WARNING} Gagal fetch harga awal: {e}")

            display_all_sentiments(
                symbols_data, dxy_warning, "STATUS SENTIMEN AWAL",
                data_status, hmr_status=hmr_status_init,
                today_news=today_news_init, tomorrow_news=tomorrow_news_init,
                prices=prices_init
            )
        else:
            log(f"{WARNING} Tidak ada simbol yang cocok.")
    else:
        log(f"{WARNING} Gagal koneksi awal (status: {status}).")

    log("\nMenunggu 60 detik...")
    print()

    cycle_count = 0
    dxy_warning_cycles = 0
    previous_dxy_warning = False
    last_clear_time = time.time()

    while True:
        try:
            cycle_count += 1
            time.sleep(60)

            if time.time() - last_clear_time >= 600:
                os.system('clear')
                safe_print("\n=== LAYAR DIBERSIHKAN SETIAP 10 MENIT ===\n")
                display_legend()
                last_clear_time = time.time()

            status, data = fetch_sentiment()

            if status == 401:
                log(f"{CROSS} Token expired di tengah pemantauan. Harap restart script.")
                break

            if status == 200 and data:
                symbols_data, data_status = find_matching_symbols(data)
                dxy_warning, dxy_reason = check_dxy_warning(symbols_data, data_status)

                hmr_data = []
                hmr_status = {}
                today_news = []
                tomorrow_news = []
                try:
                    hmr_data = fetch_hmr_today()
                    if hmr_data:
                        hmr_status = check_hmr_for_symbols(hmr_data)
                except Exception as e:
                    log(f"{WARNING} Gagal fetch/hitung HMR: {e}")

                try:
                    today_news, tomorrow_news = fetch_trading_central_news()
                except Exception as e:
                    log(f"{WARNING} Gagal fetch berita: {e}")

                prices = {}
                try:
                    prices = fetch_all_prices()
                except:
                    pass

                if symbols_data:
                    if dxy_warning:
                        dxy_warning_cycles += 1
                        if not previous_dxy_warning:
                            log(f"\n{WARNING} DXY MULAI WARNING - SINYAL DXY TIDAK VALID!")
                    else:
                        if dxy_warning_cycles > 0:
                            log(f"\n{CHECK} DXY KEMBALI NORMAL setelah {dxy_warning_cycles} menit warning")
                        dxy_warning_cycles = 0

                    previous_dxy_warning = dxy_warning

                    title = "SENTIMEN SIKLUS"
                    if dxy_warning:
                        title += " [DXY WARNING]"

                    display_all_sentiments(
                        symbols_data, dxy_warning, title,
                        data_status,
                        hmr_status=hmr_status,
                        today_news=today_news,
                        tomorrow_news=tomorrow_news,
                        prices=prices
                    )

                    try:
                        display_news_and_hmr(hmr_data, symbols_data, today_news=today_news, tomorrow_news=tomorrow_news)
                    except Exception as e:
                        log(f"{WARNING} Modul berita error (tidak menghentikan bot): {e}")

                    print()
                else:
                    log(f"{WARNING} Tidak ada simbol yang cocok.")
            else:
                log(f"{WARNING} Gagal fetch (status: {status}), mencoba lagi...")

        except KeyboardInterrupt:
            log("\nDihentikan oleh pengguna.")
            log(f"Total siklus: {cycle_count}")
            break
        except Exception as e:
            log(f"{CROSS} Error tidak terduga: {e}")
            log("Melanjutkan ke siklus berikutnya...")
            time.sleep(5)

if __name__ == "__main__":
    main()