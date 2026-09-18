import os, glob, json, csv, sys

OFFSETS = [0, 1, 5, 10, 12, 15, 30, 60]  # +12s included: creator's example exited ~09:15:12

def load_day(folder):
    cf = glob.glob(os.path.join(folder, "session_contracts_*.json"))
    tf = glob.glob(os.path.join(folder, "session_ticks_*.csv"))
    if not cf or not tf:
        return None
    contracts = json.load(open(cf[0]))
    id_label = {str(contracts["sensex"]["security_id"]): "SENSEX"}
    order = ["SENSEX"]
    for c in contracts["contracts"]:
        label = f'{c["strike"]} {c["option_type"]}'
        id_label[str(c["security_id"])] = label
        order.append(label)
    h, m, s = map(int, contracts["record_start"].split(":"))
    start_sec = h * 3600 + m * 60 + s
    return contracts, id_label, order, tf[0], start_sec

def analyze(folder):
    loaded = load_day(folder)
    if not loaded:
        print(f"{folder}: no data files found, skipping")
        return
    contracts, id_label, order, ticks_path, start_sec = loaded

    rows = []
    with open(ticks_path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("packet_type") == "Previous Close":
                continue
            ltt, ltp = row.get("LTT"), row.get("LTP")
            if not ltt or not ltp:
                continue
            try:
                h, m, s = map(int, ltt.split(":"))
                offset = (h * 3600 + m * 60 + s) - start_sec
                price = float(ltp)
            except ValueError:
                continue
            if 0 <= offset <= 60:
                rows.append((int(row["local_ns"]), row["security_id"], offset, price))

    rows.sort(key=lambda r: r[0])  # chronological order

    first_at = {}   # (label, offset) -> price, first one wins
    minmax = {}     # label -> [min, max]
    for _, sid, offset, price in rows:
        label = id_label.get(sid)
        if not label:
            continue
        key = (label, offset)
        if key not in first_at:
            first_at[key] = price
        lo, hi = minmax.get(label, (price, price))
        minmax[label] = (min(lo, price), max(hi, price))

    print(f"\n=== {os.path.basename(folder)}  (ATM {contracts['reference_atm']}, spot {contracts['reference_spot']}) ===")
    header = "Instrument".ljust(10) + "".join(f"+{o}s".rjust(10) if o else "Open".rjust(10) for o in OFFSETS) + "Min".rjust(10) + "Max".rjust(10)
    print(header)
    for label in order:
        vals = []
        for o in OFFSETS:
            v = first_at.get((label, o))
            vals.append(f"{v:.2f}".rjust(10) if v is not None else "N/A".rjust(10))
        lo, hi = minmax.get(label, (None, None))
        lo_s = f"{lo:.2f}".rjust(10) if lo is not None else "N/A".rjust(10)
        hi_s = f"{hi:.2f}".rjust(10) if hi is not None else "N/A".rjust(10)
        print(label.ljust(10) + "".join(vals) + lo_s + hi_s)

if __name__ == "__main__":
    folders = sys.argv[1:] if len(sys.argv) > 1 else sorted(glob.glob("2026-09-*"))
    for folder in folders:
        analyze(folder)
