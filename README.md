# Sentiment

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
- CSV Export: Automatic data export for integration with other tools
- Auto Token Capture: JWT token extracted via Chrome DevTools Protocol
- Auto Token Refresh: Handles 401 errors by re-launching Chrome for re-login


Installation:

pip install -r requirements.txt

- playwright>=1.40.0
- requests>=2.28.0


📋 Prerequisites

- Python 3.7+
- Google Chrome (auto-detected, or specify path manually)
- Windows, macOS, or Linux
- Stable internet connection
- Active Exness trading account (for one-time manual login)



How To Use:

1. Download Sen.py
2. Run -> python Sen.py
3. Log-in your Exnees Account for once if needed
4. Then the datas will show:


📊 Sample Output

<img width="738" height="530" alt="Output" src="https://github.com/user-attachments/assets/f20e98bf-3bba-4204-be03-2a27c621ac70" />


Optional:

- Change into ur Language


⚠️ Disclaimer
This project is developed for educational and research purposes only. It demonstrates the application of sentiment analysis and market indicators in generating trading signals.

Not Financial Advice: This system is not intended to provide financial advice. Any trading decisions made based on the outputs of this system are at your own risk.
No Guarantees: There are no guarantees of profit or freedom from loss. Algorithmic trading carries significant risks, and past performance (especially with synthetic data) is not indicative of future results.
Real-Money Trading: This system is not designed for direct real-money trading without substantial modifications, rigorous testing, and adherence to regulatory requirements. Always consult with a qualified financial professional before making any investment decisions.
