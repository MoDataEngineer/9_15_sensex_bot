import os
import csv
import json
import time
from datetime import datetime, time as dtime

import requests
from dotenv import load_dotenv
from dhanhq import DhanContext, MarketFeed

load_dotenv()

CLIENT_ID = os.getenv("DHAN_CLIENT_ID")
ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN")

if not CLIENT_ID or not ACCESS_TOKEN:
    raise RuntimeError("DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN missing from .env")

HEADERS = {
    "access-token": ACCESS_TOKEN,
    "client-id": CLIENT_ID,
    "Content-Type": "application/json",
}

BASE_URL = "https://api.dhan.co/v2"

SENSEX_SECURITY_ID = 51
UNDERLYING_SEGMENT = "IDX_I"

# Recording window in local machine time (IST).
START_TIME = dtime(14, 15, 59)
END_TIME = dtime(14, 17, 0)

# ATM +/- 100/200/300
STRIKE_OFFSETS = [-300, -200, -100, 0, 100, 200, 300]


def now_local():
    return datetime.now()


def wait_until(target_time):
    while True:
        now = now_local()

        if now.time() >= target_time:
            return

        seconds = (
            datetime.combine(now.date(), target_time) - now
        ).total_seconds()

        time.sleep(min(max(seconds, 0.01), 0.5))


def api_post(path, payload):
    response = requests.post(
        f"{BASE_URL}{path}",
        headers=HEADERS,
        json=payload,
        timeout=10,
    )
    response.raise_for_status()

    data = response.json()

    if data.get("status") != "success":
        raise RuntimeError(data)

    return data


def get_expiry():
    data = api_post(
        "/optionchain/expirylist",
        {
            "UnderlyingScrip": SENSEX_SECURITY_ID,
            "UnderlyingSeg": UNDERLYING_SEGMENT,
        },
    )

    expiries = data.get("data", [])

    if not expiries:
        raise RuntimeError("No SENSEX expiry returned.")

    return expiries[0]


def get_option_chain(expiry):
    return api_post(
        "/optionchain",
        {
            "UnderlyingScrip": SENSEX_SECURITY_ID,
            "UnderlyingSeg": UNDERLYING_SEGMENT,
            "Expiry": expiry,
        },
    )


def build_contracts(chain_data):
    data = chain_data["data"]
    spot = float(data["last_price"])
    option_chain = data["oc"]

    available_strikes = [float(k) for k in option_chain.keys()]

    atm = min(
        available_strikes,
        key=lambda x: abs(x - spot)
    )

    atm = round(atm / 100) * 100

    strike_key_map = {
        round(float(k), 6): k
        for k in option_chain.keys()
    }

    contracts = []

    for offset in STRIKE_OFFSETS:
        strike = atm + offset
        key = strike_key_map.get(round(float(strike), 6))

        if key is None:
            print(f"WARNING: strike {strike} not found.")
            continue

        strike_data = option_chain[key]

        for option_type in ("CE", "PE"):
            leg = strike_data.get(option_type.lower())

            if not leg:
                continue

            contracts.append({
                "strike": int(strike),
                "option_type": option_type,
                "security_id": int(leg["security_id"]),
                "chain_ltp": leg.get("last_price"),
            })

    return spot, atm, contracts


def packet_to_row(packet):
    depth = packet.get("depth")

    return {
        "local_time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "local_ns": time.time_ns(),
        "monotonic_ns": time.monotonic_ns(),
        "packet_type": packet.get("type"),
        "exchange_segment": packet.get("exchange_segment"),
        "security_id": packet.get("security_id"),
        "LTP": packet.get("LTP"),
        "LTQ": packet.get("LTQ"),
        "LTT": packet.get("LTT"),
        "avg_price": packet.get("avg_price"),
        "volume": packet.get("volume"),
        "total_sell_quantity": packet.get("total_sell_quantity"),
        "total_buy_quantity": packet.get("total_buy_quantity"),
        "OI": packet.get("OI"),
        "depth_json": (
            json.dumps(depth, separators=(",", ":"))
            if depth is not None else ""
        ),
    }


def main():
    print("=" * 80)
    print("SENSEX 9:15 PAPER-RESEARCH RECORDER")
    print("=" * 80)
    print("NO ORDERS WILL BE PLACED.")

    if now_local().time() < START_TIME:
        print(
            f"\nWaiting for recording window: "
            f"{START_TIME.strftime('%H:%M:%S')} IST"
        )
        wait_until(START_TIME)

    if now_local().time() > END_TIME:
        raise RuntimeError(
            "Today's 9:15 recording window has already passed. "
            "Run this script before 09:14:45 IST on the next trading day."
        )

    print("\nGetting nearest SENSEX expiry...")
    expiry = get_expiry()
    print(f"Expiry: {expiry}")

    print("Getting option chain...")
    chain_data = get_option_chain(expiry)

    spot, atm, contracts = build_contracts(chain_data)

    print(f"Reference SENSEX spot: {spot:.2f}")
    print(f"Reference ATM strike: {atm:.0f}")

    if len(contracts) != 14:
        raise RuntimeError(
            f"Expected 14 option contracts, got {len(contracts)}."
        )

    print("\nSelected contracts:")
    print("-" * 80)
    print(
        f"{'Strike':>10} {'Type':>6} "
        f"{'Security ID':>12} {'Chain LTP':>12}"
    )
    print("-" * 80)

    for c in contracts:
        print(
            f"{c['strike']:>10} "
            f"{c['option_type']:>6} "
            f"{c['security_id']:>12} "
            f"{str(c['chain_ltp']):>12}"
        )

    # ------------------------------------------------------------
    # DAILY OUTPUT FOLDER
    # ------------------------------------------------------------
    # Example:
    # 9.15_SENSEX_BOT/
    # └── 2026-09-12/
    #     ├── session_ticks_20260912_091445.csv
    #     └── session_contracts_20260912_091445.json
    # ------------------------------------------------------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_date = datetime.now().strftime("%Y-%m-%d")

    output_dir = os.path.join(
        os.getcwd(),
        session_date
    )

    os.makedirs(output_dir, exist_ok=True)

    map_file = os.path.join(
        output_dir,
        f"session_contracts_{timestamp}.json"
    )

    with open(map_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "created_at": datetime.now().isoformat(),
                "expiry": expiry,
                "reference_spot": spot,
                "reference_atm": atm,
                "strikes": STRIKE_OFFSETS,
                "contracts": contracts,
                "sensex": {
                    "security_id": SENSEX_SECURITY_ID,
                    "exchange_segment": "IDX_I",
                    "feed_type": "Ticker",
                },
                "options": {
                    "exchange_segment": "BSE_FNO",
                    "feed_type": "Full",
                    "depth_levels": 5,
                },
            },
            f,
            indent=2,
        )

    instruments = [
        (
            MarketFeed.IDX,
            str(SENSEX_SECURITY_ID),
            MarketFeed.Ticker,
        )
    ]

    for c in contracts:
        instruments.append(
            (
                MarketFeed.BSE_FNO,
                str(c["security_id"]),
                MarketFeed.Full,
            )
        )

    print("\n" + "=" * 80)
    print("WEBSOCKET SUBSCRIPTIONS")
    print("=" * 80)
    print(f"Total instruments: {len(instruments)}")
    print("1 SENSEX + 14 options")

    print("\nConnecting to Dhan WebSocket...")
    print("Recording until 09:16:00 IST...")
    print("NO ORDERS WILL BE PLACED.\n")

    dhan_context = DhanContext(
        CLIENT_ID,
        ACCESS_TOKEN,
    )

    feed = MarketFeed(
        dhan_context,
        instruments,
        "v2",
    )

    csv_file = os.path.join(
        output_dir,
        f"session_ticks_{timestamp}.csv"
    )

    columns = [
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
        encoding="utf-8",
    )

    writer = csv.DictWriter(
        csv_handle,
        fieldnames=columns,
    )

    writer.writeheader()

    packet_count = 0
    recording_started = None

    try:
        feed.run_forever()

        if now_local().time() < START_TIME:
            wait_until(START_TIME)

        recording_started = now_local()

        while now_local().time() <= END_TIME:
            packet = feed.get_data()

            if not packet:
                continue

            row = packet_to_row(packet)

            writer.writerow(row)
            csv_handle.flush()

            packet_count += 1

            print(
                f"{row['local_time']} | "
                f"TYPE={row['packet_type']} | "
                f"SEG={row['exchange_segment']} | "
                f"ID={row['security_id']} | "
                f"LTP={row['LTP']} | "
                f"LTT={row['LTT']}"
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

        print("\n" + "=" * 80)
        print("SESSION RECORDING FINISHED")
        print("=" * 80)
        print(f"Packets recorded : {packet_count}")
        print(f"Tick file        : {csv_file}")
        print(f"Contract map     : {map_file}")

        if recording_started:
            print(
                "Recording started: "
                f"{recording_started.isoformat()}"
            )

        print("\nFiles for this session are stored in:")
        print(f"  {output_dir}")


if __name__ == "__main__":
    main()
