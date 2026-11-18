#!/usr/bin/env bash
# Serve several vLLM instances in parallel on one MI300X node.
#
# On an 8-GPU MI300X node each GPU is 192 GB of HBM3. Models in the 7B-32B
# range fit on one GPU with room to spare, so the win here is data parallelism:
# one independent vLLM server per GPU, each holding its own model, each with
# its own OpenAI-compatible port. Total throughput scales roughly linearly.
#
# Tensor parallelism (TP=8) would be the wrong tool here: it shards one model
# across all eight GPUs and adds communication overhead, which buys nothing for
# a model that already fits on one card.
#
# Usage on the droplet:
#   ./serve-parallel.sh list                 # what would be started
#   ./serve-parallel.sh start                # launch all, wait for health
#   ./serve-parallel.sh stop                 # stop all
#   ./serve-parallel.sh health               # per-model health check
#
set -uo pipefail
cd "$(dirname "$0")"

RUN_DIR="${RUN_DIR:-/root/serve}"
LOG_DIR="${LOG_DIR:-/root/serve/logs}"
MODEL_DIR="${MODEL_DIR:-/root/models}"
PORT_BASE="${PORT_BASE:-8000}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-12288}"
GPU_UTIL="${GPU_UTIL:-0.82}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-128}"
CONTAINER="${CONTAINER:-rocm}"

# name|model-path|port-offset
# Each entry gets its own GPU via CUDA_VISIBLE_DEVICES/ROCR_VISIBLE_DEVICES.
# Models are read from a local directory; download them first (see README).
MODELS=(
  "qwen25-coder-14b|qwen25-coder-14b|0"
  "qwen25-coder-32b|qwen25-coder-32b|1"
  "llama31-8b|llama31-8b|2"
  "llama31-70b|llama31-70b|3"
  "deepseek-coder-v2-lite|deepseek-coder-v2-lite|4"
  "qwen3-30b-a3b|qwen3-30b-a3b|5"
  "mistral-small-3.1-24b|mistral-small-3.1-24b|6"
  "gemma-3-27b-it|gemma-3-27b-it|7"
)

info() { printf '\033[36m::\033[0m %s\n' "$*"; }
ok()   { printf '\033[32mok\033[0m  %s\n' "$*"; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

nvidia_smi_equivalent() {
  if command -v rocm-smi >/dev/null 2>&1; then rocm-smi --showproductname 2>/dev/null; return; fi
  if command -v rocminfo >/dev/null 2>&1; then rocminfo 2>/dev/null | grep -i "Marketing Name"; return; fi
  echo "no rocm-smi/rocminfo on PATH"
}

count_gpus() {
  local n=0
  if command -v rocm-smi >/dev/null 2>&1; then
    n="$(rocm-smi --showid 2>/dev/null | grep -cE 'GPU\[[0-9]+\]' || true)"
  fi
  [ "$n" -eq 0 ] && n="$(ls -d /sys/class/kfd/kfd/topology/nodes/* 2>/dev/null | wc -l)"
  echo "$n"
}

cmd_list() {
  printf '%-26s %-14s %-6s %s\n' NAME MODEL PORT GPU
  local i=0
  for entry in "${MODELS[@]}"; do
    IFS='|' read -r name path off <<<"$entry"
    printf '%-26s %-14s %-6s %s\n' "$name" "$path" "$((PORT_BASE+off))" "$off"
    i=$((i+1))
  done
  printf '\n%d slots defined\n' "$i"
}

wait_healthy() {  # wait_healthy <port> <name>
  local port="$1" name="$2" waited=0
  while [ "$waited" -lt 300 ]; do
    if curl -sS --max-time 3 "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
      ok "$name healthy on port $port (${waited}s)"
      return 0
    fi
    sleep 5; waited=$((waited+5))
  done
  printf '\033[31merror:\033[0m %s did not become healthy within 300s\n' "$name" >&2
  printf '  last log lines:\n' >&2
  tail -n 15 "$LOG_DIR/${name}.log" 2>/dev/null | sed 's/^/    /' >&2
  return 1
}

cmd_start() {
  command -v docker >/dev/null 2>&1 || die "docker not found"
  docker ps --format '{{.Names}}' | grep -qx "$CONTAINER" || die "container '$CONTAINER' not running.
On the AMD DevCloud vLLM image the container is named 'rocm'. If it is not up:
  docker ps -a
  docker start $CONTAINER"

  local ngpu; ngpu="$(count_gpus)"
  info "detected $ngpu GPU(s)"
  [ "$ngpu" -gt 0 ] || die "no GPUs detected"

  mkdir -p "$LOG_DIR" "$MODEL_DIR"

  local started=0 failed=0
  for entry in "${MODELS[@]}"; do
    IFS='|' read -r name path off <<<"$entry"
    [ "$off" -lt "$ngpu" ] || { info "skipping $name (needs GPU $off, have $ngpu)"; continue; }
    local model_path="$MODEL_DIR/$path"
    if [ ! -d "$model_path" ]; then
      info "skipping $name (no model at $model_path)"
      continue
    fi
    local port=$((PORT_BASE+off))
    if curl -sS --max-time 2 "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
      info "$name already serving on $port"
      continue
    fi

    info "starting $name on GPU $off, port $port"
    docker exec -d \
      -e "HIP_VISIBLE_DEVICES=$off" \
      -e "ROCR_VISIBLE_DEVICES=$off" \
      -e "CUDA_VISIBLE_DEVICES=$off" \
      -e "HSA_OVERRIDE_GFX_VERSION=11.0.0" \
      "$CONTAINER" \
      vllm serve "$model_path" \
        --host 0.0.0.0 --port "$port" \
        --dtype bfloat16 \
        --max-model-len "$MAX_MODEL_LEN" \
        --gpu-memory-utilization "$GPU_UTIL" \
        --max-num-seqs "$MAX_NUM_SEQS" \
        --enable-prefix-caching \
        --disable-log-requests \
      > "$LOG_DIR/${name}.log" 2>&1

    started=$((started+1))
  done

  info "launched $started instance(s); waiting for health"
  for entry in "${MODELS[@]}"; do
    IFS='|' read -r name path off <<<"$entry"
    local port=$((PORT_BASE+off))
    if curl -sS --max-time 2 "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then continue; fi
    if grep -q "Starting vLLM API server\|Application startup complete" "$LOG_DIR/${name}.log" 2>/dev/null; then
      wait_healthy "$port" "$name" || failed=$((failed+1))
    fi
  done

  if [ "$failed" -gt 0 ]; then
    die "$failed instance(s) failed to start; see $LOG_DIR"
  fi
  ok "all instances up"
  cmd_health
}

cmd_health() {
  printf '%-26s %-6s %s\n' NAME PORT STATUS
  for entry in "${MODELS[@]}"; do
    IFS='|' read -r name path off <<<"$entry"
    local port=$((PORT_BASE+off))
    local st="down"
    if curl -sS --max-time 3 "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
      st="healthy"
    elif curl -sS --max-time 3 "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
      st="responding"
    fi
    printf '%-26s %-6s %s\n' "$name" "$port" "$st"
  done
}

cmd_stop() {
  command -v docker >/dev/null 2>&1 || die "docker not found"
  info "stopping vLLM processes inside $CONTAINER"
  docker exec "$CONTAINER" pkill -f "vllm serve" || true
  ok "stopped"
}

case "${1:-}" in
  list)   cmd_list ;;
  start)  cmd_start ;;
  stop)   cmd_stop ;;
  health) cmd_health ;;
  *) sed -n '2,20p' "$0"; exit 1 ;;
esac
