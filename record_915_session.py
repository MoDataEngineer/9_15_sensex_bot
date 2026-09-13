import os
import csv
import json
import time
import argparse
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import requests
from dhanhq import DhanContext, MarketFeed


IST = ZoneInfo("Asia/Kolkata")

CLIENT_ID = os.environ.get("DHAN_CLIENT_ID")
ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN")

if not CLIENT_ID or not ACCESS_TOKEN:
    raise RuntimeError(
        "DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN environment variables are required"
    )

HEADERS = {
    "access-token": ACCESS_TOKEN,
    "client-id": CLIENT_ID,
    "Content-Type": "application/json",
}

BASE_URL = "https://api.dhan.co/v2"

SENSEX_SECURITY_ID = 51
UNDERLYING_SEGMENT = "IDX_I"

# ------------------------------------------------------------
# MARKET TIMING
# ------------------------------------------------------------
# The recorder is launched before market open.
# Feed/contract preparation happens before 09:15.
# ACTUAL tick recording begins at 09:15:00 IST.
RECORD_START_TIME = dtime(9, 15, 0)
RECORD_END_TIME = dtime(9, 16, 0)

# ATM +/- 100/200/300
STRIKE_OFFSETS = [-300, -200, -100, 0, 100, 200, 300]


def now_local():
    return datetime.now(IST)


def wait_until(target_time):
    """Precision wait using Asia/Kolkata wall-clock time."""
    while True:
        now = now_local()

        if now.time() >= target_time:
            return

        target = datetime.combine(
            now.date(),
            target_time,
            tzinfo=IST,
        )

        remaining = (target - now).total_seconds()

        if remaining > 30:
            sleep_seconds = 10.0
        elif remaining > 5:
            sleep_seconds = 1.0
        elif remaining > 1:
            sleep_seconds = 0.2
        else:
            sleep_seconds = 0.05

        time.sleep(max(0.01, min(sleep_seconds, remaining)))


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

    nearest_strike = min(
        available_strikes,
        key=lambda x: abs(x - spot),
    )

    # Nearest-100 ATM.
    atm = round(nearest_strike / 100) * 100

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

            contracts.append(
                {
                    "strike": int(strike),
                    "option_type": option_type,
                    "security_id": int(leg["security_id"]),
                    "chain_ltp": leg.get("last_price"),
                }
            )

    return spot, atm, contracts


def packet_to_row(packet, received_at=None):
    """
    Convert a Dhan MarketFeed packet into one CSV row.

    received_at is captured at the moment get_data() returns so the
    dataset has a local receipt timestamp independent of the packet's
    exchange timestamp.
    """
    if received_at is None:
        received_at = now_local()

    depth = packet.get("depth")

    return {
        "local_time": received_at.strftime("%H:%M:%S.%f")[:-3],
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
            if depth is not None
            else ""
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="SENSEX 9:15 paper-research recorder"
    )

    parser.add_argument(
        "--preparation-test",
        action="store_true",
        help="Prepare contracts and connect MarketFeed, then exit without recording.",
    )

    args = parser.parse_args()

    print("=" * 80)
    print("SENSEX 9:15 PAPER-RESEARCH RECORDER")
    print("=" * 80)
    print("NO ORDERS WILL BE PLACED.")

    current_time = now_local().time()

    # The runner should launch this process before 09:15.
    # If it is launched after the recording window, do not create a
    # misleading/late dataset.
    if current_time >= RECORD_END_TIME:
        raise RuntimeError(
            "Today's 9:15 recording window has already passed."
        )

    # ------------------------------------------------------------
    # CONTRACT PREPARATION
    # ------------------------------------------------------------
    # IMPORTANT:
    # Do this BEFORE 09:15 so the WebSocket can be connected before
    # the actual recording boundary.
    # ------------------------------------------------------------

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

    for contract in contracts:
        print(
            f"{contract['strike']:>10} "
            f"{contract['option_type']:>6} "
            f"{contract['security_id']:>12} "
            f"{str(contract['chain_ltp']):>12}"
        )

    # ------------------------------------------------------------
    # DAILY OUTPUT FOLDER
    # ------------------------------------------------------------

    now = now_local()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    session_date = now.strftime("%Y-%m-%d")

    output_dir = os.path.join(
        os.getcwd(),
        session_date,
    )

    os.makedirs(output_dir, exist_ok=True)

    map_file = os.path.join(
        output_dir,
        f"session_contracts_{timestamp}.json",
    )

    with open(map_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "created_at": now.isoformat(),
                "record_start": RECORD_START_TIME.strftime("%H:%M:%S"),
                "record_end": RECORD_END_TIME.strftime("%H:%M:%S"),
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

    # ------------------------------------------------------------
    # WEBSOCKET SUBSCRIPTIONS
    # ------------------------------------------------------------

    instruments = [
        (
            MarketFeed.IDX,
            str(SENSEX_SECURITY_ID),
            MarketFeed.Ticker,
        )
    ]

    for contract in contracts:
        instruments.append(
            (
                MarketFeed.BSE_FNO,
                str(contract["security_id"]),
                MarketFeed.Full,
            )
        )

    print("\n" + "=" * 80)
    print("WEBSOCKET SUBSCRIPTIONS")
    print("=" * 80)
    print(f"Total instruments: {len(instruments)}")
    print("1 SENSEX + 14 options")

    print("\nConnecting to Dhan WebSocket...")
    print("Actual recording boundary: 09:15:00 IST")
    print("Recording ends: 09:16:00 IST")
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
        f"session_ticks_{timestamp}.csv",
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

    csv_handle = None
    recording_started = None
    recording_finished = None
    rows_written = 0

    try:
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
        csv_handle.flush()

        # --------------------------------------------------------
        # PRE-OPEN WEBSOCKET CONNECTION
        # --------------------------------------------------------
        # Dhan's run_forever() establishes the WebSocket connection
        # and subscription, then returns. get_data() receives packets.
        # We deliberately do not call get_data() until 09:15.
        # --------------------------------------------------------

        print(
            f"[{now_local().isoformat()}] "
            "Connecting to Dhan MarketFeed before 09:15..."
        )

        feed.run_forever()

        feed_ready_at = now_local()

        print(
            f"[{feed_ready_at.isoformat()}] "
            "MarketFeed connected/subscribed."
        )

        # --------------------------------------------------------
        # PREPARATION-ONLY TEST MODE
        # --------------------------------------------------------
        # Used by the manual GitHub Actions test.
        # This verifies:
        #   - expiry retrieval
        #   - option-chain retrieval
        #   - ATM contract selection
        #   - MarketFeed construction
        #   - WebSocket connection/subscription
        #
        # NO MARKET TICKS ARE RECORDED IN THIS MODE.
        # --------------------------------------------------------

        if args.preparation_test:
            preparation_finished = now_local()

            print("\n" + "=" * 80)
            print("PREPARATION TEST PASSED")
            print("=" * 80)
            print(
                f"MarketFeed ready at: "
                f"{preparation_finished.isoformat()}"
            )
            print(f"Contracts prepared : {len(contracts)}")
            print(f"Instruments ready  : {len(instruments)}")
            print("Recording started  : NO")
            print("=" * 80)

            return 0

        # --------------------------------------------------------
        # WAIT FOR ACTUAL MARKET OPEN
        # --------------------------------------------------------

        if now_local().time() < RECORD_START_TIME:
            print(
                f"[{now_local().isoformat()}] "
                "Feed ready. Waiting for 09:15:00 IST..."
            )
            wait_until(RECORD_START_TIME)

        recording_started = now_local()

        print(
            f"[{recording_started.isoformat()}] "
            "ACTUAL RECORDING STARTED."
        )

        # --------------------------------------------------------
        # RECORD 09:15:00 <= receipt time < 09:16:00
        # --------------------------------------------------------

        while True:
            current_time = now_local().time()

            if current_time >= RECORD_END_TIME:
                break

            packet = feed.get_data()
            received_at = now_local()

            if not packet:
                continue

            # Hard local receipt-time boundary.
            if received_at.time() < RECORD_START_TIME:
                continue

            if received_at.time() >= RECORD_END_TIME:
                break

            writer.writerow(packet_to_row(packet, received_at))
            rows_written += 1

            # Flush each row so the CSV is kept current on disk.
            csv_handle.flush()

        recording_finished = now_local()

        print(
            f"[{recording_finished.isoformat()}] "
            f"RECORDING FINISHED. Rows written: {rows_written}"
        )

    except KeyboardInterrupt:
        print("\nStopped manually.")

    except Exception as exc:
        print("\nERROR:")
        print(type(exc).__name__, exc)
        raise

    finally:
        try:
            feed.close_connection()
        except Exception as exc:
            print(
                f"[{now_local().isoformat()}] "
                f"Feed close warning: {exc}"
            )

        if csv_handle is not None:
            try:
                csv_handle.flush()
                csv_handle.close()
            except Exception as exc:
                print(
                    f"[{now_local().isoformat()}] "
                    f"CSV close warning: {exc}"
                )

        print("\n" + "=" * 80)
        print("SESSION RECORDING FINISHED")
        print("=" * 80)
        print(f"Packets recorded : {rows_written}")
        print(f"Tick file        : {csv_file}")
        print(f"Contract map     : {map_file}")

        if recording_started:
            print(
                "Recording started: "
                f"{recording_started.isoformat()}"
            )

        if recording_finished:
            print(
                "Recording finished: "
                f"{recording_finished.isoformat()}"
            )

        print("\nFiles for this session are stored in:")
        print(f"  {output_dir}")


if __name__ == "__main__":
    main()