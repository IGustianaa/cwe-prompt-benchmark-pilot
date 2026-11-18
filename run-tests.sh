#!/usr/bin/env bash
# Run every test suite. No network beyond 127.0.0.1, no GPU, no token.
set -uo pipefail
cd "$(dirname "$0")"

fail=0
run() {
  printf '\n\033[1m=== %s ===\033[0m\n' "$1"
  shift
  if "$@"; then
    printf '\033[32mall green\033[0m\n'
  else
    printf '\033[31mFAILED\033[0m\n'
    fail=$((fail+1))
  fi
}

run "shell syntax"        bash -n amd-provision.sh
run "shell syntax (2)"    bash -n serve-parallel.sh
run "shell syntax (3)"    bash -n run-all.sh
run "provision helpers"   ./test-helpers.sh
run "matrix client"       python3 test_matrix.py
run "orchestrator"        python3 test_orchestrator.py
run "scorer"              python3 test_scorer.py

printf '\n'
if [ "$fail" -eq 0 ]; then
  printf '\033[32m=== every suite passed ===\033[0m\n'
else
  printf '\033[31m=== %d suite(s) failed ===\033[0m\n' "$fail"
fi
exit "$fail"
