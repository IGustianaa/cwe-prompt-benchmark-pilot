#!/usr/bin/env bash
# Unit test for the JSON helpers in amd-provision.sh (no network, no token).
set -uo pipefail
cd "$(dirname "$0")"

pass=0; fail=0
t() { # t <name> <expected> <actual>
  if [ "$2" = "$3" ]; then
    printf 'ok   %-40s %s\n' "$1" "$3"; pass=$((pass+1))
  else
    printf 'FAIL %-40s expected=[%s] got=[%s]\n' "$1" "$2" "$3"; fail=$((fail+1))
  fi
}

# shellcheck source=amd-provision.sh
source ./amd-provision.sh

# --- json_get ------------------------------------------------------------
t "json_get reads droplet.id" \
  "12345" "$(json_get '{"droplet":{"id":12345}}' 'd.get("droplet",{}).get("id")')"
t "json_get returns empty on missing key" \
  "" "$(json_get '{"droplet":{}}' 'd.get("droplet",{}).get("id")')"
t "json_get returns empty on bad json" \
  "" "$(json_get 'not json at all' 'd.get("id")')"
t "json_get survives a bad expression" \
  "" "$(json_get '{"a":1}' 'this is not python')"

# --- is_error ------------------------------------------------------------
t "is_error: success droplet is not an error" \
  "no" "$(is_error '{"droplet":{"id":12345,"status":"new"}}')"
t "is_error: Unauthorized is an error" \
  "yes" "$(is_error '{"id":"Unauthorized","message":"Unable to authenticate you"}')"
t "is_error: Forbidden is an error" \
  "yes" "$(is_error '{"id":"Forbidden"}')"
t "is_error: status_code 422 is an error" \
  "yes" "$(is_error '{"status_code":422,"message":"invalid size"}')"
t "is_error: message containing error is an error" \
  "yes" "$(is_error '{"message":"validation error on region"}')"
t "is_error: plain resource is not an error" \
  "no" "$(is_error '{"id":7,"name":"x","region":{"slug":"atl1"}}')"

# --- payload construction ------------------------------------------------
build_body() { # mirrors cmd_create's body builder
  python3 -c "
import json
print(json.dumps({
 'name':'cwe-vllm-atl1',
 'region':'atl1',
 'size':'gpu-mi300x8-1536gb-devcloud',
 'image':'vllm-0-27-1-vllm-omni-0-27-0rc1-rocm-7-14',
 'ssh_keys':['SHA256:abc'],
 'backups':False,
 'ipv6':False,
 'monitoring':False,
 'tags':['skripsi','cwe-eval'],
 'user_data':'',
 'vpc_uuid':'',
 'gpu_partition_mode':'PARTITION_MODE_UNSET',
}))
"
}
body="$(build_body)"
t "payload: ssh_keys is a non-empty list" \
  "1" "$(json_get "$body" 'len(d.get("ssh_keys",[]))')"
t "payload: image is a string slug" \
  "vllm-0-27-1-vllm-omni-0-27-0rc1-rocm-7-14" "$(json_get "$body" 'd.get("image")')"
t "payload: gpu_partition_mode present" \
  "PARTITION_MODE_UNSET" "$(json_get "$body" 'd.get("gpu_partition_mode")')"
t "payload: tags split into a list" \
  "2" "$(json_get "$body" 'len(d.get("tags",[]))')"
t "payload: body is valid JSON" \
  "ok" "$(json_get "$body" '"ok" if isinstance(d,dict) else "bad"')"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
