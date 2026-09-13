import os
import sys
import time
import subprocess
import argparse
from datetime import datetime, date, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import pyotp


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
RECORDER_PATH = BASE_DIR / "record_915_session.py"
LOG_DIR = BASE_DIR / "logs"

LOG_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# TIMEZONE
# ============================================================

IST = ZoneInfo("Asia/Kolkata")


# ============================================================
# DHAN
# ============================================================

DHAN_TOKEN_URL = "https://auth.dhan.co/app/generateAccessToken"
DHAN_PROFILE_URL = "https://api.dhan.co/v2/profile"

TOKEN_RETRY_SECONDS = 2


# ============================================================
# MARKET TIMING
# ============================================================

# 09:14:30 is ONLY the preparation/buffer checkpoint.
# Actual market tick recording begins at 09:15:00.
PREP_TIME = dtime(9, 14, 30)
RECORD_START = dtime(9, 15, 0)
RECORD_END = dtime(9, 16, 0)


# ============================================================
# HELPERS
# ============================================================

def now_ist():
    return datetime.now(IST)


def log(message):
    timestamp = now_ist().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {message}"

    print(line, flush=True)

    try:
        log_file = LOG_DIR / f"morning_runner_{now_ist().strftime('%Y-%m-%d')}.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def wait_until(target_time):
    """
    Precision wait until target_time in IST.
    """

    while True:
        current = now_ist()
        target = datetime.combine(
            current.date(),
            target_time,
            tzinfo=IST
        )

        remaining = (target - current).total_seconds()

        if remaining <= 0:
            return

        if remaining > 30:
            time.sleep(10)
        elif remaining > 5:
            time.sleep(1)
        elif remaining > 1:
            time.sleep(0.2)
        else:
            time.sleep(0.05)


def is_weekend(day=None):
    if day is None:
        day = now_ist().date()

    return day.weekday() >= 5


# ============================================================
# NSE HOLIDAY CHECK
# ============================================================

def is_nse_holiday(day=None):
    """
    Returns:
        True  -> confirmed NSE holiday
        False -> confirmed trading day

    Fails closed if the NSE API cannot be reached.
    """

    if day is None:
        day = now_ist().date()

    url = "https://www.nseindia.com/api/holiday-master?type=trading"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/142.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.nseindia.com/",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        target = day.strftime("%d-%b-%Y").upper()

        for item in data.get("CM", []):
            holiday_date = str(item.get("tradingDate", "")).upper()

            if holiday_date == target:
                return True

        return False

    except Exception as exc:
        log(f"NSE holiday check failed: {exc}")
        raise RuntimeError(
            "Unable to verify NSE holiday status. "
            "Failing closed for safety."
        ) from exc


# ============================================================
# CONFIG
# ============================================================

def load_config():
    client_id = os.environ.get("DHAN_CLIENT_ID")
    pin = os.environ.get("DHAN_PIN")
    totp_secret = os.environ.get("DHAN_TOTP_SECRET")

    missing = []

    if not client_id:
        missing.append("DHAN_CLIENT_ID")

    if not pin:
        missing.append("DHAN_PIN")

    if not totp_secret:
        missing.append("DHAN_TOTP_SECRET")

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
        )

    return client_id, pin, totp_secret


# ============================================================
# DHAN TOKEN
# ============================================================

def generate_access_token(client_id, pin, totp_secret):
    """
    Generate a fresh Dhan access token using TOTP.
    """

    for attempt in range(2):

        # Avoid generating a TOTP right on a 30-second boundary.
        current_second = int(time.time()) % 30

        if current_second >= 25:
            sleep_for = 31 - current_second

            log(
                f"TOTP boundary approaching. "
                f"Waiting {sleep_for}s..."
            )

            time.sleep(sleep_for)

        totp = pyotp.TOTP(totp_secret).now()

        payload = {
            "dhanClientId": client_id,
            "pin": pin,
            "totp": totp,
        }

        try:
            response = requests.post(
                DHAN_TOKEN_URL,
                json=payload,
                timeout=15
            )

            response.raise_for_status()

            data = response.json()

            token = (
                data.get("accessToken")
                or data.get("access_token")
            )

            if not token:
                raise RuntimeError(
                    f"Dhan token response did not contain access token: "
                    f"{data}"
                )

            log("Fresh Dhan access token generated.")

            return token

        except Exception as exc:

            log(
                f"Dhan token generation attempt "
                f"{attempt + 1} failed: {exc}"
            )

            if attempt == 0:
                time.sleep(TOKEN_RETRY_SECONDS)
            else:
                raise

    raise RuntimeError("Unable to generate Dhan access token.")


# ============================================================
# VALIDATE DHAN TOKEN
# ============================================================

def validate_access_token(access_token):
    headers = {
        "access-token": access_token
    }

    response = requests.get(
        DHAN_PROFILE_URL,
        headers=headers,
        timeout=15
    )

    response.raise_for_status()

    log("Dhan access token validated successfully.")


# ============================================================
# LAUNCH RECORDER
# ============================================================

def launch_recorder(access_token, preparation_test=False):
    """
    Launch the SENSEX recorder.

    Normal mode:
        prepare -> connect -> record 09:15-09:16

    Preparation-test mode:
        prepare -> connect -> exit without recording
    """

    if not RECORDER_PATH.exists():
        raise FileNotFoundError(
            f"Recorder not found: {RECORDER_PATH}"
        )

    env = os.environ.copy()
    env["DHAN_ACCESS_TOKEN"] = access_token

    command = [
        sys.executable,
        str(RECORDER_PATH),
    ]

    if preparation_test:
        command.append("--preparation-test")

    log(
        f"Launching recorder: {RECORDER_PATH.name}"
        + (" [PREPARATION TEST]" if preparation_test else "")
    )

    process = subprocess.Popen(
        command,
        cwd=str(BASE_DIR),
        env=env,
    )

    log(
        f"Recorder process started. PID={process.pid}"
    )

    return process



# ============================================================
# PREPARATION TEST
# ============================================================

def run_preparation_test():
    """
    Full end-to-end preparation test.

    Tests:
      - Dhan configuration
      - fresh TOTP authentication
      - access-token validation
      - option expiry retrieval
      - option-chain retrieval
      - ATM contract selection
      - MarketFeed creation
      - WebSocket connection/subscription

    NO MARKET TICKS ARE RECORDED.
    NO ORDERS ARE PLACED.
    """

    test_started = now_ist()

    log("=" * 80)
    log("SENSEX PREPARATION TEST STARTED")
    log("=" * 80)
    log(f"Test start: {test_started.isoformat()}")

    client_id, pin, totp_secret = load_config()

    log("Generating fresh Dhan access token.")
    token_started = now_ist()

    access_token = generate_access_token(
        client_id,
        pin,
        totp_secret
    )

    token_finished = now_ist()

    log(
        f"Token generation: "
        f"{(token_finished - token_started).total_seconds():.3f}s"
    )

    log("Validating Dhan access token.")
    validate_started = now_ist()

    validate_access_token(access_token)

    validate_finished = now_ist()

    log(
        f"Token validation: "
        f"{(validate_finished - validate_started).total_seconds():.3f}s"
    )

    log("Launching recorder in preparation-test mode.")

    process = launch_recorder(
        access_token,
        preparation_test=True
    )

    return_code = process.wait()
    test_finished = now_ist()

    total_seconds = (
        test_finished - test_started
    ).total_seconds()

    log(
        f"Recorder preparation-test exit code: "
        f"{return_code}"
    )

    log(
        f"Total preparation time: "
        f"{total_seconds:.3f}s"
    )

    if return_code != 0:
        raise RuntimeError("Preparation test FAILED.")

    log("=" * 80)
    log("PREPARATION TEST PASSED")
    log("=" * 80)

    return 0


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="SENSEX 09:15 market recorder runner"
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help="Run without the normal trading-day restriction."
    )

    parser.add_argument(
        "--preparation-test",
        action="store_true",
        help="Test Dhan authentication and recorder preparation without recording."
    )

    args = parser.parse_args()

    log("Morning runner started.")

    if args.preparation_test:
        return run_preparation_test()

    today = now_ist().date()

    # --------------------------------------------------------
    # Trading day validation
    # --------------------------------------------------------

    if not args.test:

        if is_weekend(today):
            log(
                f"{today} is weekend. "
                "Nothing to record."
            )
            return 0

        if is_nse_holiday(today):
            log(
                f"{today} is an NSE holiday. "
                "Nothing to record."
            )
            return 0

    # --------------------------------------------------------
    # Check whether we have already missed recording window
    # --------------------------------------------------------

    current_time = now_ist().time()

    if current_time >= RECORD_END:
        log(
            f"Current time {current_time} is already after "
            f"recording end {RECORD_END}. Exiting."
        )
        return 0

    # --------------------------------------------------------
    # IMPORTANT:
    # Authentication/preparation happens BEFORE 09:14:30.
    # --------------------------------------------------------

    log("Loading Dhan configuration.")

    client_id, pin, totp_secret = load_config()

    log("Generating fresh Dhan access token.")

    access_token = generate_access_token(
        client_id,
        pin,
        totp_secret
    )

    log("Validating Dhan access token.")

    validate_access_token(access_token)

    # --------------------------------------------------------
    # Launch recorder BEFORE 09:15.
    #
    # The recorder establishes the WebSocket and subscribes
    # before the market opens.
    # --------------------------------------------------------

    current_time = now_ist().time()

    if current_time < PREP_TIME:

        log(
            f"Waiting until preparation checkpoint "
            f"{PREP_TIME} IST."
        )

        wait_until(PREP_TIME)

    log(
        "Preparation checkpoint reached. "
        "Starting recorder before market open."
    )

    process = launch_recorder(access_token)

    # --------------------------------------------------------
    # Wait for recorder to finish.
    # --------------------------------------------------------

    return_code = process.wait()

    log(
        f"Recorder process finished with exit code "
        f"{return_code}."
    )

    if return_code != 0:
        raise RuntimeError(
            f"Recorder failed with exit code {return_code}."
        )

    log("Morning runner completed successfully.")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())

    except KeyboardInterrupt:
        log("Interrupted by user.")
        sys.exit(130)

    except Exception as exc:
        log(f"FATAL ERROR: {exc}")
        sys.exit(1)