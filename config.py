"""
Central config. Everything here is read from environment variables so no
secrets ever live in source control. Set these in your shell, a local .env
(loaded via `python-dotenv` if you add it), or your OS's env var manager.

Required:
  GOOGLE_SHEET_ID              - the long ID from the sheet's URL
  GOOGLE_SERVICE_ACCOUNT_PATH  - path to the service account JSON key file

Optional (sensible defaults given):
  QT_TOKEN_STORE   - where the rotating Questrade refresh token is cached
  QT_PRACTICE      - set to "1" to hit practicelogin.questrade.com instead
                      of login.questrade.com (paper/demo account)
"""

import os

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_SERVICE_ACCOUNT_PATH = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_PATH", "service_account.json"
)

QT_TOKEN_STORE = os.environ.get("QT_TOKEN_STORE", "token_store.json")
QT_PRACTICE = os.environ.get("QT_PRACTICE", "0") == "1"

UNIVERSE_CSV = os.environ.get("UNIVERSE_CSV", "universe.csv")

# Proxy symbol used to represent the S&P/TSX Composite for the regime-gate
# calculation. Questrade's REST API is account/security-data oriented and
# doesn't cleanly expose the raw index level the way a market-data vendor
# does, so we track the composite via a highly-correlated, liquid ETF
# instead. XIC.TO (iShares Core S&P/TSX Capped Composite Index ETF) is the
# default. Swap this for another proxy if you prefer.
INDEX_PROXY_TICKER = os.environ.get("INDEX_PROXY_TICKER", "XIC")
