"""
One-off diagnostic: dump every candidate Questrade's prefix search
returns for a given ticker, unfiltered, so we can see exactly what's
available instead of guessing at naming conventions.

Usage: python debug_symbol.py ENB
"""

import sys
import requests
from questrade_client import QuestradeClient

ticker = sys.argv[1] if len(sys.argv) > 1 else "ENB"

qt = QuestradeClient()
qt.authenticate()

resp = requests.get(
    f"{qt.api_server}/v1/symbols/search",
    headers=qt._headers(),
    params={"prefix": ticker},
    timeout=30,
)
resp.raise_for_status()
symbols = resp.json().get("symbols", [])

print(f"{len(symbols)} results for prefix='{ticker}':")
for s in symbols:
    print(f"  {s['symbol']:20} | {s.get('listingExchange'):8} | {s.get('description')}")
