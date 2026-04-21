#!/usr/bin/env bash
# Runs all load test combinations: 2 brokers × 4 sizes × 3 rates = 24 experiments
# Usage: bash run_all.sh [duration_sec]

set -euo pipefail

DURATION=${1:-60}
BROKERS=("rabbitmq" "redis")
SIZES=("128B" "1KB" "10KB" "100KB")
RATES=(1000 5000 10000)
TOTAL=$(( ${#BROKERS[@]} * ${#SIZES[@]} * ${#RATES[@]} ))
CURRENT=0

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "Starting $TOTAL experiments (duration=${DURATION}s each)"
log "Estimated total time: $(( TOTAL * DURATION / 60 )) min"
echo ""

for BROKER in "${BROKERS[@]}"; do
    for SIZE in "${SIZES[@]}"; do
        for RATE in "${RATES[@]}"; do
            CURRENT=$(( CURRENT + 1 ))
            log "[$CURRENT/$TOTAL] broker=$BROKER size=$SIZE rate=$RATE"

            python run_test.py \
                --broker "$BROKER" \
                --size   "$SIZE"   \
                --rate   "$RATE"   \
                --duration "$DURATION" || {
                log "ERROR: experiment failed (broker=$BROKER size=$SIZE rate=$RATE)"
            }

            sleep 3
        done
    done
done

echo ""
log "All $TOTAL experiments done. Results saved in ./results/"

python3 - <<'EOF'
import json, os, glob

files = sorted(glob.glob("results/*.json"))
if not files:
    print("No results found.")
    exit()

seen = {}
for path in files:
    with open(path) as f:
        r = json.load(f)
    key = (r['broker'], r['message_size_bytes'], r['target_rate_msg_per_sec'])
    seen[key] = r

rows = sorted(seen.values(), key=lambda r: (r['broker'], r['message_size_bytes'], r['target_rate_msg_per_sec']))

header = (
    f"{'broker':<10} {'size':>7} {'rate':>7} {'sent':>8} {'recv':>8} {'lost':>6} "
    f"{'prod_tps':>9} {'cons_tps':>9} {'avg_ms':>8} {'p95_ms':>8} {'max_ms':>8}"
)
sep = "-" * len(header)

print("\n" + sep)
print(header)
print(sep)
for r in rows:
    print(
        f"{r['broker']:<10} "
        f"{r['message_size_bytes']:>7} "
        f"{r['target_rate_msg_per_sec']:>7} "
        f"{r['sent']:>8} "
        f"{r['received']:>8} "
        f"{r['lost']:>6} "
        f"{r['producer_throughput_msg_per_sec']:>9} "
        f"{r['consumer_throughput_msg_per_sec']:>9} "
        f"{r['latency_avg_ms']:>8} "
        f"{r['latency_p95_ms']:>8} "
        f"{r['latency_max_ms']:>8}"
    )
print(sep + "\n")
EOF
