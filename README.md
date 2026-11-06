# Sentiment Mobile

📊 Broker Realtime Sentiment & News Monitor

A real-time monitoring tool for Broker trading platform that tracks sentiment data (buy/sell percentages) across multiple trading pairs, provides candle direction predictions, economic news alerts, High Margin Requirement (HMR) status, and live prices — all updated every 60 seconds.

✨ Features

- 12 Trading Symbols Monitored: XAUUSD, DXY, USDJPY, XAGUSD, EURUSD, GBPUSD, AUDUSD, NZDUSD, USDCAD, USDCHF, BTCUSD, ETHUSD
- Candle Direction Prediction: 
  - ⬆ Bullish (Sell ≥ 60%)
  - ⬇ Bearish (Buy ≥ 60%)
  - ⇕ Sideways (Balanced)
- Sentiment Flags: 🟢 BUY / 🔴 SELL / ⚪ BALANCE
- Live Prices: Real-time bid prices from broker RT-API
- HMR Status: Displays temporary leverage changes with time range (WIB/GMT+7)
- Economic News: Today's & tomorrow's high-impact news with:
  - Time remaining countdown
  - Consensus vs Previous analysis
  - Affected pairs identification
  - Sentiment confirmation/contradiction checks
- DXY Warning System: Invalid DXY data triggers "NO ENTRY" recommendation
- Statistics Dashboard: Bullish/Bearish/Sideways dominance percentages


Installation:

pip install -r requirements.txt

- playwright>=1.40.0
- requests>=2.28.0


How to Use in Termux:

1. Type one by one:
```bash
   termux-setup-storage
```
```bash
   pkg update -y && pkg upgrade -y && pkg install git -y
```
2. Paste into Termux to download the data:

```bash
git clone https://github.com/Unknown-Desert/Sentiment.git
```

Target Result:

Make sure there is Sentiment folder

```bash
ls
```
Open Folder:

```bash
cd Sentiment
```
Make sure there are install.sh + sen.py

```bash
ls -All
```

Run or if already:

1. Only once for the first install:
```bash
sh install.sh
```
2. Every time you want to run the code:
```bash
python sen.py
```

📊 Sample Output

<img width="738" height="530" alt="Output" src="https://github.com/user-attachments/assets/f20e98bf-3bba-4204-be03-2a27c621ac70" />


Optional:

- Change into ur Language


⚠️ Disclaimer
This project is developed for educational and research purposes only. It demonstrates the application of sentiment analysis and market indicators in generating trading signals.

- Not Financial Advice: This system is not intended to provide financial advice. Any trading decisions made based on the outputs of this system are at your own risk.
- No Guarantees: There are no guarantees of profit or freedom from loss. Algorithmic trading carries significant risks, and past performance (especially with synthetic data) is not indicative of future results.
- Real-Money Trading: This system is not designed for direct real-money trading without substantial modifications, rigorous testing, and adherence to regulatory requirements. Always consult with a qualified financial professional before making any investment decisions.
