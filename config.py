"""
Central config. Everything here is read from environment variables so no
secrets ever live in source control. Set these in your shell, a local .env
(loaded via `python-dotenv` if you add it), or your OS's env var manager.

Required:
  GOOGLE_SHEET_ID              - the long ID from the sheet's URL (raw OHLCV
                                   pull: Index_Daily* / Universe_OHLCV* tabs,
                                   written by run_daily.py)
  GOOGLE_SERVICE_ACCOUNT_PATH  - path to the service account JSON key file

Optional (sensible defaults given):
  QT_TOKEN_STORE   - where the rotating Questrade refresh token is cached
  QT_PRACTICE      - set to "1" to hit practicelogin.questrade.com instead
                      of login.questrade.com (paper/demo account)
  QT_LOOKBACK_DAYS - calendar days of history to pull per run (default 10,
                      ~7 trading days). For a one-time backfill to support
                      SMA50/ATR14/20-day-average calculations, temporarily
                      set this much higher (e.g. 140) for a single run,
                      then unset it so normal daily runs go back to the
                      small incremental window -- there's no dedup yet, so
                      a large window every day would balloon duplicate rows.
  MARKET           - "TSX" (default) or "NASDAQ". Picks the universe file,
                      index proxy, Sheet tab names, and price/volume
                      thresholds below. Same codebase runs both markets;
                      only this switch changes. Set it once per shell
                      session before running any script:
                        Windows:  set MARKET=NASDAQ
                        bash:     export MARKET=NASDAQ
  GOOGLE_OUTPUT_SHEET_ID - the sheet the aggressive screens' final
                      shortlist gets written to (write_list_agg.py). This
                      is a SEPARATE spreadsheet from GOOGLE_SHEET_ID above
                      -- Abe tracks screen results on their own, away from
                      the raw daily OHLCV pull. TSX writes to its
                      List_agg tab there, Nasdaq to List_agg_NASDAQ --
                      same spreadsheet, separate tabs, so the two markets'
                      shortlists never mix in one table. Defaults to
                      Abe's results-tracking sheet; the service account
                      (see GOOGLE_SERVICE_ACCOUNT_PATH's client_email)
                      must be shared on it as an Editor, same as
                      GOOGLE_SHEET_ID.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_SERVICE_ACCOUNT_PATH = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_PATH", "service_account.json"
)

# Where the aggressive screens' final candidate shortlist (List_agg /
# List_agg_NASDAQ) gets written -- separate from GOOGLE_SHEET_ID, which
# holds the raw OHLCV pull. Override with an env var if you ever want to
# point results somewhere else without touching this file.
GOOGLE_OUTPUT_SHEET_ID = os.environ.get(
    "GOOGLE_OUTPUT_SHEET_ID", "12B85W-6NHXhROMg50tHAG3OVxSz16OssCzM1iDMbSW8"
)

QT_TOKEN_STORE = os.environ.get("QT_TOKEN_STORE", "token_store.json")
QT_PRACTICE = os.environ.get("QT_PRACTICE", "0") == "1"
QT_LOOKBACK_DAYS = int(os.environ.get("QT_LOOKBACK_DAYS", "10"))

# --- market switch -----------------------------------------------------
MARKET = os.environ.get("MARKET", "TSX").upper()

_MARKET_DEFAULTS = {
    "TSX": dict(
        UNIVERSE_CSV="universe.csv",
        INDEX_PROXY_TICKER="XIC",
        LISTING_EXCHANGE="TSX",
        INDEX_TAB="Index_Daily",
        UNIVERSE_TAB="Universe_OHLCV",
        LIST_AGG_TAB="List_agg",
        PRICE_MIN=5.0,
        DOLLAR_VOLUME_MIN=5_000_000,
        CURRENCY="CAD",
        # TSX symbols sometimes only resolve under a ".TO"-suffixed form;
        # query both bare and suffixed forms (see questrade_client.py).
        USES_TO_SUFFIX=True,
        # Canadian preferred shares/debentures follow a dot-segment naming
        # convention (RY.PR.O, TD.PFA.TO, CSU.DB.TO, ...) that the exclusion
        # logic in questrade_client.py is built around.
        BLOCK_PREFERRED_SEGMENTS=True,
    ),
    "NASDAQ": dict(
        UNIVERSE_CSV="universe_nasdaq.csv",
        # ONEQ (Fidelity Nasdaq Composite Index ETF) -- the closest liquid,
        # single-symbol proxy for the ~1,000-name Nasdaq Composite, same
        # role XIC plays for the TSX Composite. Swap here if you'd rather
        # track QQQ (Nasdaq-100) instead.
        INDEX_PROXY_TICKER="ONEQ",
        LISTING_EXCHANGE="NASDAQ",
        INDEX_TAB="Index_Daily_NASDAQ",
        UNIVERSE_TAB="Universe_OHLCV_NASDAQ",
        LIST_AGG_TAB="List_agg_NASDAQ",
        PRICE_MIN=5.0,
        # Higher than TSX's $5M CAD: Nasdaq names trade at materially higher
        # average dollar volume, so $5M there would pass a lot of names
        # that aren't actually liquid by Nasdaq standards.
        DOLLAR_VOLUME_MIN=10_000_000,
        CURRENCY="USD",
        # US common stock isn't suffixed the way TSX's ".TO" convention
        # works -- querying a ".TO" variant for a Nasdaq ticker would just
        # waste a lookup.
        USES_TO_SUFFIX=False,
        # Not yet empirically verified against Questrade's actual Nasdaq
        # symbol table. US preferred shares/units typically use a hyphen
        # convention (e.g. "BAC-PB") rather than TSX's dot-segment style,
        # so the TSX exclusion logic likely doesn't apply as-is and may
        # need its own pass once real symbol-resolution output is seen
        # (the same iterative diagnose-then-fix approach used for TSX).
        # Left off for now rather than guessing.
        BLOCK_PREFERRED_SEGMENTS=False,
    ),
}

if MARKET not in _MARKET_DEFAULTS:
    raise ValueError(
        f"Unknown MARKET '{MARKET}'. Expected one of: {', '.join(_MARKET_DEFAULTS)}"
    )

_defaults = _MARKET_DEFAULTS[MARKET]

UNIVERSE_CSV = os.environ.get("UNIVERSE_CSV", _defaults["UNIVERSE_CSV"])
INDEX_PROXY_TICKER = os.environ.get("INDEX_PROXY_TICKER", _defaults["INDEX_PROXY_TICKER"])
LISTING_EXCHANGE = _defaults["LISTING_EXCHANGE"]
INDEX_TAB = _defaults["INDEX_TAB"]
UNIVERSE_TAB = _defaults["UNIVERSE_TAB"]
LIST_AGG_TAB = _defaults["LIST_AGG_TAB"]
PRICE_MIN = _defaults["PRICE_MIN"]
DOLLAR_VOLUME_MIN = _defaults["DOLLAR_VOLUME_MIN"]
CURRENCY = _defaults["CURRENCY"]
USES_TO_SUFFIX = _defaults["USES_TO_SUFFIX"]
BLOCK_PREFERRED_SEGMENTS = _defaults["BLOCK_PREFERRED_SEGMENTS"]
