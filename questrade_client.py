"""
Minimal Questrade REST client for the daily data pull.

Handles the one tricky part of this API: refresh tokens are SINGLE-USE.
Every time you redeem one, Questrade hands back a brand-new refresh token
that must be saved before you do anything else, or you lock yourself out
and have to re-authorize manually in the API Centre.

Symbol-resolution conventions (the ".TO" suffix querying, the preferred-
share/debenture exclusion logic) were built empirically against TSX names
and are gated behind config.USES_TO_SUFFIX / config.BLOCK_PREFERRED_SEGMENTS
so they don't misfire on other markets (e.g. NASDAQ) that use different
symbol-naming conventions. The exchange to match against
(config.LISTING_EXCHANGE) is likewise config-driven, not hardcoded.
"""

import json
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

import config

EASTERN = ZoneInfo("America/Toronto")


class QuestradeAuthError(RuntimeError):
    pass


class QuestradeClient:
    def __init__(self, token_store_path: str = None, practice: bool = None):
        self.token_store_path = token_store_path or config.QT_TOKEN_STORE
        self.practice = config.QT_PRACTICE if practice is None else practice
        self.access_token = None
        self.api_server = None

    # ---- auth -------------------------------------------------------

    def _token_host(self) -> str:
        return (
            "https://practicelogin.questrade.com"
            if self.practice
            else "https://login.questrade.com"
        )

    def _load_refresh_token(self) -> str:
        if not os.path.exists(self.token_store_path):
            raise QuestradeAuthError(
                f"No token store at {self.token_store_path}. "
                "Seed it once with: "
                '{\"refresh_token\": \"<token from API Centre>\"}'
            )
        with open(self.token_store_path) as f:
            data = json.load(f)
        rt = data.get("refresh_token")
        if not rt:
            raise QuestradeAuthError(f"{self.token_store_path} has no refresh_token key.")
        return rt

    def _save_refresh_token(self, refresh_token: str) -> None:
        with open(self.token_store_path, "w") as f:
            json.dump(
                {"refresh_token": refresh_token, "saved_at": time.time()}, f, indent=2
            )

    def authenticate(self) -> None:
        refresh_token = self._load_refresh_token()
        url = f"{self._token_host()}/oauth2/token"
        resp = requests.get(
            url,
            params={"grant_type": "refresh_token", "refresh_token": refresh_token},
            timeout=30,
        )
        if resp.status_code != 200:
            raise QuestradeAuthError(
                f"Token refresh failed ({resp.status_code}): {resp.text}\n"
                "Your stored refresh_token is likely stale or already used. "
                "Generate a new manual authorization token in the API Centre "
                f"and reseed {self.token_store_path}."
            )
        data = resp.json()

        # Save the NEW refresh token immediately, before making any other
        # call, so a later failure never strands us on a burned token.
        self._save_refresh_token(data["refresh_token"])

        self.access_token = data["access_token"]
        self.api_server = data["api_server"].rstrip("/")

    def _headers(self) -> dict:
        if not self.access_token:
            raise QuestradeAuthError("Call authenticate() before making requests.")
        return {"Authorization": f"Bearer {self.access_token}"}

    # ---- data calls ---------------------------------------------------

    def get_symbol_ids_bulk(self, tickers: list[str]) -> dict:
        """
        Resolve exact symbolIds for a list of tickers in as few calls as
        possible, using Questrade's exact-name lookup (GET /v1/symbols?names=...)
        rather than prefix search.

        This matters because prefix search returns EVERY security that
        starts with the ticker string -- preferred share series
        (TD.PF.J.TO), subordinated debentures (CSU.DB.TO), rights,
        warrants, etc. -- and picking the "right" one from that list
        requires guessing at naming conventions that differ security by
        security. Exact-name lookup sidesteps the guessing entirely: it
        either finds the literal symbol you asked for, or it doesn't.

        The listing-exchange to require (config.LISTING_EXCHANGE) and
        whether to also try a ".TO"-suffixed form (config.USES_TO_SUFFIX)
        are both config-driven so this works for TSX and NASDAQ without
        two copies of this method.

        Returns {ticker: symbolId or None}.
        """
        results = {}
        exchange = config.LISTING_EXCHANGE
        try_suffix = config.USES_TO_SUFFIX
        CHUNK = 25 if try_suffix else 50  # no suffix variant halves the query list
        for i in range(0, len(tickers), CHUNK):
            chunk = tickers[i : i + CHUNK]
            query_names = list(chunk)
            if try_suffix:
                query_names += [f"{t}.TO" for t in chunk]
            resp = requests.get(
                f"{self.api_server}/v1/symbols",
                headers=self._headers(),
                params={"names": ",".join(query_names)},
                timeout=30,
            )
            resp.raise_for_status()
            found = {s["symbol"].upper(): s for s in resp.json().get("symbols", [])}
            for t in chunk:
                # Check both the bare and (if applicable) suffixed forms,
                # don't short-circuit on whichever exists first -- a
                # bare-ticker cross-listing on another exchange must not
                # shadow a valid match for the exchange we actually want.
                bare = found.get(t.upper())
                suffixed = found.get(f"{t.upper()}.TO") if try_suffix else None
                match = next(
                    (c for c in (bare, suffixed) if c and c.get("listingExchange") == exchange),
                    None,
                )
                if match:
                    print(f"  matched {t} -> {match['symbol']} \"{match.get('description', '?')}\" (symbolId={match['symbolId']})")
                    results[t] = match["symbolId"]
                elif bare or suffixed:
                    wrong = bare or suffixed
                    print(
                        f"  rejected exact match for {t} -> {wrong['symbol']} "
                        f"\"{wrong.get('description', '?')}\" listed on {wrong.get('listingExchange')} "
                        f"(not {exchange}) -- will try prefix search instead"
                    )
                    results[t] = None
                else:
                    results[t] = None
        return results

    def _search_and_filter(self, prefix: str, base_ticker: str) -> int | None:
        """
        Run one prefix search and return the best plausible common-equity
        match, or None. Shared by the broad and narrowed search attempts
        in get_symbol_id_by_prefix.
        """
        resp = requests.get(
            f"{self.api_server}/v1/symbols/search",
            headers=self._headers(),
            params={"prefix": prefix},
            timeout=30,
        )
        resp.raise_for_status()
        symbols = resp.json().get("symbols", [])
        if not symbols:
            return None

        exchange = config.LISTING_EXCHANGE

        # Prefixes that mark a segment as preferred shares, debentures,
        # notes, rights, or warrants -- not common equity. This is a TSX
        # naming convention (dot-separated segments); gated behind
        # config.BLOCK_PREFERRED_SEGMENTS since it hasn't been verified
        # against how Questrade names the equivalent NASDAQ security types.
        BLOCKED_SEGMENT_PREFIXES = ("PF", "PR", "DB", "WT", "RT", "DEB", "NT", "MRP")

        def is_equity_symbol(symbol: str) -> bool:
            if not config.BLOCK_PREFERRED_SEGMENTS:
                return True
            segments = symbol.upper().split(".")
            tail = segments[1:]
            if tail and tail[-1] == "TO":
                tail = tail[:-1]
            for seg in tail:
                if any(seg.startswith(p) for p in BLOCKED_SEGMENT_PREFIXES):
                    return False
            return True

        candidates = [
            s for s in symbols
            if s.get("listingExchange") == exchange and is_equity_symbol(s["symbol"])
        ]
        if not candidates:
            return None

        for s in candidates:
            sym_norm = s["symbol"].upper().replace(".", "-")
            if sym_norm.split("-")[0] == base_ticker:
                print(
                    f"  WARN: loose prefix match for {base_ticker} -> {s['symbol']} "
                    f"\"{s.get('description', '?')}\" (symbolId={s['symbolId']}) -- verify this is correct"
                )
                return s["symbolId"]
        return None

    def get_symbol_id_by_prefix(self, ticker: str) -> int | None:
        """
        Fallback for tickers the exact-name lookup couldn't resolve
        (e.g. a separator-convention mismatch between your universe CSV
        and Questrade's actual symbol string, or a bare-ticker collision
        with a cross-listing on another exchange).

        Excludes non-equity security types by checking each dot-separated
        symbol SEGMENT for a blocked prefix, rather than matching a fixed
        substring -- when config.BLOCK_PREFERRED_SEGMENTS is on (TSX).
        This matters because Questrade uses inconsistent naming across
        companies for the same security type -- e.g. preferred shares show
        up as both "TD.PF.J.TO" (PF as its own segment) and "TD.PFA.TO"
        (PFA fused as one token, no separating dot) for the SAME company.
        A substring check for ".PF." catches the first form and silently
        misses the second. Segment-prefix checking catches both, and any
        other naming variant that starts the same way.

        If the broad prefix search comes back with nothing usable, retries
        with a narrower "{ticker}.T" prefix (TSX) or "{ticker}" itself is
        already narrow for NASDAQ where this retry adds little -- it's
        cheap to try regardless. This matters for companies with enough
        outstanding preferred series to fill the API's 20-result cap
        before the alphabetically-later common stock is ever reached
        (e.g. Enbridge alone has 19 preferred series, all sorting before
        "ENB.TO").
        """
        base = ticker.upper().replace(".", "-").split("-")[0]

        result = self._search_and_filter(ticker, base)
        if result is not None:
            return result

        narrow_prefix = f"{ticker}.T" if config.USES_TO_SUFFIX else ticker
        if narrow_prefix != ticker:
            result = self._search_and_filter(narrow_prefix, base)
            if result is not None:
                print(f"  (found {ticker} via narrowed '.T' prefix -- broad search was likely crowded out by preferred series)")
                return result

        print(f"  WARN: no plausible {config.LISTING_EXCHANGE} equity match for {ticker} via prefix search")
        return None

    def get_daily_candles(self, symbol_id: int, lookback_days: int = 10) -> list[dict]:
        """
        Daily OHLCV candles for the trailing `lookback_days` calendar days.

        Access tokens expire after ~30 minutes, but authenticate() only runs
        once at the start of a script. A short TSX run (215 tickers) easily
        finishes inside that window; a full Nasdaq run (~1,000 tickers) can
        outlast it, and every call made after expiry gets 401 Unauthorized --
        not because those tickers are broken, but because the whole session's
        token went stale. If that happens, re-authenticate once (this also
        redeems and re-saves a fresh refresh token, same as any other
        authenticate() call) and retry this one request before giving up.
        """
        try:
            return self._fetch_candles(symbol_id, lookback_days)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                print("  access token expired mid-run -- re-authenticating and retrying...")
                self.authenticate()
                return self._fetch_candles(symbol_id, lookback_days)
            raise

    def _fetch_candles(self, symbol_id: int, lookback_days: int) -> list[dict]:
        end = datetime.now(EASTERN)
        start = end - timedelta(days=lookback_days)
        resp = requests.get(
            f"{self.api_server}/v1/markets/candles/{symbol_id}",
            headers=self._headers(),
            params={
                "startTime": start.isoformat(timespec="seconds"),
                "endTime": end.isoformat(timespec="seconds"),
                "interval": "OneDay",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("candles", [])
