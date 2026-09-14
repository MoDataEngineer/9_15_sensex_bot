#!/bin/bash

set -u

BASE_DIR="/home/ubuntu/sensex-915-recorder/9_15_sensex_bot"
PYTHON="/home/ubuntu/sensex-915-recorder/.venv/bin/python"

cd "$BASE_DIR" || exit 1

RUN_DATE=$(date +%F)

echo "========================================"
echo "SENSEX daily run started: $(date)"
echo "Run date: $RUN_DATE"
echo "========================================"

echo "Running morning_runner.py..."

"$PYTHON" "$BASE_DIR/morning_runner.py"
RUNNER_STATUS=$?

if [ "$RUNNER_STATUS" -ne 0 ]; then
    echo "ERROR: morning_runner.py failed with exit code $RUNNER_STATUS."
    echo "GitHub publishing will NOT run."
    exit "$RUNNER_STATUS"
fi

echo "morning_runner.py completed successfully."

DATE_DIR="$BASE_DIR/$RUN_DATE"

if [ ! -d "$DATE_DIR" ]; then
    echo "No dataset folder found for $RUN_DATE."
    echo "This is expected for weekends/NSE holidays."
    echo "Nothing will be published to GitHub."
    exit 0
fi

echo "Dataset folder found: $DATE_DIR"
echo "Starting GitHub publishing..."

"$PYTHON" "$BASE_DIR/daily_publisher.py" --date "$RUN_DATE"
PUBLISH_STATUS=$?

if [ "$PUBLISH_STATUS" -ne 0 ]; then
    echo "ERROR: GitHub publishing failed with exit code $PUBLISH_STATUS."
    exit "$PUBLISH_STATUS"
fi

echo "========================================"
echo "SUCCESS: Daily dataset completed and pushed to GitHub."
echo "Completed: $(date)"
echo "========================================"

exit 0
