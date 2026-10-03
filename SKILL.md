---
name: qsx-stock-aggresive
description: "Aggressive TSX screen that skips the regime gate and sector-qualification gate and scores the ENTIRE passing universe directly, then verifies real catalysts for the top scorers. Sources OHLCV from Abe's Google Sheet (Qtrade, sheet ID 1EUxwETtZwj71K5TnIAjxXzuQvbLvBPbwwVHRTn7xP4s), same as qtrade-daily-tsx. Use this when Abe explicitly asks to bypass the regime/sector gates, wants candidates regardless of market conditions, or invokes it by name."
---

# TSX Aggressive Screen — no regime gate, no sector gate (on-demand, chat-only)

This is a deliberately more permissive sibling of `qtrade-daily-tsx`. That skill's Stage 1 (regime gate) and Stage 3 (sector qualification) exist specifically to keep the pipeline out of unfavorable conditions — this skill skips both by design and scores the whole universe directly. **That's a real trade-off, not a bug**: it will surface candidates on days `qtrade-daily-tsx` would call NO TRADE, including days when the broader market or an individual name's sector is weak. Say so plainly in every report this skill produces — don't let the candidate list imply "the market is favorable" when it hasn't been checked.

Every data-sourcing rule, universe filter, scoring formula/weights, hard gate, and risk-sizing formula is otherwise **identical** to `qtrade-daily-tsx`. If the scoring logic changes, update both skills together.

## Ground rules (identical to qtrade-daily-tsx)

- **Sheet is the data source.** Sheet ID: `1EUxwETtZwj71K5TnIAjxXzuQvbLvBPbwwVHRTn7xP4s`. Two tabs: `Index_Daily` (XIC, the Composite proxy) and `Universe_OHLCV` (date, ticker, open, high, low, close, volume).
- **Download the full workbook** via the Drive download tool with `exportMimeType: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` — don't rely on a markdown preview, which truncates on a sheet this size.
- **Dedup on (ticker, date), keep the last occurrence** — `run_daily.py` only appends and has no dedup logic.
- **Freshness check.** Compare the latest date in `Index_Daily` to today. If stale by more than one trading day, say so explicitly and name it as the likely reason (Abe hasn't rerun `run_daily.py` today).
- **History-length reality check.** Verify per-ticker row counts after dedup are comfortably above 60 trading days before scoring; if not, say so and stop rather than scoring on thin history.
- **Sector classification** comes from the most recent XIC holdings export (has a Sector column) if Abe has one on hand or uploads one — needed for the Momentum sub-score's "relative strength vs. own sector" calculation, even though this skill doesn't gate on sector qualification the way `qtrade-daily-tsx` does.
- **Universe list** is whatever tickers are in `Universe_OHLCV` — reflects Abe's `universe.csv`, not a live pull from a public source; note if it looks stale.
- **Compute indicators from real data via code execution**, never from narrative snippets. If code execution isn't available, say so and scale down rather than eyeballing numbers.
- **Search budget:** top 3 results per catalyst query. Unresolved stays unresolved, not broadened.
- **Market day check:** if today is a weekend or TSX holiday, still note that fact — but unlike `qtrade-daily-tsx`, don't stop the analysis solely for this reason unless Abe wants live/current data specifically. If the Sheet's most recent session is the relevant reference point regardless of today's calendar status, proceed and say so.

## Pipeline

**1. Universe filter (same as qtrade-daily-tsx Stage 2).** From the tickers in `Universe_OHLCV`: price ≥ $5.00 CAD, 20-day median dollar volume ≥ $5,000,000 CAD, ≥60 trading days of history post-dedup. Note pass/fail counts.

**2. Score the entire passing universe directly — no sector gate.** For every name that passes the universe filter, regardless of its sector's relative performance: Momentum 30% (relative strength vs. own sector, blended 10-day/20-day return — this still needs the sector mapping, just not sector qualification), Volume 25% (session volume ÷ 20-day avg, capped at 4.0x), Structure 25% (distance to 20-day high, normalized by ATR14), Liquidity 10% (dollar-volume percentile within the passing universe), Quality 10% (exclusion-based only — see caveat below). Scale each sub-component to 0–100 via percentile rank within the scored set; note this is a reasonable implementation choice since the exact scaling isn't spelled out mechanically, and a different choice would shift exact scores somewhat.

Note explicitly: **Quality defaults to 100 for every name** unless a specific exclusion is confirmed — checking halted/cease-trade/M&A/going-concern/earnings-in-10-days status for the whole scored universe isn't practical here, so nothing has actually been screened out on Quality grounds at this stage. Say this in the report.

**3. Hard gates — score ≥70 AND ATR14 ≥2.0% of price.** Take everything that clears both as the shortlist to catalyst-check. If the resulting list is large (>15), say so and either narrow to the top-scoring subset within budget or ask Abe how many to check.

**4. Catalyst verification — real web searches, real fetches, resolvable URLs, applied strictly.** For each name from step 3: search for company news, verify the actual dated announcement (not just an article discussing an old announcement), and require the event itself — not commentary about it — to fall within the last 3 trading days. Distinguish a genuine catalyst (earnings, guidance change, analyst revision, or material-change news) from routine noise (a dividend approval, a generic "stock in focus" piece with no new information, an automated technical-signals report). When a name is a genuine borderline call (an event that would've been fresh as of a hypothetical earlier entry point but has aged past the window by the time of verification), say so explicitly rather than silently deciding either way. A name with a qualifying score but no verifiable fresh catalyst is excluded, not scored down — name the specific reason per exclusion (no catalyst found vs. catalyst too old vs. only routine items found).

**5. Reference risk sizing (informational only — no trade is ever executed).** Ask Abe for notional if not given; default to $100,000 CAD if he doesn't specify one, and flag if a much smaller notional (e.g. $100 per name) will produce fractional-share, impractical results rather than silently presenting it as realistic. effective_stop = 1.75 × ATR14; risk_per_trade = 1% of notional; shares = (0.01 × notional) ÷ effective_stop; entry = prev_close + 0.5 × ATR14; target = entry + 2.5 × ATR14; stop-loss = entry − 1.5 × ATR14.

**6. Report.** List every name that cleared step 4, each with: the catalyst in plain language plus its source URL and date, the score breakdown, the bear case, what would invalidate the setup, and the reference entry/target/stop from step 5. Rank by whatever Abe asked for (score, target upside, etc.) and be explicit about what the ranking metric actually measures — a formula-derived target from ATR is not a prediction of future performance, and should never be presented as one. Close with: (a) the same data-quality note as qtrade-daily-tsx, and (b) an explicit one-line reminder that this run did not check the regime gate or sector-level conditions — the shortlist reflects individual-name setups only, evaluated independently of whether the broader market or the name's sector currently supports new positions.

**7. Write the candidate table to the `List_agg` tab, after every run.** Columns: ticker, score, atr_pct, entry, target, stop, shares, target_upside_pct, catalyst, catalyst_url. This writes to Abe's separate **results-tracking sheet** (`config.GOOGLE_OUTPUT_SHEET_ID`, sheet ID `12B85W-6NHXhROMg50tHAG3OVxSz16OssCzM1iDMbSW8`) — not the Questrade OHLCV sheet this skill reads from. It APPENDS each run as a new timestamped block ("Run: <when>" + header + rows) rather than clearing the tab, so `List_agg` accumulates a running history of every run's recommendations instead of only ever showing the latest one.

Capability check first: this step needs an actual Google Sheets cell-write path, which a plain chat session does NOT have (chat's Google Drive access is file-level only — read, download, copy, share — not cell-level Sheets writes). Check what's actually available before claiming to have done this:
- **Claude Code, run from the `questrade-sheets` project folder** (has the local `service_account.json` and `config.py`): write the candidates to a temp CSV matching the column order above, then run `python write_list_agg.py <csv path>`. This works today.
- **Plain chat session, no code execution or no local project access**: say plainly that this step can't be completed from here, and tell Abe to run `write_list_agg.py` himself (or ask him to switch to Claude Code) rather than silently skipping it or claiming it's done.

Never report step 7 as complete without it actually having happened.

Keep the whole report itself in the chat response — this is a one-off report, not a document to file anywhere. The Sheet write is the one persistent side effect this skill has.
