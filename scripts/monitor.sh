#!/bin/bash
# RAPPterverse Automation Monitor
# Checks GitHub Actions workflow runs every hour and logs results.
# Run via launchd plist or manually with: nohup ./monitor.sh &

REPO="kody-w/rappterverse"
LOG_DIR="$HOME/.rappterverse-monitor"
LOG_FILE="$LOG_DIR/monitor-$(date +%Y-%m-%d).log"
STOP_FILE="$LOG_DIR/.stop"
INTERVAL=3600  # 1 hour
DURATION=86400  # 24 hours

mkdir -p "$LOG_DIR"
rm -f "$STOP_FILE"

echo "=== RAPPterverse Monitor Started ===" >> "$LOG_FILE"
echo "Started: $(date -u '+%Y-%m-%dT%H:%M:%SZ')" >> "$LOG_FILE"
echo "Will run for 24 hours. Touch $STOP_FILE to stop early." >> "$LOG_FILE"
echo "---" >> "$LOG_FILE"

START=$(date +%s)

while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START))

    # Stop conditions
    if [ $ELAPSED -ge $DURATION ]; then
        echo "[$(date -u '+%H:%M:%S')] 24 hours elapsed. Monitor complete." >> "$LOG_FILE"
        break
    fi
    if [ -f "$STOP_FILE" ]; then
        echo "[$(date -u '+%H:%M:%S')] Stop file detected. Shutting down." >> "$LOG_FILE"
        break
    fi

    echo "" >> "$LOG_FILE"
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] --- Check #$((ELAPSED / INTERVAL + 1)) ---" >> "$LOG_FILE"

    # Check recent workflow runs (last 2 hours)
    SINCE=$(date -u -v-2H '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -d '2 hours ago' '+%Y-%m-%dT%H:%M:%SZ')

    TOTAL=0
    PASSED=0
    FAILED=0
    FAILED_NAMES=""

    while IFS=$'\t' read -r status conclusion name id; do
        TOTAL=$((TOTAL + 1))
        if [ "$conclusion" = "success" ]; then
            PASSED=$((PASSED + 1))
        elif [ "$conclusion" = "failure" ]; then
            FAILED=$((FAILED + 1))
            FAILED_NAMES="$FAILED_NAMES  ❌ $name (run $id)\n"
        fi
    done < <(gh run list --repo "$REPO" --created ">$SINCE" --json status,conclusion,name,databaseId --jq '.[] | [.status, .conclusion, .name, .databaseId] | @tsv' 2>/dev/null)

    echo "  Runs in last 2h: $TOTAL (✅ $PASSED passed, ❌ $FAILED failed)" >> "$LOG_FILE"

    if [ $FAILED -gt 0 ]; then
        echo "  FAILURES:" >> "$LOG_FILE"
        echo -e "$FAILED_NAMES" >> "$LOG_FILE"
    fi

    if [ $TOTAL -eq 0 ]; then
        echo "  ⚠️  No runs found — cron may not be triggering" >> "$LOG_FILE"
    fi

    # World stats snapshot
    REPO_DIR="$HOME/Documents/GitHub/m365-agents-for-python/rappterverse"
    if [ -d "$REPO_DIR" ]; then
        cd "$REPO_DIR"
        git pull --quiet 2>/dev/null
        AGENTS=$(python3 -c "import json; print(len(json.load(open('state/agents.json'))['agents']))" 2>/dev/null || echo "?")
        ACTIONS=$(python3 -c "import json; print(len(json.load(open('state/actions.json'))['actions']))" 2>/dev/null || echo "?")
        echo "  World: $AGENTS agents, $ACTIONS actions in buffer" >> "$LOG_FILE"
    fi

    sleep $INTERVAL
done

echo "" >> "$LOG_FILE"
echo "=== Monitor Summary ===" >> "$LOG_FILE"
echo "Ended: $(date -u '+%Y-%m-%dT%H:%M:%SZ')" >> "$LOG_FILE"

# Final tally
TOTAL_RUNS=$(gh run list --repo "$REPO" --created ">$(date -u -v-24H '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%SZ')" --limit 500 --json conclusion --jq 'length' 2>/dev/null)
TOTAL_FAIL=$(gh run list --repo "$REPO" --created ">$(date -u -v-24H '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%SZ')" --limit 500 --json conclusion --jq '[.[] | select(.conclusion == "failure")] | length' 2>/dev/null)

echo "24h total: $TOTAL_RUNS runs, $TOTAL_FAIL failures" >> "$LOG_FILE"
echo "Log: $LOG_FILE" >> "$LOG_FILE"
