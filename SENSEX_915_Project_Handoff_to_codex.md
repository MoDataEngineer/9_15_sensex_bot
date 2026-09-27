# SENSEX 9:15 Paper Research Recorder — Project Handoff

**Purpose of this document:** portable context for continuing this project with
another AI assistant. Read this fully before making any changes.

## 0. CRITICAL RULES — READ FIRST

1. **This is a research/data-collection system. NO LIVE TRADING.** Never add
   order placement, broker execution, or any code that could send an order.
2. Do not assume the creator's full strategy from a screenshot or video clip.
   Verify against multiple examples before treating anything as a rule.
3. Keep **LTT** (exchange timestamp, 1-second precision) and **local_time**
   (local receipt timestamp, millisecond precision) conceptually separate.
   Claims more precise than 1 second cannot be verified from LTT alone.
4. `chain_ltp` (the option-chain snapshot at ~09:14:30, pre-market) is NOT the
   same as live `LTP` from the WebSocket ticks during 09:15:00–09:16:00.
5. Do not forward-fill missing tick observations unless explicitly requested.
   Missing seconds should show as blank/N/A.
6. Never read, print, or modify `~/.dhan_env` on the VM — it contains the
   Dhan PIN and TOTP secret used for daily authentication.
7. Do not edit `record_915_session.py`, `morning_runner.py`, or `daily_run.sh`
   on a weekday between 08:50–09:20 IST (the live recording window).
8. Run `python3 -m py_compile <file>` on any edited Python script before
   committing.
9. Do not draw strategy conclusions from a handful of sessions. Wait for
   volume before treating any pattern as validated.

## 1. Project Goal

Record SENSEX opening behavior around **09:15:00–09:16:00 IST** on trading
days — SENSEX ticks, 14 nearby option contracts (ATM ±300 in 100-point
steps, CE+PE), timestamps, LTP, volume, bid/ask depth — in order to
**reverse-engineer and objectively test** an Instagram creator's undisclosed
9:15 SENSEX options scalping strategy, without ever placing real orders.

## 2. Infrastructure

- **VM:** Oracle Cloud, Ubuntu 24.04 LTS, ARM64 (`VM.Standard.A1.Flex`, 1
  OCPU), region ap-mumbai-1, instance name `sensex-915-recorder`
- **Public IP:** `137.23.48.129` — **Reserved** (converted from ephemeral on
  2026-09-18, so it survives instance stop/start)
- **SSH:** user `ubuntu`, key-based auth, key at
  `F:\oracle cloud\ssh_key\private_key\ssh-key-2026-09-13.key` (local
  Windows machine). VS Code Remote-SSH is configured (host alias
  `sensex-vm` in `~/.ssh/config` on the laptop).
- **Project directory on VM:** `~/sensex-915-recorder/9_15_sensex_bot`
- **Python venv:** `~/sensex-915-recorder/.venv/bin/python`
- **Data source:** Dhan (`dhanhq` package), REST option-chain API +
  WebSocket market feed
- **Auth:** `~/.dhan_env` holds `DHAN_CLIENT_ID`, `DHAN_PIN`,
  `DHAN_TOTP_SECRET`. A fresh `DHAN_ACCESS_TOKEN` is generated each run via
  TOTP login (see `morning_runner.py`) — **there is no long-lived stored
  token**, so `record_915_session.py` cannot run standalone; it must be
  launched as a subprocess of `morning_runner.py`, which injects the token
  into its environment.
- **Scheduling:** systemd (`sensex-915.timer` fires ~08:55 IST weekdays →
  `sensex-915.service` → `daily_run.sh`)
- **Publishing:** automated `git add/commit/push` to
  `github.com/MoDataEngineer/9_15_sensex_bot` after each run
- **Claude Code:** was installed on the VM (`curl -fsSL
  https://claude.ai/install.sh | bash`) for direct terminal-based AI access
  to the project, but subscription access was later disabled at the org
  level — currently unusable until re-enabled or an API key is provided.
  A `CLAUDE.md` file exists in the repo root with condensed project context
  for whichever AI tool works in that terminal (Claude Code, Codex, etc.).

## 3. Pipeline (runs unattended)

```
sensex-915.timer (08:55 IST, weekdays)
  → sensex-915.service
    → daily_run.sh
      1. morning_runner.py   — TOTP login to Dhan, generates
                                DHAN_ACCESS_TOKEN, launches recorder
      2. record_915_session.py
                              — fetches option chain ~09:14:30, selects
                                ATM ±300 strikes (14 contracts), connects
                                WebSocket pre-open, records ticks from
                                09:15:00 to 09:16:00 IST
      3. daily_summary.py    — appends one row per session to summary.csv
                                (idempotent — skips dates already present)
      4. daily_publisher.py  — git add <date folder> + summary.csv,
                                commit, push (idempotent — prints
                                "ALREADY PUBLISHED" if nothing changed)
```

`daily_run.sh` checks for NSE holidays / missing dataset folders and exits
cleanly (exit 0) on non-trading days without publishing anything.

## 4. Data Schema

### `<YYYY-MM-DD>/session_contracts_*.json`
Contract map + reference snapshot taken at ~09:14:30 (pre-market):
```
created_at, record_start, record_end, expiry, reference_spot, reference_atm,
strikes (offset list), contracts: [
  { strike, option_type, security_id, chain_ltp,
    iv, delta, gamma, theta, vega,       ← added 2026-09-21
    top_bid, top_ask, oi }               ← added 2026-09-21
],
sensex: { security_id: 51, exchange_segment: "IDX_I", feed_type: "Ticker" },
options: { exchange_segment: "BSE_FNO", feed_type: "Full", depth_levels: 5 }
```
**Note:** `top_bid`/`top_ask` are expected to be 0 in this snapshot — it's
taken before market open, so there's no live order book yet. This is normal,
not a bug. `iv`/Greeks at this timestamp reflect *yesterday's* option price
against *this morning's* spot, so treat them as a rough pre-open baseline,
not the true opening IV.

**One known bad file:** `2026-09-14/session_contracts_2026-09-14_sample.json`
has a completely different schema (keys: `sample`, `description`,
`underlying`, `recording_start`/`recording_end`) — it's leftover test/demo
data, not a real session. Any script reading contract files should skip
files missing `reference_atm`/`contracts` keys rather than crashing.

### `<YYYY-MM-DD>/session_ticks_*.csv`
```
local_time, local_ns, monotonic_ns, packet_type, exchange_segment,
security_id, LTP, LTQ, LTT, avg_price, volume, total_sell_quantity,
total_buy_quantity, OI, depth_json
```
- `packet_type`: `"Ticker Data"` = SENSEX (id 51), `"Full Data"` = options,
  `"Previous Close"` = one-off pre-open snapshot — **always exclude this**.
- `depth_json` is a **quoted JSON string containing commas** — never parse
  the CSV with `awk -F','`; use Python's `csv` module.
- `depth_json` structure: array of 5 levels, each
  `{bid_quantity, ask_quantity, bid_orders, ask_orders, bid_price, ask_price}`.
- `LTT` has 1-second precision only. `local_time`/`local_ns` have
  millisecond+ precision (local receipt time, not exchange time).

### `summary.csv` (repo root, one row per session)
```
session_date, expiry, dte, atm, ref_spot,
sensex_open, sensex_15s, sensex_move,
ce_strike, ce_open, ce_15s, ce_move, ce_min, ce_max,
book_ratio_0_7,
ce_iv, ce_delta, ce_theta, ce_vega        ← blank for sessions before 2026-09-21
```
Generated/appended by `daily_summary.py`. `ce_*` fields always refer to the
**ATM+100 CE** for that day (not a fixed strike). `book_ratio_0_7` is
aggregate bid-qty ÷ aggregate ask-qty across seconds 0–7, summed over all
depth levels.

## 5. Sessions Recorded So Far

| Date | DTE | ATM | SENSEX move (0→15s) | ATM+100 CE move | book_ratio_0_7 |
|---|---|---|---|---|---|
| 2026-09-15 | 2 | 75400 | −159.48 | −56.4 | 0.61 |
| 2026-09-16 | 1 | 74200 | +30.34 | +45.5 | 1.88 |
| 2026-09-17 | 0 | 74200 | +130.64 | +70.5 | 0.56 |
| 2026-09-18 | 6 | 74600 | +27.08 | −70.0 | 1.58 |
| 2026-09-21 | 3 | 74500 | +128.57 | +54.35 | 0.94 |
| 2026-09-22 | 2 | 74900 | +50.97 | −0.95 | 0.74 |

(2026-09-11 and 2026-09-14 folders exist but were not part of the analyzed
set — 09-14 is the known bad/sample file above; 09-11 was not reviewed.)

## 6. Analysis Tools (all in repo root on the VM)

- **`analyze_sessions.py`** — per-session opening-minute breakdown (open,
  +1s/+5s/+10s/+12s/+15s/+30s/+60s, min/max) for every recorded instrument.
  No forward-fill; missing seconds show as N/A.
- **`depth_analysis.py`** — prints bid/ask quantities, ratio, spread, and
  order counts per second for a given security_id, seconds 0–12.
- **`daily_summary.py`** — the idempotent summary-row generator described
  above.
- **`scan_trade_match.py`** — scans all sessions' tick data for a specific
  three-stage price sequence (entry price → drawdown low → target price, in
  chronological order) to test whether a creator-reference trade might be
  sitting in the recorded dataset on an untried strike/day. Currently
  parameterized for the 236.15 → 220.25 → 251.15 sequence (see §8) —
  returned **no matches** across all 7 sessions as of 2026-09-22.

## 7. Hypotheses Tested Against Recorded Data (as of 6 sessions)

All tested using the ATM+100 CE unless noted. **None have been validated —
this is a record of what has been ruled out, not what works.**

1. **Fixed "buy ATM+100 CE at open, target +15 points"** — 2 wins, 2 losses,
   and the losses (−56, −70) were larger than the target. Net negative
   expectancy on this tiny sample.
2. **SENSEX direction as the signal** (does CE follow index direction?) —
   held on 3/4 early sessions but broke on 2026-09-18 (index +27, CE −70).
   Direction alone is insufficient.
3. **Order-book bid/ask imbalance (seconds 0–7) as a leading indicator** —
   looked perfect on the first 2 sessions (clean separation, ratio <0.9 on
   the down day vs >1.05 on the up day), but inverted on the next 2 sessions
   (most ask-heavy day went UP, most bid-heavy day went DOWN). Ruled out —
   no better than chance across 4 sessions.
4. **DTE (days to expiry) as a filter** (winners at DTE 0–1, losers at DTE
   2/6) — looked promising on the first 4 sessions but broke on
   2026-09-21 (DTE 3, CE +54, a clear win) and 2026-09-22 (DTE 2, CE ≈flat).
   No longer holds cleanly.
5. **Delta/gamma/vega decomposition** (current best lead, only tested on
   the 2 sessions with Greeks data so far):
   `predicted_move = delta × sensex_move + 0.5 × gamma × sensex_move²`
   `gap = actual_ce_move − predicted_move`
   `implied_iv_change ≈ gap ÷ vega`
   - 2026-09-21: gap ≈ −1.4 → implied IV change ≈ −0.05 (negligible;
     delta alone explained the move almost exactly)
   - 2026-09-22: gap ≈ −24.4 → implied IV change ≈ −0.99 (a real IV crush
     appears to explain why the CE barely moved despite the index rising)
   - **Working theory:** opening-minute option price = delta/gamma-implied
     move from the index, minus a day-varying IV crush. If true, the real
     research question becomes *what predicts the size/direction of the
     IV crush*, not the index move itself.
   - This needs many more sessions with Greeks data before being trusted.
     IV/Greeks capture only started 2026-09-21, so there are only 2 data
     points for this theory as of writing.

## 8. Creator Reference Trades (external evidence, not from our recorder)

### Trade A — likely matched to 2026-09-16 session
From a screenshot: **SENSEX 74300 CE**, expiry **17 SEP 26**, qty 200,
entry **288.25**, exit **306.80** (+18.55 pts), target label "+15", exit
timestamp ~09:15:12.415 (unverifiable to the millisecond — LTT only has
1-second precision).

Matching evidence found in our 2026-09-16 data (ATM was 74200 that day, so
74300 = ATM+100):
```
09:15:04.186   LTP 288.10   (≈ entry 288.25)
09:15:11.736   LTP 307.40   (≈ exit 306.80)
```
Expiry matches exactly. This is the strongest evidence linking a specific
recorded session to a specific creator trade so far.

### Trade B — NOT matched in any recorded session
From a video: entry **≈236.15**, drawdown low **≈220.25** (−15.9 pts, this
IS the max adverse excursion shown on-screen, i.e. "Max Drawdown: 15.90 pts"
before the trade turned around), target hit at **≈251.15** (+15 pts),
qty 140, displayed P&L +₹1,932, order confirmation showed instrument name
truncated as "SENSEX26SEP7…" (possibly the Sept-24 monthly expiry, unverified).

`scan_trade_match.py` searched all 7 recorded sessions for this exact
236.15 → 220.25 → 251.15 sequence (±0.5 tolerance) on any of the 14+
tracked contracts per day. **No match found.** Either this trade happened
on a day/strike outside our recorded window, or the on-screen prices are
rounded/derived in a way that doesn't correspond exactly to raw tick data.

**Combined takeaway from A+B:** both examples show the strategy tolerating
significant adverse movement (Trade A implicitly, Trade B explicitly at
15.9 points against) before a ~15-point target is hit. Neither example
shows evidence of a tight stop-loss. Risking ~16 points to make ~15 implies
the strategy needs a win rate well above 50% (after costs) to be profitable
— this has NOT been tested statistically, only observed in two winning
examples.

## 9. Known Limitations

- Recording window is only 09:15:00–09:16:00 (60 seconds). Trade B's
  observed timeline (drawdown then recovery to target) may not always
  resolve within 60 seconds — a longer window (e.g. to 09:20:00) may be
  needed to capture full trade lifecycles, at the cost of ~4–5x larger
  daily files.
- IV/Greeks are a single pre-market snapshot (~09:14:30), not a live
  stream during the recording window — genuine tick-by-tick IV requires
  back-solving from LTP via Black-Scholes, which has not been built yet.
- Sample size (6–7 usable sessions as of 2026-09-22) is far too small to
  validate any hypothesis. Every "finding" above should be treated as
  provisional until re-tested on 15–20+ sessions.
- No IV surface is possible (only one expiry is recorded per session);
  at most an IV smile across the 7 recorded strikes for that day.

## 10. Suggested Next Steps

1. **Keep collecting** — the pipeline runs unattended; just let it
   accumulate sessions. Re-test hypotheses #4 and #5 once 15–20 sessions
   with Greeks data exist.
2. Consider extending `RECORD_END_TIME` in `record_915_session.py` from
   09:16:00 to something like 09:20:00 to capture full trade lifecycles
   (do this outside the 08:50–09:20 window, per rule #7 above).
3. Build a Black-Scholes back-solve script to estimate tick-by-tick implied
   vol during the recording window, to test the delta/gamma/vega theory
   (§7.5) more rigorously than the single pre-open snapshot allows.
4. If the creator posts more examples — especially a **losing trade** —
   that would reveal whether a stop-loss exists and how large it is, which
   neither Trade A nor Trade B (both winners) can show.
5. Do not attempt a 5×5 target/stop grid search (or any multi-parameter
   optimization) until there are 20+ sessions — on 6 sessions it will
   overfit and produce a misleadingly good-looking result by chance.
