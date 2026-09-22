# SENSEX 9:15 Paper Research Recorder

## What this is
A RESEARCH-ONLY data-collection system. It records SENSEX and 14 option
contracts from 09:15:00 to 09:16:00 IST each trading day, to study opening
behaviour and test hypotheses about an Instagram creator's undisclosed
9:15 options scalping strategy. NO LIVE TRADING. Never add order placement.

## Pipeline (runs unattended via systemd)
sensex-915.timer (08:55 IST weekdays) -> sensex-915.service -> daily_run.sh
  1. morning_runner.py   - TOTP login to Dhan, generates DHAN_ACCESS_TOKEN,
                           launches the recorder as a subprocess
  2. record_915_session.py - fetches option chain at ~09:14:30, picks
                           ATM +/-300 strikes (CE+PE), records WebSocket ticks
  3. daily_summary.py    - appends one row per session to summary.csv
  4. daily_publisher.py  - git add <date folder> + summary.csv, commit, push

Python venv: ~/sensex-915-recorder/.venv/bin/python
record_915_session.py cannot run standalone: the token only exists inside
morning_runner.py's subprocess environment.

## Data
<YYYY-MM-DD>/session_contracts_*.json  - contract map; from 2026-09-21 also
                                         iv, delta, gamma, theta, vega,
                                         top_bid, top_ask, oi (09:14:30 snapshot)
<YYYY-MM-DD>/session_ticks_*.csv       - all ticks; depth_json is quoted JSON
                                         (use Python csv, never awk -F',')
summary.csv                            - one row per session

packet_type: "Ticker Data" = SENSEX (id 51), "Full Data" = options,
"Previous Close" = one-off snapshot, always exclude.

## Rules
1. Research only. Never place orders or add trading logic.
2. Keep LTT (exchange time, 1-second precision) and local_time (receipt time,
   ms precision) separate. Millisecond claims cannot be verified from LTT.
3. chain_ltp (09:14:30 snapshot) is not the same as live LTP.
4. Do not forward-fill missing ticks unless explicitly asked.
5. Never read, print, or modify ~/.dhan_env (contains PIN and TOTP secret).
6. Do not edit record_915_session.py, morning_runner.py or daily_run.sh
   on a weekday between 08:50 and 09:20 IST.
7. Run python3 -m py_compile on any edited script before committing.
8. Do not draw conclusions from a handful of sessions.

## Research status (as of 2026-09-18, 4 sessions)
Tested and NOT supported:
- Fixed "buy ATM+100 CE at open, +15 target": 2 wins, 2 larger losses
- SENSEX direction as signal: Sep 18 index +27 but CE -70
- Order-book bid/ask imbalance (sec 0-7): 2/4, no better than chance
Open lead: winners were DTE 0-1, losers DTE 2 and 6. IV capture added
2026-09-21 to test whether IV/theta explains the divergence.
Creator reference trade: SENSEX 74300 CE, expiry 17 SEP 26, entry 288.25,
exit 306.80. Best candidate match is the 2026-09-16 session.
