import csv, json, sys, glob

def analyze(folder, sid, label):
    path = glob.glob(f"{folder}/session_ticks_*.csv")[0]
    print(f"\n=== {label}  ({folder}, id {sid}) ===")
    print("LTT       LTP      BidQty  AskQty  Ratio   Spread  BidOrd AskOrd")
    seen = set()
    with open(path) as f:
        for row in csv.DictReader(f):
            if row['security_id'] != sid:
                continue
            ltt = row.get('LTT', '')
            if not ltt or ltt < "09:15:00" or ltt > "09:15:12":
                continue
            if ltt in seen:
                continue
            dj = row.get('depth_json')
            if not dj:
                continue
            try:
                levels = json.loads(dj)
            except Exception:
                continue
            bq = sum(int(l['bid_quantity']) for l in levels)
            aq = sum(int(l['ask_quantity']) for l in levels)
            bo = sum(int(l['bid_orders']) for l in levels)
            ao = sum(int(l['ask_orders']) for l in levels)
            try:
                spread = float(levels[0]['ask_price']) - float(levels[0]['bid_price'])
            except Exception:
                spread = float('nan')
            ratio = bq / aq if aq else float('inf')
            ltp = row.get('LTP', '')
            seen.add(ltt)
            print(f"{ltt}  {ltp:>8}  {bq:>6}  {aq:>6}  {ratio:>5.2f}  {spread:>6.2f}  {bo:>5}  {ao:>5}")

analyze("2026-09-15", "865797", "Sep 15 - 75500 CE (broke DOWN)")
analyze("2026-09-16", "869699", "Sep 16 - 74300 CE (broke UP)")
