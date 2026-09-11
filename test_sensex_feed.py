import os
import time
from datetime import datetime

from dotenv import load_dotenv
from dhanhq import DhanContext, MarketFeed

load_dotenv()

client_id = os.getenv("DHAN_CLIENT_ID")
access_token = os.getenv("DHAN_ACCESS_TOKEN")

if not client_id or not access_token:
    raise RuntimeError("Dhan credentials missing from .env")

dhan_context = DhanContext(client_id, access_token)

# SENSEX INDEX
# IDX_I = 0
# Security ID = 1
instruments = [
    (MarketFeed.IDX, "51", MarketFeed.Ticker)
]

print("=" * 60)
print("Dhan SENSEX LIVE FEED TEST")
print("=" * 60)
print("Instrument : SENSEX")
print("Segment    : IDX_I")
print("Security ID: 51")
print()
print("Connecting...")
print()

feed = MarketFeed(
    dhan_context,
    instruments,
    "v2"
)

try:
    feed.run_forever()

    print("WebSocket connected.")
    print("Waiting for SENSEX ticks...")
    print()

    start = time.monotonic()

    while time.monotonic() - start < 30:

        data = feed.get_data()

        local_ns = time.time_ns()
        local_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        print(
            f"{local_time} | "
            f"local_ns={local_ns} | "
            f"{data}"
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