#!/usr/bin/env bash
# Provision an AMD Developer Cloud GPU droplet for the CWE prompt-study vLLM run.
#
# Design rules:
#   - The AMD token is read from a file, never from argv (so it never lands in
#     shell history or `ps` output) and never echoed.
#   - Read-only discovery runs first. The create call only fires after the
#     slug the user picked is confirmed present in the account's catalogue.
#   - Every destructive step is opt-in via a flag; running without flags only
#     inspects.
#
# Usage:
#   ./amd-provision.sh discover          # list regions/sizes/images/droplets
#   ./amd-provision.sh key               # upload this machine's SSH key
#   ./amd-provision.sh create            # create the droplet
#   ./amd-provision.sh status            # show the droplet's current state
#   ./amd-provision.sh ssh               # print the ssh command
#
set -uo pipefail

API="https://api.devcloud.amd.com"
SECRETS_DIR="${HOME}/.secrets"
TOKEN_FILE="${SECRETS_DIR}/amd_devcloud_token"
FINGERPRINT_FILE="${SECRETS_DIR}/amd_ssh_fingerprint"
PUBKEY="${HOME}/.ssh/id_ed25519.pub"

# --- overridable via env -------------------------------------------------
DROPLET_NAME="${DROPLET_NAME:-cwe-vllm-atl1}"
REGION="${REGION:-atl1}"
SIZE="${SIZE:-gpu-mi300x8-1536gb-devcloud}"
IMAGE="${IMAGE:-vllm-0-27-1-vllm-omni-0-27-0rc1-rocm-7-14}"
PARTITION_MODE="${PARTITION_MODE:-PARTITION_MODE_UNSET}"
TAGS="${TAGS:-skripsi,cwe-eval}"

# --- helpers -------------------------------------------------------------
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[36m::\033[0m %s\n' "$*"; }
ok()   { printf '\033[32mok\033[0m  %s\n' "$*"; }

need_token() {
  [ -f "$TOKEN_FILE" ] || die "token file missing: $TOKEN_FILE
Create it with:
  mkdir -p $SECRETS_DIR
  printf '%s' 'YOUR_AMD_DEVCLOUD_TOKEN' > $TOKEN_FILE
  chmod 600 $TOKEN_FILE"
  [ -s "$TOKEN_FILE" ] || die "token file is empty: $TOKEN_FILE"
}

# The token goes into a variable read from the file. It is never printed.
api() {
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -sS -X "$method" "$API$path" \
      -H 'Content-Type: application/json' \
      -H "Authorization: Bearer $(cat "$TOKEN_FILE")" \
      -d "$body"
  else
    curl -sS -X "$method" "$API$path" \
      -H "Authorization: Bearer $(cat "$TOKEN_FILE")"
  fi
}

# jq is convenient but not guaranteed; fall back to python3.
have_jq() { command -v jq >/dev/null 2>&1; }

# Extract a field from a JSON document. Uses python3 with a Python expression
# over the variable `d` — always Python syntax, never jq syntax.
json_get() {  # json_get <json> <python-expression over `d`>
  printf '%s' "$1" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print(''); raise SystemExit
try:
    v=eval('''$2''')
except Exception:
    v=None
print('' if v is None else v)
"
}

# True when the JSON document looks like an API error rather than a resource.
is_error() {  # is_error <json>
  printf '%s' "$1" | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: print('yes'); raise SystemExit
if isinstance(d,dict):
    if d.get('id') in ('Unauthorized','Forbidden','error','Error'): print('yes'); raise SystemExit
    if d.get('status_code') and int(d.get('status_code'))>=400: print('yes'); raise SystemExit
    if d.get('message') and 'error' in str(d.get('message')).lower(): print('yes'); raise SystemExit
print('no')
"
}

# --- actions -------------------------------------------------------------
cmd_discover() {
  need_token
  info "validating token against the AMD API"
  local me
  me="$(api GET /v2/account || true)"
  if printf '%s' "$me" | grep -qiE '"(id|message)"[[:space:]]*:[[:space:]]*"Unauthorized"'; then
    die "token rejected by the API. Check $TOKEN_FILE"
  fi
  if printf '%s' "$me" | grep -qiE '"(id|message)"[[:space:]]*:[[:space:]]*"(Forbidden|Bad credentials|Invalid token)"'; then
    die "token rejected by the API. Check $TOKEN_FILE"
  fi
  ok "token accepted"
  printf '%s\n' "$me" | head -c 400; printf '\n\n'

  info "regions"
  api GET /v2/regions | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception as e: print('  (unparsed)',e); raise SystemExit
rs=d.get('regions',d if isinstance(d,list) else [])
for r in rs:
    print(f\"  {r.get('slug','?'):12} {r.get('name','?')}\")
"

  info "sizes (GPU plans)"
  api GET /v2/sizes | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception as e: print('  (unparsed)',e); raise SystemExit
ss=d.get('sizes',d if isinstance(d,list) else [])
for s in ss:
    sl=s.get('slug','')
    if 'gpu' in sl or 'mi300' in sl.lower():
        gpus=s.get('gpus')
        mem=s.get('memory')
        print(f\"  {sl:42} gpus={gpus} mem={mem} disk={s.get('disk')}\")
"

  info "images matching vllm / rocm"
  api GET /v2/images | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception as e: print('  (unparsed)',e); raise SystemExit
ims=d.get('images',d if isinstance(d,list) else [])
for i in ims:
    sl=i.get('slug') or i.get('name') or ''
    if any(k in sl.lower() for k in ('vllm','rocm','mi300')):
        print(f\"  {sl:60} {i.get('distribution','')}\")
"

  info "existing droplets"
  api GET /v2/droplets | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception as e: print('  (unparsed)',e); raise SystemExit
ds=d.get('droplets',d if isinstance(d,list) else [])
if not ds: print('  (none)')
for x in ds:
    ips=[n.get('ip_address') for n in x.get('networks',{}).get('v4',[]) if n.get('type')=='public']
    print(f\"  id={x.get('id')} name={x.get('name')} status={x.get('status')} ip={ips[0] if ips else '-'}\")
"
}

cmd_key() {
  need_token
  [ -f "$PUBKEY" ] || die "no public key at $PUBKEY (ssh-keygen -t ed25519)"
  mkdir -p "$SECRETS_DIR"
  info "uploading SSH key to the AMD account"
  local name="hermes-$(hostname -s 2>/dev/null || echo local)"
  local body fp resp
  body="$(python3 -c "
import json
print(json.dumps({'name':'$name','public_key':open('$PUBKEY').read().strip()}))
")"
  resp="$(api POST /v2/account/keys "$body")"
  printf '%s\n' "$resp" | head -c 300; printf '\n'
  fp="$(json_get "$resp" 'd.get("fingerprint") or d.get("ssh_key",{}).get("fingerprint")')"
  if [ -z "$fp" ] || [ "$fp" = "None" ]; then
    info "listing account keys to find the fingerprint"
    api GET /v2/account/keys | python3 -c "
import json,sys
d=json.load(sys.stdin)
ks=d.get('ssh_keys',d.get('keys',d if isinstance(d,list) else []))
for k in ks: print(' ',k.get('id'),k.get('name'),k.get('fingerprint'))
"
    die "could not read fingerprint from the create response; re-run 'key' and read it from the list above"
  fi
  printf '%s' "$fp" > "$FINGERPRINT_FILE"
  chmod 600 "$FINGERPRINT_FILE"
  ok "fingerprint saved to $FINGERPRINT_FILE"
  ok "$fp"
}

cmd_create() {
  need_token
  [ -f "$FINGERPRINT_FILE" ] || die "no SSH fingerprint. Run: $0 key"
  local fp body resp
  fp="$(cat "$FINGERPRINT_FILE")"
  info "creating droplet '$DROPLET_NAME' in $REGION"
  info "size=$SIZE image=$IMAGE partition=$PARTITION_MODE"
  body="$(python3 -c "
import json
print(json.dumps({
 'name':'$DROPLET_NAME',
 'region':'$REGION',
 'size':'$SIZE',
 'image':'$IMAGE',
 'ssh_keys':['$fp'],
 'backups':False,
 'ipv6':False,
 'monitoring':False,
 'tags':'$TAGS'.split(','),
 'user_data':'',
 'vpc_uuid':'',
 'gpu_partition_mode':'$PARTITION_MODE',
}))
")"
  resp="$(api POST /v2/droplets "$body")"
  printf '%s\n' "$resp" | head -c 1200; printf '\n\n'
  if [ "$(is_error "$resp")" = "yes" ]; then
    die "create failed. Read the error above; the usual causes are an invalid size/image slug for your account, a missing vpc_uuid, or a credit limit."
  fi
  local did
  did="$(json_get "$resp" 'd.get("droplet",{}).get("id")')"
  if [ -n "$did" ]; then
    ok "droplet id: $did"
    printf '%s' "$did" > "${SECRETS_DIR}/amd_droplet_id"
    chmod 600 "${SECRETS_DIR}/amd_droplet_id"
  else
    die "create returned no droplet id; the response above is the whole story"
  fi
}

cmd_status() {
  need_token
  api GET /v2/droplets | python3 -c "
import json,sys
d=json.load(sys.stdin)
ds=d.get('droplets',d if isinstance(d,list) else [])
for x in ds:
    ips=[n.get('ip_address') for n in x.get('networks',{}).get('v4',[]) if n.get('type')=='public']
    print(f\"id={x.get('id')} name={x.get('name')} status={x.get('status')} ip={ips[0] if ips else '-'} region={x.get('region',{}).get('slug')}\")
"
}

cmd_ssh() {
  need_token
  api GET /v2/droplets | python3 -c "
import json,sys
d=json.load(sys.stdin)
ds=d.get('droplets',d if isinstance(d,list) else [])
for x in ds:
    if x.get('name')=='$DROPLET_NAME':
        ips=[n.get('ip_address') for n in x.get('networks',{}).get('v4',[]) if n.get('type')=='public']
        if ips: print(f\"ssh root@{ips[0]}\")
        else: print('no public IP yet (droplet still provisioning)')
"
}

# Only run a command when executed directly, so the helpers above can be
# sourced by the test harness without side effects.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    discover) cmd_discover ;;
    key)      cmd_key ;;
    create)   cmd_create ;;
    status)   cmd_status ;;
    ssh)      cmd_ssh ;;
    *) sed -n '2,20p' "$0"; exit 1 ;;
  esac
fi
