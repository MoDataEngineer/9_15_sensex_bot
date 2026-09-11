import os
import csv
import json
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
from dhanhq import DhanContext, MarketFeed

load_dotenv()

CLIENT_ID = os.getenv("DHAN_CLIENT_ID")
ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN")

if not CLIENT_ID or not ACCESS_TOKEN:
    raise RuntimeError("Dhan credentials missing from .env")

HEADERS = {
    "access-token": ACCESS_TOKEN,
    "client-id": CLIENT_ID,
    "Content-Type": "application/json",
}

BASE_URL = "https://api.dhan.co/v2"

# ---------------------------------------------------------
# 1. GET CURRENT SENSEX EXPIRY
# ---------------------------------------------------------

print("=" * 75)
print("SENSEX STRIKE LADDER FEED TEST")
print("=" * 75)

print("\nGetting active SENSEX expiry...")

response = requests.post(
    f"{BASE_URL}/optionchain/expirylist",
    headers=HEADERS,
    json={
        "UnderlyingScrip": 51,
        "UnderlyingSeg": "IDX_I",
    },
    timeout=10,
)

response.raise_for_status()

expiry_data = response.json()

if expiry_data.get("status") != "success":
    raise RuntimeError(expiry_data)

expiry = expiry_data["data"][0]

print(f"Nearest expiry: {expiry}")


# ---------------------------------------------------------
# 2. GET OPTION CHAIN
# ---------------------------------------------------------

print("\nGetting SENSEX option chain...")

response = requests.post(
    f"{BASE_URL}/optionchain",
    headers=HEADERS,
    json={
        "UnderlyingScrip": 51,
        "UnderlyingSeg": "IDX_I",
        "Expiry": expiry,
    },
    timeout=10,
)

response.raise_for_status()

chain_data = response.json()

if chain_data.get("status") != "success":
    raise RuntimeError(chain_data)

data = chain_data["data"]

spot = float(data["last_price"])
option_chain = data["oc"]

print(f"SENSEX spot: {spot:.2f}")


# ---------------------------------------------------------
# 3. FIND ATM STRIKE
# ---------------------------------------------------------

available_strikes = [
    float(key)
    for key in option_chain.keys()
]

atm_strike = min(
    available_strikes,
    key=lambda x: abs(x - spot)
)

print(f"ATM strike: {atm_strike:.0f}")


# ---------------------------------------------------------
# 4. BUILD ATM +/- 300 STRIKE LADDER
# ---------------------------------------------------------

strike_values = [
    atm_strike - 300,
    atm_strike - 200,
    atm_strike - 100,
    atm_strike,
    atm_strike + 100,
    atm_strike + 200,
    atm_strike + 300,
]

# Map numeric strike -> actual API dictionary key
strike_key_map = {
    round(float(key), 6): key
    for key in option_chain.keys()
}

contracts = []

for strike in strike_values:

    numeric_strike = round(float(strike), 6)

    if numeric_strike not in strike_key_map:
        print(f"WARNING: Strike {strike:.0f} not found")
        continue

    actual_key = strike_key_map[numeric_strike]
    strike_data = option_chain[actual_key]

    ce = strike_data.get("ce")
    pe = strike_data.get("pe")

    if ce:
        contracts.append({
            "strike": int(strike),
            "option_type": "CE",
            "security_id": int(ce["security_id"]),
            "ltp": ce.get("last_price"),
        })

    if pe:
        contracts.append({
            "strike": int(strike),
            "option_type": "PE",
            "security_id": int(pe["security_id"]),
            "ltp": pe.get("last_price"),
        })


# ---------------------------------------------------------
# 5. DISPLAY CONTRACT MAP
# ---------------------------------------------------------

print("\n" + "=" * 75)
print("SELECTED CONTRACTS")
print("=" * 75)

print(
    f"{'Strike':>10} {'Type':>6} "
    f"{'Security ID':>12} {'Chain LTP':>12}"
)

print("-" * 75)

for contract in contracts:
    print(
        f"{contract['strike']:>10} "
        f"{contract['option_type']:>6} "
        f"{contract['security_id']:>12} "
        f"{str(contract['ltp']):>12}"
    )

print("-" * 75)

print(f"\nTotal option contracts: {len(contracts)}")


# ---------------------------------------------------------
# 6. SAVE CONTRACT MAP
# ---------------------------------------------------------

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

map_file = f"strike_ladder_{timestamp}.json"

with open(map_file, "w", encoding="utf-8") as f:
    json.dump(
        {
            "created_at": datetime.now().isoformat(),
            "expiry": expiry,
            "spot": spot,
            "atm_strike": atm_strike,
            "contracts": contracts,
        },
        f,
        indent=2,
    )

print(f"Contract map saved: {map_file}")


# ---------------------------------------------------------
# 7. PREPARE WEBSOCKET SUBSCRIPTIONS
# ---------------------------------------------------------

instruments = [
    # SENSEX
    (MarketFeed.IDX, "51", MarketFeed.Ticker)
]

for contract in contracts:
    instruments.append(
        (
            MarketFeed.BSE_FNO,
            str(contract["security_id"]),
            MarketFeed.Full,
        )
    )


print("\n" + "=" * 75)
print("WEBSOCKET SUBSCRIPTIONS")
print("=" * 75)

print(f"SENSEX + {len(contracts)} options")
print(f"Total instruments: {len(instruments)}")

print("\nConnecting...")


# ---------------------------------------------------------
# 8. START WEBSOCKET
# ---------------------------------------------------------

dhan_context = DhanContext(
    CLIENT_ID,
    ACCESS_TOKEN
)

feed = MarketFeed(
    dhan_context,
    instruments,
    "v2"
)


# ---------------------------------------------------------
# 9. CSV FILE
# ---------------------------------------------------------

csv_file = f"strike_ladder_ticks_{timestamp}.csv"

csv_columns = [
    "local_time",
    "local_ns",
    "monotonic_ns",
    "packet_type",
    "exchange_segment",
    "security_id",
    "LTP",
    "LTQ",
    "LTT",
    "avg_price",
    "volume",
    "total_sell_quantity",
    "total_buy_quantity",
    "OI",
    "depth_json",
]

csv_handle = open(
    csv_file,
    "w",
    newline="",
    encoding="utf-8"
)

writer = csv.DictWriter(
    csv_handle,
    fieldnames=csv_columns
)

writer.writeheader()


# ---------------------------------------------------------
# 10. RECEIVE DATA FOR 60 SECONDS
# ---------------------------------------------------------

print("\nLive feed started.")
print("Recording for 60 seconds...")
print("NO ORDERS WILL BE PLACED.\n")

start = time.monotonic()
packet_count = 0

try:

    feed.run_forever()

    while time.monotonic() - start < 60:

        packet = feed.get_data()

        local_ns = time.time_ns()
        monotonic_ns = time.monotonic_ns()

        local_time = datetime.now().strftime(
            "%H:%M:%S.%f"
        )[:-3]

        packet_count += 1

        depth = packet.get("depth")

        row = {
            "local_time": local_time,
            "local_ns": local_ns,
            "monotonic_ns": monotonic_ns,
            "packet_type": packet.get("type"),
            "exchange_segment": packet.get("exchange_segment"),
            "security_id": packet.get("security_id"),
            "LTP": packet.get("LTP"),
            "LTQ": packet.get("LTQ"),
            "LTT": packet.get("LTT"),
            "avg_price": packet.get("avg_price"),
            "volume": packet.get("volume"),
            "total_sell_quantity": packet.get(
                "total_sell_quantity"
            ),
            "total_buy_quantity": packet.get(
                "total_buy_quantity"
            ),
            "OI": packet.get("OI"),
            "depth_json": json.dumps(depth)
            if depth is not None else "",
        }

        writer.writerow(row)
        csv_handle.flush()

        # Compact terminal output
        print(
            f"{local_time} | "
            f"SEG={packet.get('exchange_segment')} | "
            f"ID={packet.get('security_id')} | "
            f"LTP={packet.get('LTP')} | "
            f"LTT={packet.get('LTT')}"
        )

except KeyboardInterrupt:

    print("\nStopped manually.")

except Exception as e:

    print("\nERROR:")
    print(type(e).__name__, e)

finally:

    csv_handle.close()

    try:
        feed.close_connection()
    except Exception:
        pass

    print("\n" + "=" * 75)
    print("TEST FINISHED")
    print("=" * 75)
    print(f"Packets recorded: {packet_count}")
    print(f"Tick data file: {csv_file}")
    print(f"Contract map:   {map_file}")