#!/usr/bin/env python3
"""Append one summary row per session to summary.csv."""
import csv, json, glob, os, sys
from datetime import date

SUMMARY = "summary.csv"
HEADER = ["session_date","expiry","dte","atm","ref_spot",
          "sensex_open","sensex_15s","sensex_move",
          "ce_strike","ce_open","ce_15s","ce_move","ce_min","ce_max",
          "book_ratio_0_7"]

def at_second(ticks, sid, sec):
    """First tick whose LTT is exactly this second. No forward-fill."""
    for ltt, s, price, _ in ticks:
        if s == sid and ltt == sec:
            return price
    return None

def summarize(folder):
    cf = glob.glob(os.path.join(folder, "session_contracts_*.json"))
    tf = glob.glob(os.path.join(folder, "session_ticks_*.csv"))
    if not cf or not tf:
        print(f"{folder}: no data files, skipping")
        return None
    c = json.load(open(cf[0]))
    atm = c["reference_atm"]
    sensex_id = str(c["sensex"]["security_id"])

    ce_strike = atm + 100
    ce_id = None
    for k in c["contracts"]:
        if k["strike"] == ce_strike and k["option_type"] == "CE":
            ce_id = str(k["security_id"])
    if ce_id is None:
        print(f"{folder}: no ATM+100 CE in contracts, skipping")
        return None

    ticks = []
    with open(tf[0]) as f:
        for row in csv.DictReader(f):
            if row.get("packet_type") == "Previous Close":
                continue
            ltt, ltp = row.get("LTT"), row.get("LTP")
            if not ltt or not ltp:
                continue
            try:
                ticks.append((ltt, row["security_id"], float(ltp), row.get("depth_json")))
            except ValueError:
                continue

    window = [t for t in ticks if "09:15:00" <= t[0] <= "09:16:00"]
    ce_prices = [p for ltt, s, p, _ in window if s == ce_id]

    # aggregate book pressure over seconds 00-07
    bid_tot = ask_tot = 0
    seen = set()
    for ltt, s, _, dj in window:
        if s != ce_id or not dj or ltt > "09:15:07" or ltt in seen:
            continue
        try:
            levels = json.loads(dj)
        except Exception:
            continue
        seen.add(ltt)
        bid_tot += sum(int(l["bid_quantity"]) for l in levels)
        ask_tot += sum(int(l["ask_quantity"]) for l in levels)
    ratio = round(bid_tot / ask_tot, 2) if ask_tot else ""

    sess = date.fromisoformat(os.path.basename(folder.rstrip("/")))
    exp = date.fromisoformat(c["expiry"])

    sx_o = at_second(window, sensex_id, "09:15:00")
    sx_15 = at_second(window, sensex_id, "09:15:15")
    ce_o = at_second(window, ce_id, "09:15:00")
    ce_15 = at_second(window, ce_id, "09:15:15")

    return {
        "session_date": sess.isoformat(),
        "expiry": c["expiry"],
        "dte": (exp - sess).days,
        "atm": atm,
        "ref_spot": c["reference_spot"],
        "sensex_open": sx_o or "",
        "sensex_15s": sx_15 or "",
        "sensex_move": round(sx_15 - sx_o, 2) if sx_o and sx_15 else "",
        "ce_strike": ce_strike,
        "ce_open": ce_o or "",
        "ce_15s": ce_15 or "",
        "ce_move": round(ce_15 - ce_o, 2) if ce_o and ce_15 else "",
        "ce_min": min(ce_prices) if ce_prices else "",
        "ce_max": max(ce_prices) if ce_prices else "",
        "book_ratio_0_7": ratio,
    }

def main(folders):
    existing = set()
    if os.path.exists(SUMMARY):
        with open(SUMMARY) as f:
            existing = {r["session_date"] for r in csv.DictReader(f)}

    new_rows = []
    for folder in folders:
        row = summarize(folder)
        if row and row["session_date"] not in existing:
            new_rows.append(row)
        elif row:
            print(f"{row['session_date']}: already in summary, skipping")

    if not new_rows:
        print("No new rows to add.")
        return

    write_header = not os.path.exists(SUMMARY)
    with open(SUMMARY, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        if write_header:
            w.writeheader()
        for row in sorted(new_rows, key=lambda r: r["session_date"]):
            w.writerow(row)
            print(f"Added {row['session_date']}")

if __name__ == "__main__":
    main(sys.argv[1:] or sorted(glob.glob("2026-*")))
