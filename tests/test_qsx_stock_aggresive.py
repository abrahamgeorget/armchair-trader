import math

from qsx_stock_aggresive import score_candidates


def test_score_candidates_filters_and_ranks():
    data = {
        "AAA": [
            {"date": "2024-01-01", "close": 10.0, "high": 10.5, "low": 9.6, "volume": 100_000},
            {"date": "2024-01-02", "close": 10.2, "high": 10.7, "low": 9.7, "volume": 120_000},
            {"date": "2024-01-03", "close": 10.4, "high": 10.9, "low": 9.8, "volume": 130_000},
            {"date": "2024-01-04", "close": 10.8, "high": 11.1, "low": 10.2, "volume": 150_000},
            {"date": "2024-01-05", "close": 11.0, "high": 11.2, "low": 10.6, "volume": 300_000},
            {"date": "2024-01-06", "close": 11.2, "high": 11.6, "low": 10.8, "volume": 200_000},
        ],
        "BBB": [
            {"date": "2024-01-01", "close": 20.0, "high": 20.8, "low": 19.2, "volume": 50_000},
            {"date": "2024-01-02", "close": 20.5, "high": 21.0, "low": 19.8, "volume": 60_000},
            {"date": "2024-01-03", "close": 20.8, "high": 21.2, "low": 20.0, "volume": 40_000},
            {"date": "2024-01-04", "close": 21.2, "high": 21.5, "low": 20.6, "volume": 90_000},
            {"date": "2024-01-05", "close": 21.8, "high": 22.3, "low": 21.0, "volume": 80_000},
            {"date": "2024-01-06", "close": 22.2, "high": 22.8, "low": 21.1, "volume": 70_000},
        ],
        "CCC": [
            {"date": "2024-01-01", "close": 50.0, "high": 51.0, "low": 49.1, "volume": 20_000},
            {"date": "2024-01-02", "close": 49.5, "high": 50.2, "low": 48.5, "volume": 15_000},
            {"date": "2024-01-03", "close": 48.8, "high": 49.6, "low": 47.9, "volume": 18_000},
            {"date": "2024-01-04", "close": 48.2, "high": 49.1, "low": 47.7, "volume": 25_000},
            {"date": "2024-01-05", "close": 47.6, "high": 48.4, "low": 46.8, "volume": 30_000},
            {"date": "2024-01-06", "close": 47.1, "high": 48.2, "low": 46.5, "volume": 35_000},
        ],
    }

    rows = score_candidates(data)

    assert len(rows) == 3
    assert rows[0]["ticker"] in {"AAA", "BBB", "CCC"}
    assert "score" in rows[0]
    assert all(r["score"] >= 0 for r in rows)
    assert all(r["atr_pct"] >= 0 for r in rows)
    assert all(math.isfinite(r["score"]) for r in rows)

    top = rows[0]
    assert top["score"] >= max(r["score"] for r in rows[1:])
