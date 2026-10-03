"""
Runs the aggressive score-the-whole-universe screen against whichever
market config.MARKET currently points at (TSX by default, or NASDAQ if
you set MARKET=NASDAQ before running). Same scoring engine
(qsx_stock_aggresive.score_candidates) for both -- only the universe
source tab, price/volume thresholds, and output filename differ.
"""

import csv
from collections import defaultdict

import gspread
from google.oauth2.service_account import Credentials

from qsx_stock_aggresive import score_candidates
import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def load_universe_data():
    creds = Credentials.from_service_account_file(config.GOOGLE_SERVICE_ACCOUNT_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(config.GOOGLE_SHEET_ID)
    ws = sh.worksheet(config.UNIVERSE_TAB)
    rows = ws.get_all_values()
    if not rows:
        raise RuntimeError(f"{config.UNIVERSE_TAB} is empty")
    header = rows[0]
    dedup = {}
    for r in rows[1:]:
        if len(r) < len(header):
            r = r + [""] * (len(header) - len(r))
        row = dict(zip(header, r))
        key = (row.get("ticker", "").strip(), row.get("date", "").strip())
        if key:
            dedup[key] = row

    by_ticker = defaultdict(list)
    for row in dedup.values():
        ticker = row.get("ticker", "").strip()
        if not ticker:
            continue
        by_ticker[ticker].append(
            {
                "date": row.get("date", "").strip(),
                "close": float(row.get("close", 0) or 0),
                "high": float(row.get("high", 0) or 0),
                "low": float(row.get("low", 0) or 0),
                "volume": float(row.get("volume", 0) or 0),
            }
        )

    return by_ticker


def filter_universe(by_ticker):
    passing = {}
    for ticker, data in by_ticker.items():
        ordered = sorted(data, key=lambda d: d["date"])
        if len(ordered) < 60:
            continue
        last = ordered[-1]
        if last["close"] < config.PRICE_MIN:
            continue
        recent = ordered[-20:]
        median_vol = sorted(d["volume"] for d in recent)[len(recent) // 2]
        if median_vol * last["close"] < config.DOLLAR_VOLUME_MIN:
            continue
        passing[ticker] = ordered
    return passing


def build_output_rows(scored_rows):
    output = []
    for r in scored_rows:
        if r["score"] < 70 or r["atr_pct"] < 2.0:
            continue
        output.append(
            {
                "ticker": r["ticker"],
                "score": round(r["score"], 2),
                "atr_pct": round(r["atr_pct"], 2),
                "entry": round(r["entry"], 2),
                "target": round(r["target"], 2),
                "stop": round(r["stop"], 2),
                "shares": 0,
                "target_upside_pct": 0.0,
                "catalyst": "",
                "catalyst_url": "",
            }
        )
    return output


def main():
    print(f"Market: {config.MARKET}  (tab '{config.UNIVERSE_TAB}', "
          f"price >= {config.PRICE_MIN} {config.CURRENCY}, "
          f"20d $ volume >= {config.DOLLAR_VOLUME_MIN:,} {config.CURRENCY})")

    by_ticker = load_universe_data()
    passing = filter_universe(by_ticker)
    scored = score_candidates(passing)
    rows = build_output_rows(scored)

    output_path = "qsx_candidates.csv" if config.MARKET == "TSX" else f"qsx_candidates_{config.MARKET.lower()}.csv"
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "ticker", "score", "atr_pct", "entry", "target", "stop",
                "shares", "target_upside_pct", "catalyst", "catalyst_url",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Universe candidates considered: {len(passing)}")
    print(f"Passed hard gate: {len(rows)}")
    for r in rows[:10]:
        print(r["ticker"], r["score"], r["atr_pct"], r["entry"], r["target"], r["stop"])

    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
