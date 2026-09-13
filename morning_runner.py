import os
import sys
import time
import subprocess
import argparse
from datetime import datetime, date
from pathlib import Path

import requests
import pyotp
from dotenv import dotenv_values


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
RECORDER_PATH = BASE_DIR / "record_915_session.py"

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / f"morning_runner_{date.today().strftime('%Y%m%d')}.log"

NSE_HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
DHAN_TOKEN_URL = "https://auth.dhan.co/app/generateAccessToken"
DHAN_PROFILE_URL = "https://api.dhan.co/v2/profile"

# TOTP codes use a 30-second time step. Avoid starting authentication in the
# final few seconds of the current window, where a boundary race is possible.
TOTP_PERIOD = 30
TOTP_MIN_REMAINING_SECONDS = 5
TOTP_RETRY_DELAY = 0.75


def log(message):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_config():
    cfg = dotenv_values(ENV_PATH)
    required = ["DHAN_CLIENT_ID", "DHAN_PIN", "DHAN_TOTP_SECRET"]
    missing = [key for key in required if not cfg.get(key)]
    if missing:
        raise RuntimeError("Missing required .env values: " + ", ".join(missing))
    return cfg


def is_weekend(day=None):
    day = day or date.today()
    return day.weekday() >= 5


def get_nse_holidays():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/142.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.nseindia.com/",
    }
    session = requests.Session()
    session.headers.update(headers)
    session.get("https://www.nseindia.com/", timeout=10)
    response = session.get(NSE_HOLIDAY_URL, timeout=10)
    response.raise_for_status()
    data = response.json()

    holidays = set()
    for group in data.values():
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            raw_date = item.get("tradingDate") or item.get("date")
            if not raw_date:
                continue
            for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
                try:
                    holidays.add(datetime.strptime(raw_date, fmt).date())
                    break
                except ValueError:
                    pass
    return holidays


def trading_day_check():
    today = date.today()
    if is_weekend(today):
        log(f"Today is {today} ({today.strftime('%A')}); no regular 09:15 session.")
        return False

    try:
        holidays = get_nse_holidays()
    except Exception as exc:
        log(f"Could not verify NSE holiday calendar: {type(exc).__name__}.")
        log("Failing closed; recorder will NOT be started.")
        return False

    if today in holidays:
        log(f"Today ({today}) is listed as an NSE trading holiday.")
        return False

    log(f"Trading-day check passed for {today}.")
    return True


def seconds_remaining_in_totp_window():
    return TOTP_PERIOD - (time.time() % TOTP_PERIOD)


def wait_for_safe_totp_window():
    remaining = seconds_remaining_in_totp_window()
    if remaining < TOTP_MIN_REMAINING_SECONDS:
        wait_seconds = remaining + TOTP_RETRY_DELAY
        log(
            f"TOTP window has only {remaining:.2f}s remaining; "
            f"waiting {wait_seconds:.2f}s for the next code."
        )
        time.sleep(wait_seconds)


def generate_current_totp(secret):
    return pyotp.TOTP(secret).now()


def generate_dhan_access_token(client_id, pin, totp):
    params = {"dhanClientId": client_id, "pin": pin, "totp": totp}
    response = requests.post(DHAN_TOKEN_URL, params=params, timeout=15)
    if response.status_code not in (200, 201):
        log(f"Dhan token generation failed (HTTP {response.status_code}).")
        return None

    try:
        data = response.json()
    except ValueError:
        log("Dhan token generation returned a non-JSON response.")
        return None

    token = data.get("accessToken")
    expiry = data.get("expiryTime")
    if not token:
        log("Dhan token generation succeeded but no access token was returned.")
        return None
    return token, expiry


def validate_dhan_token(token):
    response = requests.get(DHAN_PROFILE_URL, headers={"access-token": token}, timeout=15)
    if response.status_code != 200:
        log(f"Dhan token validation failed (HTTP {response.status_code}).")
        return False

    try:
        data = response.json()
    except ValueError:
        log("Dhan profile validation returned a non-JSON response.")
        return False

    status = str(data.get("status", "")).lower()
    if status and status != "success":
        log("Dhan profile validation did not return success.")
        return False
    return True


def get_fresh_dhan_token(cfg):
    client_id = cfg["DHAN_CLIENT_ID"]
    pin = cfg["DHAN_PIN"]
    secret = cfg["DHAN_TOTP_SECRET"]

    # Normal path: do not use a code that is about to expire.
    wait_for_safe_totp_window()
    totp = generate_current_totp(secret)
    result = generate_dhan_access_token(client_id, pin, totp)

    if result is None:
        # Boundary race/transient rejection: wait for the next TOTP window
        # and retry exactly once with a freshly generated code.
        remaining = seconds_remaining_in_totp_window()
        wait_seconds = remaining + TOTP_RETRY_DELAY
        log(f"Retrying Dhan authentication with the next TOTP window after {wait_seconds:.2f}s.")
        time.sleep(wait_seconds)
        totp = generate_current_totp(secret)
        result = generate_dhan_access_token(client_id, pin, totp)
        if result is None:
            raise RuntimeError("Dhan access-token generation failed after retry.")

    token, expiry = result
    if not validate_dhan_token(token):
        raise RuntimeError("Fresh Dhan access token failed profile validation.")

    log(f"Fresh Dhan access token validated successfully. Expiry: {expiry}")
    return token


def update_env_access_token(token):
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    output = []
    found = False
    for line in lines:
        if line.startswith("DHAN_ACCESS_TOKEN="):
            output.append(f"DHAN_ACCESS_TOKEN={token}")
            found = True
        else:
            output.append(line)
    if not found:
        output.append(f"DHAN_ACCESS_TOKEN={token}")
    ENV_PATH.write_text("\n".join(output) + "\n", encoding="utf-8")


def wait_until_recording_window():
    from datetime import time as dtime

    start_time = dtime(9, 14, 45)
    end_time = dtime(9, 16, 0)
    now = datetime.now()
    current_time = now.time()

    if current_time > end_time:
        log(
            f"Current time {current_time.strftime('%H:%M:%S')} is already past "
            f"the recording window ending at 09:16:00. Recorder will not be started."
        )
        return False

    if current_time < start_time:
        target = datetime.combine(now.date(), start_time)
        wait_seconds = (target - now).total_seconds()
        log(
            f"Authentication completed early. Waiting {wait_seconds:.1f}s "
            f"until 09:14:45 to start recorder."
        )
        time.sleep(wait_seconds)

    log("Recording window reached: starting recorder.")


def launch_recorder():
    if not RECORDER_PATH.exists():
        raise FileNotFoundError(f"Recorder not found: {RECORDER_PATH}")

    if wait_until_recording_window() is False:
        log("No recording window available today. Runner completed safely.")
        return None

    log(f"Launching recorder: {RECORDER_PATH.name}")
    return subprocess.run(
        [sys.executable, str(RECORDER_PATH)],
        cwd=str(BASE_DIR),
        check=False,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Dhan morning authentication + 09:15 recorder launcher"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run calendar/auth/token validation and .env update, but do not start recorder.",
    )
    args = parser.parse_args()

    log("Morning runner started.")
    log(f"Runner log file: {LOG_PATH}")

    if args.dry_run:
        log("DRY-RUN MODE: recorder will NOT be started.")

    if not trading_day_check():
        return 0

    try:
        cfg = load_config()
        token = get_fresh_dhan_token(cfg)

        # Only replace the .env token after BOTH token generation and
        # profile validation have succeeded.
        update_env_access_token(token)
        log("Validated access token written to .env.")

        if args.dry_run:
            log("DRY-RUN complete: calendar + TOTP + token + validation + .env update passed.")
            return 0

        result = launch_recorder()

        if result is None:
            # Outside the recording window is an expected/safe condition,
            # not a task failure. This keeps Task Scheduler at 0x0.
            return 0

        log(f"Recorder finished with exit code {result.returncode}.")
        return result.returncode

    except Exception as exc:
        log(f"Runner stopped safely: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())