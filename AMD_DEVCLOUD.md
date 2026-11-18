# AMD Developer Cloud provisioning helper

Scripts to stand up a GPU droplet on the AMD Developer Cloud for the CWE
prompt-study vLLM run. No third-party dependencies: `bash`, `curl`, `python3`.

## Why this exists

The AMD Developer Cloud API is DigitalOcean-compatible (`/v2/droplets`), but
the shape of a create request differs from a plain DigitalOcean one in ways
that fail quietly or confusingly:

| Field | Consequence if wrong |
|---|---|
| `ssh_keys: []` | Droplet comes up but **cannot be logged into**. The key must be registered on the account first and passed by fingerprint. |
| `gpu_partition_mode` | Not in the stock DigitalOcean request. Selects full-GPU versus a partition on a multi-GPU plan. |
| `http://` + `//v2/...` | Silently redirects; the authorization header is dropped on the redirect hop, so the request comes back unauthenticated. |

## Setup

1. Put the token in a file. It is read from disk, never passed as an argument,
   so it stays out of shell history and out of `ps` output:

   ```
   mkdir -p ~/.secrets
   printf '%s' 'YOUR_AMD_DEVCLOUD_TOKEN' > ~/.secrets/amd_devcloud_token
   chmod 600 ~/.secrets/amd_devcloud_token
   ```

   Get the token from the AMD Developer Cloud console (API keys).

2. Make sure an SSH keypair exists at `~/.ssh/id_ed25519.pub`:

   ```
   ssh-keygen -t ed25519
   ```

## Use

```
./amd-provision.sh discover    # read-only: regions, GPU sizes, vLLM images, existing droplets
./amd-provision.sh key         # upload this machine's public key to the account, save its fingerprint
./amd-provision.sh create      # create the droplet
./amd-provision.sh status      # droplet state and public IP
./amd-provision.sh ssh         # print the ssh command
```

Run `discover` first. It prints the exact size and image slugs your account
can use, which is the thing worth checking before spending credit — a wrong
slug fails at create time and can still bill a few minutes.

### Overrides

Every create parameter can be set from the environment:

```
DROPLET_NAME=cwe-vllm-atl1
REGION=atl1
SIZE=gpu-mi300x8-1536gb-devcloud
IMAGE=vllm-0-27-1-vllm-omni-0-27-0rc1-rocm-7-14
PARTITION_MODE=PARTITION_MODE_UNSET
TAGS=skripsi,cwe-eval
```

### Partition modes

From the API's own constants:

- `PARTITION_MODE_UNSET` — empty string, meaning full GPU allocation
- `PARTITION_MODE_SPX_NPS1` — one NPS partition
- `PARTITION_MODE_DPX_NPS2` — two NPS partitions

On a plan with more GPUs than the study needs, a partition mode can cut the
cost. Whether your plan supports one is visible in `discover` output.

## Tests

```
./test-helpers.sh
```

15 assertions covering the JSON extraction, the error classifier (a successful
droplet response must not be mistaken for an error), and the create payload's
field shapes. No network, no token, no side effects.

## Note on scope

This helper provisions infrastructure. It does not deploy vLLM, start the
model server, or run the experiment — those are separate steps, documented in
the repository's protocol and run plan.
