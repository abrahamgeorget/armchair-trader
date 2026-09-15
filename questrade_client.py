"""
Minimal Questrade REST client for the daily data pull.

Handles the one tricky part of this API: refresh tokens are SINGLE-USE.
Every time you redeem one, Questrade hands back a brand-new refresh token
that must be saved before you do anything else, or you lock yourself out
and have to re-authorize manually in the API Centre.
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

    def get_symbol_id(self, ticker: str) -> int | None:
        """Look up Questrade's internal symbolId for a TSX ticker."""
        resp = requests.get(
            f"{self.api_server}/v1/symbols/search",
            headers=self._headers(),
            params={"prefix": ticker},
            timeout=30,
        )
        resp.raise_for_status()
        symbols = resp.json().get("symbols", [])
        if not symbols:
            return None
        base = ticker.split(".")[0].upper()
        for s in symbols:
            if s["symbol"].split(".")[0].upper() == base:
                return s["symbolId"]
        # fall back to first hit if no exact prefix match
        return symbols[0]["symbolId"]

    def get_daily_candles(self, symbol_id: int, lookback_days: int = 10) -> list[dict]:
        """Daily OHLCV candles for the trailing `lookback_days` calendar days."""
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
