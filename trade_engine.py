# 📝 Nifty Trade Engine - Telegram Alert Enabled

## 📦 Install Dependencies (Handled in requirements.txt)
# beautifulsoup4, lxml, scipy, requests, pandas, numpy

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from datetime import datetime
from scipy.stats import norm
from math import log, sqrt, exp
import requests
import os
import time
import telegram

# 🌐 Telegram Bot Setup
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)

# 🌐 Fetch Option Chain from NSE

def fetch_nifty_chain():
    try:
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/option-chain",
        })

        _ = session.get("https://www.nseindia.com", timeout=5)
        response = session.get(url, timeout=5)

        if response.status_code != 200:
            print(f"❌ NSE fetch failed: HTTP {response.status_code}")
            return None

        data = response.json()
        records = data['records']['data']
        spot = data['records']['underlyingValue']

        rows = []
        for item in records:
            strike = item.get('strikePrice')
            for opt in ['CE', 'PE']:
                if opt in item:
                    row = item[opt]
                    row['Type'] = opt
                    row['Strike'] = strike
                    row['underlyingValue'] = spot
                    rows.append(row)

        df = pd.DataFrame(rows)
        df["LTP"] = pd.to_numeric(df["lastPrice"], errors="coerce")
        df["IV"] = pd.to_numeric(df["impliedVolatility"], errors="coerce")
        df["OI"] = pd.to_numeric(df["openInterest"], errors="coerce")
        df["Chg OI"] = pd.to_numeric(df["changeinOpenInterest"], errors="coerce")
        df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
        df["expiryDate"] = pd.to_datetime(df["expiryDate"], errors="coerce")
        return df.dropna()

    except Exception as e:
        print("❌ NSE fetch failed:", e)
        return None

# 🖌 ATM Strike

def get_atm_strike(df):
    spot = df['underlyingValue'].iloc[0]
    atm = round(spot / 50) * 50
    return spot, atm

# ✖️ Delta Calculator

def compute_bsm_delta(S, K, T, r, sigma, option_type):
    try:
        d1 = (log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt(T))
        if option_type == "CE":
            return norm.cdf(d1)
        else:
            return -norm.cdf(-d1)
    except:
        return 0

# 🧠 Trade Selection + Alert

def build_trade_alert(df):
    spot, atm_strike = get_atm_strike(df)
    T = 3 / 365
    r = 0.06
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    df = df[(df['Strike'].between(atm_strike - 500, atm_strike + 500)) & (df['LTP'] > 10)]
    df['Delta'] = df.apply(lambda row: compute_bsm_delta(spot, row['Strike'], T, r, row['IV'] / 100, row['Type']), axis=1)
    df['Theta'] = -np.abs(df['LTP'] / 7 * 10)

    df = df[df['LTP'] > 15]
    df = df.sort_values('LTP', ascending=False)

    alert_lines = [f"Trade Alert ({now}):\nSpot: {spot:.2f} | ATM: {atm_strike} !!! Potential Gamma Blast near ATM"]

    def format_row(row):
        return f"{int(row['Strike']):<6} | {row['LTP']:<7.2f} | {row['Delta']:<5.2f} | {row['Theta']:<6.1f}"

    for typ in ['CE', 'PE']:
        alert_lines.append(f"\n--- {typ} Top 10 ---\nStrike | LTP    | Delta | Theta")
        top_n = df[df['Type'] == typ].head(10)
        for _, row in top_n.iterrows():
            alert_lines.append(format_row(row))

    return split_message("\n".join(alert_lines))

# ✂️ Split large message

def split_message(msg, max_chars=3900):
    parts = []
    while len(msg) > max_chars:
        cut_index = msg.rfind('\n', 0, max_chars)
        if cut_index == -1:
            cut_index = max_chars
        parts.append(msg[:cut_index])
        msg = msg[cut_index:].lstrip('\n')
    if msg:
        parts.append(msg)
    return parts

# 🚀 Main Execution

def run_alert():
    df = fetch_nifty_chain()
    if df is not None:
        try:
            alerts = build_trade_alert(df)
            for msg in alerts:
                bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
                time.sleep(1)
        except Exception as e:
            print("❌ Telegram alert failed:", e)
    else:
        print("❌ Failed to fetch live data.")

if __name__ == "__main__":
    run_alert()
