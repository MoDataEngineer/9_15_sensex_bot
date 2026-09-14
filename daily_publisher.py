#!/usr/bin/env python3

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def run_command(command, check=True):
    print(f"$ {' '.join(command)}")
    result = subprocess.run(
        command,
        cwd=BASE_DIR,
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print(result.stdout, end="")

    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}: {' '.join(command)}"
        )

    return result


def publish(run_date):
    if not DATE_PATTERN.match(run_date):
        raise ValueError(f"Invalid date folder: {run_date}")

    date_dir = BASE_DIR / run_date

    if not date_dir.is_dir():
        raise FileNotFoundError(f"Daily folder does not exist: {date_dir}")

    csv_files = sorted(date_dir.glob("session_ticks_*.csv"))
    json_files = sorted(date_dir.glob("session_contracts_*.json"))

    if not csv_files:
        raise FileNotFoundError(
            f"No session_ticks_*.csv found in {date_dir}"
        )

    if not json_files:
        raise FileNotFoundError(
            f"No session_contracts_*.json found in {date_dir}"
        )

    print(f"Daily folder: {date_dir}")
    print(f"CSV files found: {len(csv_files)}")
    print(f"JSON files found: {len(json_files)}")

    for path in csv_files:
        print(f"  CSV : {path.name}")

    for path in json_files:
        print(f"  JSON: {path.name}")

    # Make sure the repository is not carrying unrelated staged changes.
    status = run_command(["git", "status", "--porcelain"])

    for line in status.stdout.splitlines():
        if line.startswith(("A ", "M ", "D ", "R ", "C ", "U ")) and not line.startswith("??"):
            raise RuntimeError(
                "Repository has staged changes before publishing. "
                "Refusing to continue."
            )

    # Stage ONLY today's date folder.
    run_command(["git", "add", "--", run_date])

    staged = run_command(["git", "diff", "--cached", "--name-only"])

    staged_files = [
        line.strip()
        for line in staged.stdout.splitlines()
        if line.strip()
    ]

    expected_prefix = f"{run_date}/"

    if not staged_files:
        print(f"ALREADY PUBLISHED: {run_date} dataset is already in Git.")
        return

    unexpected = [
        path for path in staged_files
        if not path.startswith(expected_prefix)
    ]

    if unexpected:
        raise RuntimeError(
            "Unexpected files were staged: " + ", ".join(unexpected)
        )

    print("Staged files:")
    for path in staged_files:
        print(f"  {path}")

    commit_message = f"data: SENSEX 9:15 session {run_date}"

    run_command(["git", "commit", "-m", commit_message])
    run_command(["git", "push", "origin", "main"])

    print()
    print(f"SUCCESS: {run_date} dataset pushed to GitHub.")


def main():
    parser = argparse.ArgumentParser(
        description="Publish one dated SENSEX 9:15 dataset folder to GitHub."
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Date folder to publish in YYYY-MM-DD format.",
    )

    args = parser.parse_args()

    try:
        publish(args.date)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
