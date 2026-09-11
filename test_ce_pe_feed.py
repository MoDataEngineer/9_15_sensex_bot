import os
import time
import requests
from datetime import datetime

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
# STEP 1: Get active SENSEX option expiries
# ---------------------------------------------------------

print("=" * 70)
print("SENSEX CE / PE LIVE FEED TEST")
print("=" * 70)
print("\nGetting active SENSEX option expiries...")

expiry_response = requests.post(
    f"{BASE_URL}/optionchain/expirylist",
    headers=HEADERS,
    json={
        "UnderlyingScrip": 51,
        "UnderlyingSeg": "IDX_I",
    },
    timeout=10,
)

if expiry_response.status_code != 200:
    raise RuntimeError(
        f"Expiry API failed: {expiry_response.status_code}\n"
        f"{expiry_response.text}"
    )

expiry_data = expiry_response.json()

if expiry_data.get("status") != "success":
    raise RuntimeError(f"Expiry API returned: {expiry_data}")

expiries = expiry_data["data"]

if not expiries:
    raise RuntimeError("No active SENSEX option expiries returned.")

# First expiry returned by Dhan = nearest active expiry
expiry = expiries[0]

print(f"Nearest expiry: {expiry}")

# ---------------------------------------------------------
# STEP 2: Get complete option chain
# ---------------------------------------------------------

print("\nGetting SENSEX option chain...")

chain_response = requests.post(
    f"{BASE_URL}/optionchain",
    headers=HEADERS,
    json={
        "UnderlyingScrip": 51,
        "UnderlyingSeg": "IDX_I",
        "Expiry": expiry,
    },
    timeout=10,
)

if chain_response.status_code != 200:
    raise RuntimeError(
        f"Option Chain API failed: {chain_response.status_code}\n"
        f"{chain_response.text}"
    )

chain_data = chain_response.json()

if chain_data.get("status") != "success":
    raise RuntimeError(f"Option Chain returned: {chain_data}")

data = chain_data["data"]

spot = float(data["last_price"])
option_chain = data["oc"]

print(f"SENSEX spot: {spot:.2f}")

# ---------------------------------------------------------
# STEP 3: Find nearest 100-point strike
# ---------------------------------------------------------

strikes = [float(x) for x in option_chain.keys()]

atm_strike = min(
    strikes,
    key=lambda strike: abs(strike - spot)
)

print(f"ATM strike: {atm_strike:.0f}")

# Find the actual option-chain key whose numeric value
# matches the selected ATM strike.
atm_key = next(
    key for key in option_chain.keys()
    if float(key) == float(atm_strike)
)

strike_data = option_chain[atm_key]

ce = strike_data.get("ce")
pe = strike_data.get("pe")

if not ce:
    raise RuntimeError("CE data not found for ATM strike.")

if not pe:
    raise RuntimeError("PE data not found for ATM strike.")

ce_id = int(ce["security_id"])
pe_id = int(pe["security_id"])

print()
print("-" * 70)
print("SELECTED CONTRACTS")
print("-" * 70)

print(f"Expiry      : {expiry}")
print(f"SENSEX      : {spot:.2f}")
print(f"ATM Strike  : {atm_strike:.0f}")
print()
print(f"CE Security : {ce_id}")
print(f"CE LTP      : {ce.get('last_price')}")
print(f"CE Bid      : {ce.get('top_bid_price')}")
print(f"CE Ask      : {ce.get('top_ask_price')}")
print()
print(f"PE Security : {pe_id}")
print(f"PE LTP      : {pe.get('last_price')}")
print(f"PE Bid      : {pe.get('top_bid_price')}")
print(f"PE Ask      : {pe.get('top_ask_price')}")
print("-" * 70)

# ---------------------------------------------------------
# STEP 4: Subscribe to SENSEX + ATM CE + ATM PE
# ---------------------------------------------------------

dhan_context = DhanContext(
    CLIENT_ID,
    ACCESS_TOKEN
)

instruments = [
    # SENSEX index
    (MarketFeed.IDX, "51", MarketFeed.Ticker),

    # ATM CE
    (MarketFeed.BSE_FNO, str(ce_id), MarketFeed.Ticker),

    # ATM PE
    (MarketFeed.BSE_FNO, str(pe_id), MarketFeed.Ticker),
]

print("\nConnecting to Dhan WebSocket...")
print("Subscriptions:")
print(f"  SENSEX : 51")
print(f"  CE     : {ce_id}")
print(f"  PE     : {pe_id}")
print()
print("Waiting for live ticks for 30 seconds...\n")

feed = MarketFeed(
    dhan_context,
    instruments,
    "v2"
)

try:

    feed.run_forever()

    start = time.monotonic()

    while time.monotonic() - start < 30:

        packet = feed.get_data()

        local_ns = time.time_ns()
        local_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        print(
            f"{local_time} | "
            f"local_ns={local_ns} | "
            f"{packet}"
        )

except KeyboardInterrupt:
    print("\nStopped by user.")

except Exception as e:
    print("\nERROR:")
    print(type(e).__name__, e)

finally:

    try:
        feed.close_connection()
    except Exception:
        pass

    print("\nFeed test finished.")