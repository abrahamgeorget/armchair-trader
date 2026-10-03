import csv
import math
from datetime import datetime, timezone
from statistics import median


def percentile_rank(values, current):
    if not values:
        return 0.0
    if len(values) == 1:
        return 100.0
    sorted_values = sorted(values)
    less = sum(1 for v in sorted_values if v < current)
    equal = sum(1 for v in sorted_values if v == current)
    pct = ((less + 0.5 * equal) / len(sorted_values)) * 100.0
    return max(0.0, min(100.0, pct))


def compute_atr(highs, lows, closes, period=14):
    if len(closes) < 2:
        return 0.0
    tr_values = []
    for i in range(len(closes)):
        if i == 0:
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]) if i > 0 else 0.0, abs(lows[i] - closes[i - 1]) if i > 0 else 0.0)
        else:
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        tr_values.append(tr)
    if len(tr_values) < period:
        return sum(tr_values) / len(tr_values)
    return sum(tr_values[-period:]) / period


def compute_20d_median_volume(rows):
    if not rows:
        return 0.0
    volumes = [float(r["volume"]) for r in rows[-20:]]
    return median(volumes) if volumes else 0.0


def score_candidates(data_by_ticker):
    scored = []
    for ticker, rows in data_by_ticker.items():
        if not rows:
            continue
        rows_sorted = sorted(rows, key=lambda r: r["date"])
        closes = [float(r["close"]) for r in rows_sorted]
        highs = [float(r["high"]) for r in rows_sorted]
        lows = [float(r["low"]) for r in rows_sorted]
        volumes = [float(r["volume"]) for r in rows_sorted]
        prev_close = closes[-1]
        if prev_close <= 0:
            continue

        median_volume = compute_20d_median_volume(rows_sorted)
        volume_ratio = (volumes[-1] / median_volume) if median_volume > 0 else 0.0
        atr = compute_atr(highs, lows, closes, period=14)
        atr_pct = (atr / prev_close) * 100.0 if prev_close else 0.0
        distance_to_high = (prev_close - max(highs[-20:])) / max(atr, 1e-9) if max(highs[-20:], default=prev_close) else 0.0
        ret_10 = ((closes[-1] / closes[-10]) - 1.0) * 100.0 if len(closes) >= 10 else 0.0
        ret_20 = ((closes[-1] / closes[-20]) - 1.0) * 100.0 if len(closes) >= 20 else 0.0
        momentum = 0.5 * ret_10 + 0.5 * ret_20

        if len(closes) >= 20:
            structure_score = max(0.0, min(100.0, ((max(highs[-20:]) - prev_close) / max(atr, 1e-9)) * 100.0))
        else:
            structure_score = 50.0

        dollar_volume = prev_close * volumes[-1]
        if dollar_volume <= 0:
            continue

        quality = 100.0
        momentum_component = momentum
        volume_component = min(volume_ratio, 4.0) / 4.0 * 100.0
        liquidity_component = 0.0
        structure_component = structure_score

        scored.append(
            {
                "ticker": ticker,
                "score": 0.0,
                "momentum": momentum_component,
                "volume": volume_component,
                "structure": structure_component,
                "liquidity": liquidity_component,
                "quality": quality,
                "atr_pct": atr_pct,
                "entry": prev_close,
                "target": prev_close + 2.5 * atr,
                "stop": prev_close - 1.5 * atr,
                "shares": 0,
                "target_upside_pct": 0.0,
                "catalyst": "",
                "catalyst_url": "",
            }
        )

    if not scored:
        return []

    momentum_values = [r["momentum"] for r in scored]
    volume_values = [r["volume"] for r in scored]
    structure_values = [r["structure"] for r in scored]
    liquidity_values = [r["liquidity"] for r in scored]
    quality_values = [r["quality"] for r in scored]

    for row in scored:
        row["momentum_score"] = percentile_rank(momentum_values, row["momentum"])
        row["volume_score"] = percentile_rank(volume_values, row["volume"])
        row["structure_score"] = percentile_rank(structure_values, row["structure"])
        row["liquidity_score"] = percentile_rank(liquidity_values, row["liquidity"])
        row["quality_score"] = percentile_rank(quality_values, row["quality"])
        row["score"] = (
            0.30 * row["momentum_score"]
            + 0.25 * row["volume_score"]
            + 0.25 * row["structure_score"]
            + 0.10 * row["liquidity_score"]
            + 0.10 * row["quality_score"]
        )

    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored


def run_screen(csv_path: str, output_path: str):
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        raw_rows = list(reader)

    data_by_ticker = {}
    for row in raw_rows:
        ticker = (row.get("ticker") or row.get("Ticker") or "").strip()
        if not ticker:
            continue
        data = data_by_ticker.setdefault(ticker, [])
        data.append(
            {
                "date": row.get("date") or row.get("Date") or "",
                "close": float(row.get("close") or row.get("Close") or 0.0),
                "high": float(row.get("high") or row.get("High") or 0.0),
                "low": float(row.get("low") or row.get("Low") or 0.0),
                "volume": float(row.get("volume") or row.get("Volume") or 0.0),
            }
        )

    rows = score_candidates(data_by_ticker)
    rows = [
        {
            "ticker": r["ticker"],
            "score": round(r["score"], 2),
            "atr_pct": round(r["atr_pct"], 2),
            "entry": round(r["entry"], 2),
            "target": round(r["target"], 2),
            "stop": round(r["stop"], 2),
            "shares": r["shares"],
            "target_upside_pct": round(r["target_upside_pct"], 2),
            "catalyst": r["catalyst"],
            "catalyst_url": r["catalyst_url"],
        }
        for r in rows
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "ticker",
                "score",
                "atr_pct",
                "entry",
                "target",
                "stop",
                "shares",
                "target_upside_pct",
                "catalyst",
                "catalyst_url",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} candidates to {output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the qsx-stock-aggresive screen")
    parser.add_argument("csv", help="CSV of ticker-level OHLCV rows")
    parser.add_argument("-o", "--output", default="candidate_output.csv", help="Output CSV path")
    args = parser.parse_args()
    run_screen(args.csv, args.output)
