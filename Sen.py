import asyncio
import uuid
import subprocess
import time
import os
import sys
import platform
import requests
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.async_api import async_playwright

def get_unicode_support():
    """Deteksi apakah terminal mendukung Unicode."""
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
CSV_FILE = r"C:\Users\User MSI\Desktop\sentiment_data.csv"

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
    "XAUUSD",
    "DXY",
    "USDJPY",
    "XAGUSD",
    "EURUSD",
    "GBPUSD",
    "AUDUSD",
    "NZDUSD",
    "USDCAD",
    "USDCHF",
    "BTCUSD",
    "ETHUSD"
]

CHROME_DEBUG_PORT = 9222
CDP_URL = f"http://localhost:{CHROME_DEBUG_PORT}"
TARGET_URL = "https://my.ex-markets.pro/webtrading/"
WAIT_AFTER_LAUNCH = 3
WAIT_AFTER_RELOAD = 5
user_data_dir = None

TOKEN_FILE = "jwt_token.txt"
JWT_TOKEN = ""

RTAPI_BASE_URL = "https://rtapi-sg.fognetgapoatseadaymagqak.com/rtapi/mt5/trial8/v2/accounts/279675500/instruments"
RTAPI_X_CID = "exterm_web_5a178e29-3ea5-4bbd-823f-e67f1d64f24e"

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
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
    """Wrapper untuk print yang aman dari UnicodeEncodeError."""
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        text_ascii = text.encode('ascii', errors='replace').decode('ascii')
        print(text_ascii, **kwargs)

def log(message):
    """Fungsi logging dengan timestamp opsional."""
    if SHOW_TIMESTAMP:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        safe_print(f"[{timestamp}] {message}")
    else:
        safe_print(message)

def load_token():
    """Baca token dari file TOKEN_FILE."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            token = f.read().strip()
            if token:
                return token
    return None

def save_token(token):
    """Simpan token ke TOKEN_FILE."""
    with open(TOKEN_FILE, 'w') as f:
        f.write(token)

def predict_candle_direction(buy_pct, sell_pct):
    """
    Memprediksi arah candle berdasarkan persentase buy/sell.
    - Buy > Sell DAN Buy >= 60% : Bearish (ARROW_DOWN)
    - Sell > Buy DAN Sell >= 60% : Bullish (ARROW_UP)
    - Lainnya : Sideways (ARROW_SIDEWAYS) — termasuk semua kondisi BALANCE
    """
    if buy_pct >= 60:
        return ARROW_DOWN
    
    if sell_pct >= 60:
        return ARROW_UP
    
    return ARROW_SIDEWAYS

def get_candle_prediction_detail(buy_pct, sell_pct):
    """
    Memberikan detail prediksi candle dengan penjelasan.
    """
    direction = predict_candle_direction(buy_pct, sell_pct)
    
    if direction == ARROW_DOWN:
        detail = "Bearish (Mayoritas Buy)"
    elif direction == ARROW_UP:
        detail = "Bullish (Mayoritas Sell)"
    else:
        detail = "Sideways (Seimbang)"
    
    return direction, detail

def get_sentiment_flag(buy_pct, sell_pct):
    """
    Menentukan flag berdasarkan persentase sentimen.
    Hanya menghasilkan: 🟢 BUY, 🔴 SELL, atau ⚪ BALANCE.
    """
    if sell_pct >= 60:
        return "🔴 SELL"
    elif buy_pct >= 60:
        return "🟢 BUY"
    else:
        return "⚪ BALANCE"

def check_dxy_warning(symbols_data, data_status=None):
    """
    Memeriksa apakah DXY dalam kondisi warning.
    Hanya DXY yang diperiksa, tidak mempengaruhi pair lain.
    
    Return:
        (is_warning, reason)
    """
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

def write_csv(symbols_data, dxy_warning=False, data_status=None, candle_predictions=None):
    """
    Tulis data sentimen multi-simbol ke CSV.
    Untuk DXY dengan data tidak segar, prediksi di-override menjadi "WARNING".
    """
    if data_status is None:
        data_status = {}
    if candle_predictions is None:
        candle_predictions = {}

    with open(CSV_FILE, 'w') as f:
        row_parts = []
        
        for sym in SYMBOLS:
            if sym in symbols_data:
                buy_pct = round(symbols_data[sym]['buy'] * 100, 2)
                sell_pct = round(symbols_data[sym]['sell'] * 100, 2)
                row_parts.append(str(buy_pct))
                row_parts.append(str(sell_pct))
                
                if sym in data_status:
                    row_parts.append(str(data_status[sym]))
                else:
                    row_parts.append("1")
                
                if sym == "DXY" and data_status.get("DXY", 1) != 1:
                    row_parts.append("WARNING")
                elif sym in candle_predictions:
                    direction = candle_predictions[sym]
                    if direction == ARROW_UP:
                        row_parts.append("UP")
                    elif direction == ARROW_DOWN:
                        row_parts.append("DOWN")
                    else:
                        row_parts.append("SIDEWAYS")
                else:
                    row_parts.append("N/A")
            else:
                row_parts.append("0")
                row_parts.append("0")
                row_parts.append("-1")
                row_parts.append("N/A")
        
        row_parts.append("1" if dxy_warning else "0")
        row_parts.append(str(time.time()))
        
        f.write(','.join(row_parts))

def generate_request_id():
    """Generate random request ID seperti di header x-request-id."""
    return str(uuid.uuid4()).replace('-', '')

def fetch_price_for_symbol(symbol):
    """
    Ambil harga close terbaru (candle 1 menit) untuk satu simbol.
    Return: float harga, atau None jika gagal.
    """
    global JWT_TOKEN
    if not JWT_TOKEN:
        return None

    url = f"{RTAPI_BASE_URL}/{symbol.upper()}/candles"
    params = {
        "time_frame": "1",
        "from": "9007199254740991",
        "count": "-1",
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
        response = requests.get(url, params=params, headers=headers, timeout=3)
        if response.status_code == 200:
            data = response.json()
            if 'price_history' in data and len(data['price_history']) > 0:
                return data['price_history'][0]['c']
    except:
        pass
    return None

def fetch_all_prices():
    """
    Ambil harga untuk semua simbol di SYMBOLS.
    Return: dict {symbol: price_or_None}
    """
    prices = {}
    for sym in SYMBOLS:
        try:
            prices[sym] = fetch_price_for_symbol(sym)
        except:
            prices[sym] = None
    return prices

def format_price(symbol, price):
    """Format harga sesuai tipe pair."""
    if price is None:
        return "N/A"

    if symbol in ("XAUUSD", "XAGUSD", "DXY", "BTCUSD", "ETHUSD"):
        return f"{price:,.2f}"
    elif symbol == "USDJPY":
        return f"{price:,.3f}"
    else:
        return f"{price:.5f}"

def find_matching_symbols(data):
    """
    Cocokkan simbol dari daftar SYMBOLS dengan key di data JSON.
    """
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
    """
    Ambil data sentimen menggunakan token terkini.
    """
    global JWT_TOKEN
    headers = COMMON_HEADERS.copy()
    headers["Authorization"] = f"Bearer {JWT_TOKEN}"
    
    try:
        response = requests.get(API_URL, headers=headers, timeout=15)
        if response.status_code == 401:
            log(f"{CROSS} ERROR 401: Token expired! Perlu refresh token.")
            return (401, None)
        elif response.status_code == 403:
            log(f"{CROSS} ERROR 403: Forbidden. Periksa token.")
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
    """
    Ambil data HMR hari ini.
    Return: list periode HMR atau [] jika gagal.
    """
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
    """
    Cek simbol mana yang sedang dalam periode HMR saat ini.
    Pola HMR dicocokkan ke SYMBOLS dengan presisi tinggi.
    Return: dict {symbol: (is_hmr, leverage, start_timestamp, end_timestamp)}
    """
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
    """
    Ambil berita ekonomi yang akan datang (volatility >= 2).
    Hanya ambil berita untuk HARI INI dan BESOK (48 jam ke depan).
    Return: tuple (today_news, tomorrow_news)
    """
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
    """Daftar simbol yang terpengaruh berita dari negara tertentu."""
    return COUNTRY_IMPACT_MAP.get(country_code, [])

def get_news_time_for_symbol(sym, news_list):
    """
    Mendapatkan waktu berita TERDEKAT yang mempengaruhi simbol tertentu.
    Return: tuple (display_string, volatility_tertinggi, count_di_jam_itu) atau (None, None, 0)
    """
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
    """
    Menentukan apa yang ditampilkan di kolom News.
    Prioritas: Berita hari ini > Tomorrow > ❌
    """
    news_display, _, _ = get_news_time_for_symbol(sym, today_news)
    if news_display is not None:
        return news_display
    
    tomorrow_display, _, _ = get_news_time_for_symbol(sym, tomorrow_news)
    if tomorrow_display is not None:
        return "Tomorrow "
    
    return "❌"

def calculate_candle_statistics(symbols_data, dxy_warning=False, data_status=None):
    """
    Menghitung statistik prediksi candle untuk semua simbol.
    DXY dikeluarkan dari perhitungan statistik jika dalam kondisi warning.
    """
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

def display_all_sentiments(symbols_data, dxy_warning=False, title="SENTIMEN SEMUA SIMBOL",
                           data_status=None, hmr_status=None, today_news=None, tomorrow_news=None,
                           prices=None):
    """
    Menampilkan SEMUA simbol dengan format bersih dan prediksi candle.
    
    KOLOM MARGIN: Leverage + persentase margin + rentang waktu (WIB)
                  Normal: "1:500 (0.2%)"
                  HMR Aktif: "⚠️ 1:30 (3.33%) 03/07 16:00 → 06/07 20:00"
    KOLOM NEWS: Jam berita hari ini > "Tomorrow" > "❌"
    KOLOM PRICE: Harga real-time dari RT-API, format sesuai pair
    """
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
            log(f"   Dominasi: Sinyal Bullish (NEWS) - Predict Going Up")
        elif candle_stats['bearish'] > candle_stats['bullish'] and candle_stats['bearish'] > candle_stats['sideways']:
            log(f"   Dominasi: Sinyal Bullish - Predict Going Up Multiple Pair")
            log(f"   Dominasi: Sinyal Bearish (NEWS) - Predict Going Down")
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
    """
    Menampilkan SEMUA berita HARI INI terdekat + analisis.
    Juga menampilkan ringkasan berita besok.
    """
    try:
        if today_news:
            sorted_news = sorted(today_news, key=lambda x: (x['time'], -x['volatility']))
            
            if sorted_news:
                first_news = sorted_news[0]
                target_time = first_news['time']
                
                same_time_news = []
                for n in sorted_news:
                    if n['time'] == target_time:
                        same_time_news.append(n)
                
                now = datetime.now(timezone.utc)
                time_left = target_time - now
                total_sec = int(time_left.total_seconds())
                hours, rem = divmod(total_sec, 3600)
                mins = rem // 60
                
                utc7_time = target_time + timedelta(hours=7)
                
                if len(same_time_news) == 1:
                    news = same_time_news[0]
                    impact_icon = "🔴" if news['volatility'] == 3 else "🟡"
                    log(f"\n📅 BERITA HARI INI: {news['name']} ({news['country']})")
                    log(f"   Negara: {news['country']} | Dampak: {impact_icon} {news['vol_label']}")
                else:
                    news_names = []
                    for n in same_time_news:
                        news_names.append(f"{n['name']} ({n['country']})")
                    
                    highest_vol = max(n['volatility'] for n in same_time_news)
                    impact_icon = "🔴" if highest_vol == 3 else "🟡"
                    
                    log(f"\n📅 BERITA HARI INI ({len(same_time_news)} berita):")
                    for name in news_names:
                        log(f"   • {name}")
                    log(f"   Dampak Tertinggi: {impact_icon} {'HIGH' if highest_vol == 3 else 'MEDIUM'}")
                
                log(f"   Waktu : {utc7_time.strftime('%d %b %H:%M')} WIB ({hours}j {mins}m lagi)")
                
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
                                
                                if "BUY" in sent_flag and consensus < previous:
                                    log(f"      ✅ KONFIRMASI: Sentimen & ekspektasi sama-sama Bearish")
                                elif "SELL" in sent_flag and consensus > previous:
                                    log(f"      ✅ KONFIRMASI: Sentimen & ekspektasi sama-sama Bullish")
                                elif "BUY" in sent_flag and consensus > previous:
                                    log(f"      ⚠️  KONTRADIKSI: Sentimen Bearish tapi ekspektasi Bullish")
                                elif "SELL" in sent_flag and consensus < previous:
                                    log(f"      ⚠️  KONTRADIKSI: Sentimen Bullish tapi ekspektasi Bearish")
                
                all_affected = set()
                for n in same_time_news:
                    all_affected.update(get_affected_symbols(n['country']))
                
                our_affected = sorted([s for s in SYMBOLS if s in all_affected])
                if our_affected:
                    log(f"   ⚠️  Pair terdampak: {', '.join(our_affected)}")
                
                if total_sec < 1800:
                    log(f"   🔴 HATI-HATI! Kurang dari 30 menit. JANGAN ENTRY!")
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
    """Menampilkan legenda untuk simbol dan flag."""
    safe_print("\n" + "="*65)
    safe_print("LEGENDA SIMBOL & PREDIKSI CANDLE")
    safe_print("")
    if not UNICODE_SUPPORT:
        safe_print(f"\n  {WARNING} Terminal tidak mendukung Unicode, menggunakan simbol ASCII")
    safe_print("="*65)
    safe_print("")

def find_chrome_path():
    """Cari path Chrome berdasarkan OS."""
    system = platform.system()
    paths = {
        "Windows": [
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe"),
        ],
        "Darwin": [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ],
        "Linux": [
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ],
    }
    for path in paths.get(system, []):
        if Path(path).exists():
            return path
    print("❌ Chrome tidak ditemukan. Pastikan Chrome terinstall.")
    print("   Coba cari manual dan masukkan path di variabel CHROME_PATH.")
    sys.exit(1)

def is_cdp_running():
    """Cek apakah Chrome dengan CDP sudah berjalan di port yang ditentukan."""
    try:
        response = requests.get(f"{CDP_URL}/json/version", timeout=2)
        return response.status_code == 200
    except:
        return False

def force_close_chrome():
    """Tutup paksa semua proses Chrome."""
    print("\n🔴 Menutup paksa Chrome...")
    try:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/f", "/im", "chrome.exe"], 
                         stdout=subprocess.DEVNULL, 
                         stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["pkill", "-f", "chrome"], 
                         stdout=subprocess.DEVNULL, 
                         stderr=subprocess.DEVNULL)
        time.sleep(2)
        print("   ✅ Chrome berhasil ditutup.")
    except Exception as e:
        print(f"   ⚠️  Gagal menutup Chrome: {e}")

def clean_chrome_history():
    """Membersihkan histori Chrome pada profil sementara."""
    global user_data_dir
    if not user_data_dir:
        print("❌ Path profil Chrome tidak diketahui.")
        return False

    profile_path = Path(user_data_dir)
    default_profile = profile_path / "Default"
    if not default_profile.exists():
        for item in profile_path.iterdir():
            if item.is_dir() and (item / "History").exists():
                default_profile = item
                break

    if not default_profile.exists():
        print(f"⚠️  Folder profil tidak ditemukan di: {profile_path}")
        return False

    print(f"\n🧹 Membersihkan histori Chrome...")
    print(f"   Profil: {default_profile}")

    files_to_delete = [
        "History", "History-journal", "Network Action Predictor",
        "Network Action Predictor-journal", "DownloadMetadata",
        "Shortcuts", "Shortcuts-journal", "Top Sites",
        "Top Sites-journal", "Visited Links", "Favicons", "Favicons-journal",
    ]
    for file_name in files_to_delete:
        file_path = default_profile / file_name
        if file_path.exists():
            try:
                file_path.unlink()
                print(f"   🗑️  Dihapus: {file_name}")
            except Exception as e:
                print(f"   ⚠️  Gagal menghapus {file_name}: {e}")

    cache_dirs = [
        "Cache", "Code Cache", "GPUCache", "Media Cache",
        "DawnGraphiteCache", "DawnWebGPUCache", "GrShaderCache", "ShaderCache",
    ]
    for dir_name in cache_dirs:
        dir_path = default_profile / dir_name
        if dir_path.exists():
            try:
                shutil.rmtree(dir_path, ignore_errors=True)
                print(f"   🗂️  Dihapus: {dir_name}/")
            except Exception as e:
                print(f"   ⚠️  Gagal menghapus folder {dir_name}: {e}")

    print("\n   ✅ Histori dibersihkan.")
    print("   🔒 Cookies, Local Storage, IndexedDB tetap utuh.")
    return True

def launch_chrome_with_cdp():
    """Jalankan Chrome dengan flag remote debugging."""
    global user_data_dir
    chrome_path = find_chrome_path()

    if platform.system() == "Windows":
        temp_dir = os.environ.get("TEMP", "C:\\Temp")
    else:
        temp_dir = "/tmp"
    user_data_dir = os.path.join(temp_dir, "chrome_debug_profile")

    cmd = [
        chrome_path,
        f"--remote-debugging-port={CHROME_DEBUG_PORT}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    try:
        if platform.system() == "Windows":
            subprocess.Popen(cmd, shell=False)
        else:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"❌ Gagal menjalankan Chrome: {e}")
        sys.exit(1)

    time.sleep(WAIT_AFTER_LAUNCH)

    if is_cdp_running():
        print("")
    else:
        time.sleep(3)
        if not is_cdp_running():
            sys.exit(1)

async def open_target_page():
    """Buka halaman target menggunakan Playwright via CDP."""
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"❌ Gagal terhubung ke CDP: {e}")
            return False

        contexts = browser.contexts
        if not contexts:
            print("❌ Tidak ada context. Chrome mungkin belum siap.")
            await browser.close()
            return False

        context = contexts[0]
        pages = context.pages
        if not pages:
            print("❌ Tidak ada tab terbuka sama sekali.")
            await browser.close()
            return False

        target_page = None
        for page in pages:
            if "ex-markets.pro" in page.url:
                target_page = page
                print(f"   ✅ Halaman target sudah terbuka: {page.url}")
                break

        if not target_page:
            existing_page = pages[0]
            for page in pages:
                if page.url == "about:blank":
                    existing_page = page
                    print("   📄 (about:blank)")
                    break
            try:
                await existing_page.goto(TARGET_URL, wait_until="networkidle", timeout=30000)
                target_page = existing_page
            except Exception as e:
                print(f"   ⚠️  Gagal navigasi: {e}")
                print("   ➕ Membuat tab baru sebagai fallback...")
                try:
                    target_page = await context.new_page()
                    await target_page.goto(TARGET_URL, wait_until="networkidle", timeout=30000)
                except Exception as e2:
                    print(f"   ❌ Gagal membuka halaman: {e2}")
                    await browser.close()
                    return False
        await browser.close()
        return True

def verify_cdp_json():
    """Buka dan tampilkan daftar tab dari CDP JSON endpoint."""
    try:
        response = requests.get(f"{CDP_URL}/json", timeout=5)
        tabs = response.json()
        for i, tab in enumerate(tabs, 1):
            title = tab.get("title", "No Title")
            url = tab.get("url", "No URL")
            print(f"   {i}. {title[:50]} | {url[:60]}")
        return True
    except Exception as e:
        print(f"❌ Fail to access url: {e}")
        return False

async def wait_for_login_and_capture():
    """
    Menunggu hingga user berhasil login (tidak lagi di halaman sign-in)
    dan kemudian menangkap token.
    """
    async with async_playwright() as p:
        print("\n" + "="*60)
        print("🔍 LOGIN & CAPTURE AUTH")
        print("="*60)

        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"   ❌ Gagal menghubungkan: {e}")
            return None

        contexts = browser.contexts
        if not contexts:
            print("   ❌ Tidak ada context terbuka.")
            await browser.close()
            return None

        context = contexts[0]
        
        target_page = None

        for page in context.pages:
            current_url = page.url

            is_login_page = "/accounts/sign-in" in current_url or "/login" in current_url
            is_trading_page = "/webtrading/" in current_url and not is_login_page

            if is_trading_page:
                target_page = page
                break
            elif is_login_page:
                target_page = page
                print("⚠️ Please login to your account")
                break

        if not target_page:
            print("   ➕ Tidak ada tab yang sesuai. Membuka halaman baru...")
            target_page = await context.new_page()
            await target_page.goto(TARGET_URL, wait_until="networkidle")
            print(f"   ✅ Halaman terbuka: {target_page.url}")

        login_detected = False
        check_count = 0

        while not login_detected:
            check_count += 1
            current_url = target_page.url
            timestamp = datetime.now().strftime("%H:%M:%S")

            print(f"\n Still waiting for login...")
            print(f"   🔗 URL saat ini: {current_url[:120]}")

            is_login_page = "/accounts/sign-in" in current_url or "/login" in current_url
            is_trading_page = "/webtrading/" in current_url and not is_login_page

            if is_trading_page:
                login_detected = True
                break
            elif is_login_page:
                if check_count == 1:
                    print("   💡 Please login to ur account")
            else:
                print(f"   🔍 Berada di halaman lain: {current_url[:100]}")
                try:
                    await target_page.goto(TARGET_URL, wait_until="networkidle", timeout=10000)
                    await asyncio.sleep(2)
                    new_url = target_page.url
                    if "/webtrading/" in new_url and "/accounts/sign-in" not in new_url:
                        print("   ✅ Berhasil navigasi ke webtrading!")
                        login_detected = True
                        break
                except Exception as e:
                    print(f"   ⚠️  Gagal navigasi: {e}")

            if check_count >= (WAIT_AFTER_RELOAD // 5):
                check_count = 0

            await asyncio.sleep(5)

        print(f"\n✅ Login confirmed ! Get token...")
        await asyncio.sleep(WAIT_AFTER_RELOAD)
        
        await target_page.reload(wait_until="networkidle")
        
        captured_auths = []
        
        def on_request(request):
            url = request.url
            if "all/" in url or "sentiment" in url.lower() or "api" in url.lower():
                headers = request.headers
                auth = (
                    headers.get("authorization") or 
                    headers.get("Authorization") or 
                    ""
                )
                if auth and ("Bearer" in auth or "bearer" in auth):
                    if not any(a['authorization'] == auth for a in captured_auths):
                        print("\n" + "-"*60)
                        print(f"🎯 REQUEST TERTANGKAP!")
                        print(f"🔗 URL: {url}")
                        print(f"🔑 Authorization: {auth[:80]}...")

                        captured_auths.append({
                            "url": url,
                            "authorization": auth,
                            "timestamp": time.time()
                        })
        
        target_page.on("request", on_request)

        await target_page.reload(wait_until="networkidle")

        await asyncio.sleep(WAIT_AFTER_RELOAD)

        await browser.close()

        if captured_auths:
            for i, item in enumerate(captured_auths, 1):
                token_preview = item['authorization'][:80] + "..." if len(item['authorization']) > 80 else item['authorization']

            with open(TOKEN_FILE, "w") as f:
                f.write("=== HASIL TANGKAPAN AUTHORIZATION ===\n")
                f.write(f"Waktu: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                for i, item in enumerate(captured_auths, 1):
                    f.write(f"{i}. URL: {item['url']}\n")
                    f.write(f"   Token: {item['authorization']}\n\n")
            print(f"\n💾 Saved in: {TOKEN_FILE}")

            return captured_auths
        else:
            print("❌ Tidak ada request dengan token yang tertangkap.")
            print("\n📝 Troubleshooting:")
            print("   1. Pastikan halaman webtrading sudah terbuka sempurna")
            print("   2. Cek di Chrome DevTools (F12) > Network")
            print("   3. Cari request ke API dengan header 'Authorization: Bearer ...'")
            return None

def refresh_token():
    global JWT_TOKEN
    
    if not is_cdp_running():
        launch_chrome_with_cdp()
    
    success = asyncio.run(open_target_page())
    
    if not success:
        print("❌ Failed Open Target Page")
        force_close_chrome()
        return False
    
    verify_cdp_json()
    
    result = asyncio.run(wait_for_login_and_capture())
    
    force_close_chrome()
    
    if result:
        auth_header = result[0]['authorization']
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:]
        else:
            token = auth_header
        JWT_TOKEN = token
        save_token(token)
        clean_chrome_history()
        print(f"\n✅ Token Captured, Close Chrome and Clean History")
        return True
    else:
        print("⚠️  Cant capture token. Please try again")
        clean_chrome_history()
        return False

def main():
    global JWT_TOKEN, last_valid_data
    
    if platform.system() == "Windows":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass
    
    log("=" * 60)
    log("Sentiment Data Realtime Monitor")
    log(f"CSV Output: {CSV_FILE}")
    log(f"{len(SYMBOLS)} Symbols: {', '.join(SYMBOLS)}")
    log("=" * 60)
    
    display_legend()
    
    JWT_TOKEN = load_token()
    if not JWT_TOKEN:
        log(f"{WARNING} Token Not Found, start capture...")
        if not refresh_token():
            log(f"{CROSS} cant capture token. exit.")
            return
    
    log("\nTry connect API...")
    status, data = fetch_sentiment()
    if status == 401:
        log("Token invalid, mencoba refresh...")
        if refresh_token():
            status, data = fetch_sentiment()
        else:
            log(f"{CROSS} Token gagal diperbarui. Keluar.")
            return
    
    if status == 200 and data:
        symbols_data, data_status = find_matching_symbols(data)
        dxy_warning, dxy_reason = check_dxy_warning(symbols_data, data_status)
        candle_predictions, candle_stats = calculate_candle_statistics(symbols_data, dxy_warning, data_status)
        
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
                else:
                    log(f"{WARNING} Harga real-time: Gagal mengambil data harga")
            except Exception as e:
                log(f"{WARNING} Gagal fetch harga awal: {e}")
            
            display_all_sentiments(symbols_data, dxy_warning, "STATUS SENTIMEN AWAL", 
                                 data_status, hmr_status=hmr_status_init, 
                                 today_news=today_news_init, tomorrow_news=tomorrow_news_init,
                                 prices=prices_init)
            
            csv_predictions = {sym: pred['direction'] for sym, pred in candle_predictions.items()}
            write_csv(symbols_data, dxy_warning, data_status, csv_predictions)
        else:
            log(f"{WARNING} Tidak ada simbol yang cocok.")
    else:
        log(f"{WARNING} Gagal koneksi awal.")
    
    log("\nWait 60 Sec ...")
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
                os.system('cls' if os.name == 'nt' else 'clear')
                safe_print("\n=== LAYAR DIBERSIHKAN SETIAP 10 MENIT ===\n")
                display_legend()
                last_clear_time = time.time()

            status, data = fetch_sentiment()
            
            if status == 401:
                log("Token expired selama loop, mencoba refresh...")
                if refresh_token():
                    time.sleep(2)
                    status, data = fetch_sentiment()
                else:
                    log(f"{CROSS} Refresh token gagal, menunggu siklus berikutnya...")
                    continue
            
            if status == 200 and data:
                symbols_data, data_status = find_matching_symbols(data)
                dxy_warning, dxy_reason = check_dxy_warning(symbols_data, data_status)
                candle_predictions, candle_stats = calculate_candle_statistics(symbols_data, dxy_warning, data_status)
                
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
                except Exception as e:
                    pass
                
                if symbols_data:
                    if dxy_warning:
                        dxy_warning_cycles += 1
                        if not previous_dxy_warning:
                            log(f"\n{WARNING} DXY MULAI WARNING - SINYAL DXY TIDAK VALID!")
                        elif dxy_warning_cycles % 5 == 0:
                            log(f"{WARNING} DXY sudah warning selama {dxy_warning_cycles} siklus ({dxy_warning_cycles} menit)")
                    else:
                        if dxy_warning_cycles > 0:
                            log(f"\n{CHECK} DXY KEMBALI NORMAL setelah {dxy_warning_cycles} menit warning")
                        dxy_warning_cycles = 0
                    
                    previous_dxy_warning = dxy_warning
                    
                    title = "SENTIMEN SIKLUS"
                    if dxy_warning:
                        title += " [DXY WARNING]"
                    
                    display_all_sentiments(symbols_data, dxy_warning, title, 
                                         data_status,
                                         hmr_status=hmr_status,
                                         today_news=today_news,
                                         tomorrow_news=tomorrow_news,
                                         prices=prices)
                    
                    if cycle_count == 1 or (dxy_warning_cycles == 1 and dxy_warning) or (dxy_warning_cycles == 0 and not dxy_warning and cycle_count > 1):
                        (dxy_warning, dxy_reason)
                    
                    try:
                        display_news_and_hmr(hmr_data, symbols_data, today_news=today_news, tomorrow_news=tomorrow_news)
                    except Exception as e:
                        log(f"{WARNING} Modul berita error (tidak menghentikan bot): {e}")
                    
                    print()
                    
                    csv_predictions = {sym: pred['direction'] for sym, pred in candle_predictions.items()}
                    write_csv(symbols_data, dxy_warning, data_status, csv_predictions)
                else:
                    log(f"{WARNING} Tidak ada simbol yang cocok.")
            else:
                log(f"{WARNING} Gagal fetch (status: {status}), mencoba lagi...")
                
        except KeyboardInterrupt:
            log("\nDihentikan oleh pengguna.")
            log(f"Total siklus: {cycle_count}")
            log(f"Total siklus DXY warning: {dxy_warning_cycles}")
            if cycle_count > 0:
                log(f"Persentase DXY normal: {((cycle_count-dxy_warning_cycles)/cycle_count*100):.1f}%")
            break
        except Exception as e:
            log(f"{CROSS} Error tidak terduga: {e}")
            log("Melanjutkan ke siklus berikutnya...")
            time.sleep(5)

if __name__ == "__main__":
    main()