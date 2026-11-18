#!/usr/bin/env bash
# Drive the full P0/P1/P2 matrix across every running vLLM instance.
#
# One worker per GPU, each pointed at its own local server port. Each worker
# takes a disjoint shard of the selected cases, so no case is processed twice
# and no worker waits on another's cases.
#
# The run is resumable: the output file is opened in append mode and rows
# already present (same sample_id + condition + seed) are skipped on restart.
#
# Usage on the droplet:
#   ./run-all.sh --cases 20 --seeds 1          # pilot
#   ./run-all.sh --cases 1000 --seeds 5        # full
#   ./run-all.sh --cases 1000 --seeds 5 --dry-run
#
set -uo pipefail
cd "$(dirname "$0")"

PORT_BASE="${PORT_BASE:-8000}"
N_WORKERS="${N_WORKERS:-8}"
DATA="${DATA:-data/vuldetectbench_task1_code.jsonl}"
PROTOCOL="${PROTOCOL:-protokol_prompt_cwe_v0.1.md}"
CWE_SPECS="${CWE_SPECS:-}"
OUT="${OUT:-runs/matrix.jsonl}"
EXTRA=()
DRY=0

info() { printf '\033[36m::\033[0m %s\n' "$*"; }
ok()   { printf '\033[32mok\033[0m  %s\n' "$*"; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --cases)   EXTRA+=(--cases "$2"); shift 2 ;;
    --seeds)   EXTRA+=(--seeds "$2"); shift 2 ;;
    --out)     OUT="$2"; EXTRA+=(--out "$2"); shift 2 ;;
    --cwe)     EXTRA+=(--cwe "$2"); shift 2 ;;
    --conditions) EXTRA+=(--conditions "$2"); shift 2 ;;
    --case-seed) EXTRA+=(--case-seed "$2"); shift 2 ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

mkdir -p "$(dirname "$OUT")"

# How many instances are actually up right now.
live=0
live_ports=()
for i in $(seq 0 $((N_WORKERS-1))); do
  port=$((PORT_BASE+i))
  if curl -sS --max-time 3 "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
    live_ports+=("$port")
    live=$((live+1))
  fi
done

info "instances healthy: $live of $N_WORKERS"
if [ "$live" -eq 0 ]; then
  die "no vLLM instance is responding on ports $PORT_BASE..$((PORT_BASE+N_WORKERS-1)).
Start them first:  ./serve-parallel.sh start"
fi

if [ "$DRY" -eq 1 ]; then
  ok "dry run, not writing anything"
  for p in "${live_ports[@]}"; do
    info "worker -> http://127.0.0.1:$p"
    python3 run_matrix.py --data "$DATA" --protocol "$PROTOCOL" \
      --out "$OUT" --base-url "http://127.0.0.1:$p" \
      --shard-count "$live" --shard-index 0 \
      ${CWE_SPECS:+--cwe-specs "$CWE_SPECS"} "${EXTRA[@]}" --dry-run 2>&1 | head -5
  done
  exit 0
fi

# Launch one worker per live port.
pids=()
for idx in "${!live_ports[@]}"; do
  port="${live_ports[$idx]}"
  info "worker $idx -> port $port (shard $idx/$live)"
  python3 run_matrix.py \
    --data "$DATA" --protocol "$PROTOCOL" \
    --out "$OUT" --base-url "http://127.0.0.1:$port" \
    --model "instance-$port" \
    --shard-count "$live" --shard-index "$idx" \
    ${CWE_SPECS:+--cwe-specs "$CWE_SPECS"} \
    "${EXTRA[@]}" &
  pids+=($!)
done

info "workers launched: ${#pids[@]}"
fail=0
for pid in "${pids[@]}"; do
  wait "$pid" || fail=$((fail+1))
done

if [ "$fail" -gt 0 ]; then
  die "$fail worker(s) exited non-zero. Partial results are in $OUT and are usable; rerun to resume."
fi

lines=$(wc -l < "$OUT" 2>/dev/null || echo 0)
ok "done. $lines rows in $OUT"
