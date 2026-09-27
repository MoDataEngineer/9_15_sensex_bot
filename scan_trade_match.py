import csv, json, glob, os, sys

TARGET_A = 236.15   # entry
TARGET_B = 220.25   # drawdown low
TARGET_C = 251.15   # target hit (>=)
TOL = 0.5

def load_contract_info(folder):
    cf = glob.glob(os.path.join(folder, "session_contracts_*.json"))
    for path in cf:
        try:
            c = json.load(open(path))
            if "reference_atm" not in c or "contracts" not in c:
                continue
            atm = c["reference_atm"]
            info = {}
            for k in c["contracts"]:
                info[str(k["security_id"])] = {
                    "strike": k["strike"],
                    "option_type": k["option_type"],
                    "atm_offset": k["strike"] - atm,
                }
            return info
        except Exception:
            continue
    return None

def scan_folder(folder):
    info = load_contract_info(folder)
    tf = glob.glob(os.path.join(folder, "session_ticks_*.csv"))
    if not info or not tf:
        print(f"  (skipping {folder}: no usable contracts/ticks file)")
        return []

    ticks_by_id = {}
    with open(tf[0]) as f:
        for row in csv.DictReader(f):
            if row.get("packet_type") == "Previous Close":
                continue
            sid = row.get("security_id")
            ltp = row.get("LTP")
            if not sid or sid not in info or not ltp:
                continue
            try:
                price = float(ltp)
                ns = int(row["local_ns"])
            except (ValueError, KeyError):
                continue
            ticks_by_id.setdefault(sid, []).append(
                (ns, row.get("LTT", ""), row.get("local_time", ""), price)
            )

    matches = []
    for sid, ticks in ticks_by_id.items():
        ticks.sort(key=lambda t: t[0])
        stage, a, b, c = 0, None, None, None
        for ns, ltt, lt, price in ticks:
            if stage == 0 and abs(price - TARGET_A) <= TOL:
                a = (ltt, lt, price)
                stage = 1
            elif stage == 1 and abs(price - TARGET_B) <= TOL:
                b = (ltt, lt, price)
                stage = 2
            elif stage == 2 and price >= TARGET_C:
                c = (ltt, lt, price)
                stage = 3
                break
        if stage == 3:
            meta = info[sid]
            matches.append((folder, meta["strike"], meta["option_type"], meta["atm_offset"], a, b, c))
    return matches

if __name__ == "__main__":
    folders = sys.argv[1:] or sorted(glob.glob("2026-09-*"))
    found = []
    for folder in folders:
        found.extend(scan_folder(folder))

    if not found:
        print("\nNo matches found in any session.")
    else:
        for folder, strike, otype, offset, a, b, c in found:
            print(f"\n=== MATCH: {folder}  {strike} {otype}  (ATM offset {offset:+d}) ===")
            print(f"  Entry ~236.15 : LTT {a[0]}  local {a[1]}  price {a[2]}")
            print(f"  Low   ~220.25 : LTT {b[0]}  local {b[1]}  price {b[2]}")
            print(f"  Target 251.15+: LTT {c[0]}  local {c[1]}  price {c[2]}")
