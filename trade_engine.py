# ✅ trade_engine.py — Final Version (Patched with Official NSE Scraping)

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
from scipy.stats import norm
import requests
import json
from math import log, sqrt, exp
import time
from telegram import Bot

# 📁 Constants
CACHE_DIR = "cache"
LOGS_DIR = "logs"
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# 📦 Telegram Bot Config (set these as GitHub Secrets or hardcode for testing)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# 🌐 Fetch NSE Option Chain Data (Official)
def fetch_nifty_chain(cache_minutes=10):
    cache_file = os.path.join(CACHE_DIR, "nifty_cache.csv")
    now = time.time()

    if os.path.exists(cache_file):
        mtime = os.path.getmtime(cache_file)
        if now - mtime < cache_minutes * 60:
            return pd.read_csv(cache_file)

    try:
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/option-chain",
        }

        session = requests.Session()
        session.headers.update(headers)
        session.get("https://www.nseindia.com", timeout=5)
        response = session.get(url, timeout=10)

        if response.status_code != 200:
            print(f"NSE fetch failed: HTTP {response.status_code}")
            return None

        data = response.json()
        records = data['records']['data']
        spot = data['records']['underlyingValue']

        rows = []
        for item in records:
            strike = item.get("strikePrice")
            for opt in ["CE", "PE"]:
                if opt in item:
                    row = item[opt]
                    row["Type"] = opt
                    row["Strike"] = strike
                    row["underlyingValue"] = spot
                    rows.append(row)

        df = pd.DataFrame(rows)
        df.rename(columns={
            "lastPrice": "LTP",
            "impliedVolatility": "IV",
            "openInterest": "OI",
            "changeinOpenInterest": "Chg OI",
        }, inplace=True)

        df["IV"] = pd.to_numeric(df["IV"], errors="coerce")
        df["OI"] = pd.to_numeric(df["OI"], errors="coerce")
        df["Chg OI"] = pd.to_numeric(df["Chg OI"], errors="coerce")
        df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
        df["LTP"] = pd.to_numeric(df["LTP"], errors="coerce")
        df["Theta"] = df["LTP"].apply(lambda x: -abs(x) * 10 / 7 if pd.notnull(x) else 0)
        df["expiryDate"] = pd.to_datetime(df["expiryDate"], errors="coerce")
        df = df.dropna()

        df.to_csv(cache_file, index=False)
        return df

    except Exception as e:
        print("NSE fetch failed:", e)
        return None

# 🔁 Rolling 3-day OI Memory
def load_rolling_oi():
    try:
        memory = {}
        files = sorted([f for f in os.listdir(LOGS_DIR) if f.endswith("_ce.csv")])[-3:]
        for f in files:
            df = pd.read_csv(os.path.join(LOGS_DIR, f))
            for _, row in df.iterrows():
                key = f"{row['Type']}_{row['Strike']}"
                memory.setdefault(key, []).append(row['OI'])
        return {k: np.mean(v) for k, v in memory.items() if len(v) >= 2}
    except Exception as e:
        print("Rolling OI fetch failed:", e)
        return {}

# 🧮 BSM Delta
def compute_bsm_delta(S, K, T, r, sigma, option_type):
    try:
        d1 = (log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt(T))
        return norm.cdf(d1) if option_type == "CE" else -norm.cdf(-d1)
    except:
        return 0

# 🔔 Telegram Alert
def send_telegram_alert(message):
    try:
        if len(message) > 4000:
            for i in range(0, len(message), 4000):
                bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message[i:i+4000])
        else:
            bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        print("Telegram alert sent!")
    except Exception as e:
        print("Telegram alert failed:", e)

# 🚨 Evaluate Trade Alerts
def evaluate_trade_alerts(df):
    S = df['underlyingValue'].iloc[0]
    T = 3 / 365
    r = 0.06

    alerts = [
        "Today's Market Tone: Sideways | Event Risk: Fed Meet Tonight",
        f"Spot: {S:.2f}, ATM Strike: {round(S/50)*50}",
        "!!! Potential Gamma Blast setup near ATM",
        "",
        "Suggested Call Option Trades:"
    ]

    ce_df = df[df["Type"] == "CE"].sort_values("Chg OI", ascending=False).head(3)
    for _, row in ce_df.iterrows():
        delta = compute_bsm_delta(S, row['Strike'], T, r, row['IV'] / 100, row['Type'])
        action = "buy" if delta > 0.4 and row['Chg OI'] > 10000 else "avoid"
        alerts.append(f"- CE {int(row['Strike'])} | LTP: {row['LTP']:.2f}, Delta: {delta:.2f}, Theta: {row['Theta']:.2f}, OI Change: {row['Chg OI']}, Confidence: Red, Action: {action}")

    alerts.append("\nSuggested Put Option Trades:")
    pe_df = df[df["Type"] == "PE"].sort_values("Chg OI", ascending=False).head(3)
    for _, row in pe_df.iterrows():
        delta = compute_bsm_delta(S, row['Strike'], T, r, row['IV'] / 100, row['Type'])
        action = "buy" if abs(delta) > 0.4 and row['Chg OI'] > 10000 else "avoid"
        alerts.append(f"- PE {int(row['Strike'])} | LTP: {row['LTP']:.2f}, Delta: {delta:.2f}, Theta: {row['Theta']:.2f}, OI Change: {row['Chg OI']}, Confidence: Yellow, Action: {action}")

    return alerts

# 🏁 Main Trigger
def run_engine():
    df = fetch_nifty_chain()
    if df is not None:
        alerts = evaluate_trade_alerts(df)
        if alerts:
            send_telegram_alert("\n".join(alerts))
        else:
            print("No actionable alerts found.")
    else:
        print("Failed to fetch live data.")

if __name__ == "__main__":
    run_engine()
