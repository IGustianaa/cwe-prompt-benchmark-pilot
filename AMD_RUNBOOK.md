# Running the CWE prompt study on AMD Developer Cloud

End-to-end runbook for the MI300X node: provision, serve, run the matrix,
score it. Everything here is tested locally against a mock endpoint — no step
requires a GPU to verify.

## The hardware, and why it changes the plan

An 8-GPU MI300X node is 8 x 192 GB HBM3 (1536 GB total), gfx942, fully
interconnected. AMD's own documentation states that on an 8-GPU VM the quota
is consumed eight times faster: **one wall-clock hour on eight GPUs counts as
eight GPU-hours**.

Two consequences drive every decision below.

**Do not use tensor parallelism.** A 7B-32B model fits on a single 192 GB card
with room to spare. Sharding one model across eight GPUs adds collective
communication and buys nothing. The useful pattern on this node is *data
parallelism*: one independent vLLM server per GPU, each holding its own model,
each with its own port. Throughput scales close to linearly, and the study
gains something tensor parallelism would never give it — eight model families
measured under identical conditions instead of one.

**Power off is not free.** AMD's terms are explicit: when the GPU VM is
powered off, disk, CPU, RAM and the IP address stay reserved and **charges
continue until the instance is destroyed**. `destroy` is the only way to stop
the meter.

## Steps

### 1. Provision

```bash
mkdir -p ~/.secrets
printf '%s' 'YOUR_AMD_DEVCLOUD_TOKEN' > ~/.secrets/amd_devcloud_token
chmod 600 ~/.secrets/amd_devcloud_token

./amd-provision.sh discover    # read-only: what your account can actually use
./amd-provision.sh key         # upload this machine's SSH key
./amd-provision.sh create      # create the droplet
./amd-provision.sh status
./amd-provision.sh ssh         # prints: ssh root@<public-ip>
```

`discover` prints the exact region, GPU-plan and image slugs your account has
access to. A wrong slug fails at create time and can still bill a few minutes,
so read that output before creating anything.

### 2. Get the models onto the box

The node has 5 TB of scratch and 720 GB of boot disk. Model weights are not
included in the image, so pull them before starting the servers. Use a
Hugging Face token for the gated repos:

```bash
export HF_TOKEN=...            # needed for Llama and Gemma
pip install -U huggingface_hub

for repo in \
  Qwen/Qwen2.5-Coder-14B-Instruct \
  Qwen/Qwen2.5-Coder-32B-Instruct \
  meta-llama/Llama-3.1-8B-Instruct \
  deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct \
  Qwen/Qwen3-30B-A3B-Instruct \
  mistralai/Mistral-Small-3.1-24B-Instruct \
  google/gemma-3-27b-it
do
  name=$(basename "$repo" | tr 'A-Z' 'a-z')
  huggingface-cli download "$repo" --local-dir "/root/models/$name"
done
```

Check disk as you go — 70B-class weights are large. `df -h /root/models`.

### 3. Serve

```bash
./serve-parallel.sh list       # what will be started
./serve-parallel.sh start      # launches one vLLM per GPU
./serve-parallel.sh health
```

Each instance is pinned to one GPU with `HIP_VISIBLE_DEVICES` / `ROCR_VISIBLE_DEVICES`
and listens on its own port (8000-8007). The container on the AMD vLLM image
is named `rocm`; if it is not running, `docker start rocm`.

Model weights are read from `/root/models/<name>` by default. Override with
`MODEL_DIR=...`.

### 4. Run the matrix

```bash
./run-all.sh --cases 20 --seeds 1              # pilot, ~10 minutes
./run-all.sh --cases 1000 --seeds 5 --out runs/full.jsonl
```

The orchestrator discovers which instances are healthy, shards the selected
cases across them so no case is processed twice, and appends every row to one
JSONL file. It is safe to interrupt and rerun: the output is append-only and
already-written rows are not repeated.

Each row carries the full protocol output schema: `sample_id`, `cwe_id`,
`true_label`, `prompt_condition`, `prompt_version`, `model_name`, `seed`,
`raw_response`, `predicted_label`, `evidence`, `reason`,
`insufficient_context`, `parse_status`, token counts, `latency_ms`, and the
timestamp.

### 5. Score

```bash
python3 score_matrix.py runs/full.jsonl --out scores.json
```

Reports F1, precision, recall and the confusion matrix per model and
condition, plus the paired bootstrap interval on the P2-P1 difference.

The bootstrap resamples **cases**, not rows. Every row belonging to a case
moves together, because the design is paired: a case contributes one response
per condition and seed, and treating those as independent observations would
understate the interval.

### 6. Tear down

```bash
./serve-parallel.sh stop
```

Then **destroy the droplet** from the console, or:

```bash
curl -X DELETE -H "Authorization: Bearer $(cat ~/.secrets/amd_devcloud_token)" \
  https://api.devcloud.amd.com/v2/droplets/<droplet-id>
```

Powering off does not stop billing. Destroying does.

## CWE specifications

`run_matrix.py` reads the CWE name, operational criteria, indicators and
negating conditions from a JSON file (`--cwe-specs`), keyed by CWE id:

```json
{
  "120": {
    "name": "Buffer Copy without Checking Size of Input",
    "criteria": "A copy into a fixed-size buffer without validating the source length",
    "indicators": "strcpy, strcat, memcpy, sprintf with no preceding bounds check",
    "negations": "a length check before the copy, or a destination sized to the source"
  }
}
```

Without this file the criteria fields are empty, and the P2 condition degrades
into a longer P1. That would silently invalidate the comparison, so the
specifications must be filled in from the official CWE entries before the real
run — and the version of each CWE definition recorded, as the protocol
requires.

## Cost

The full matrix is small in compute terms. The dataset averages 779 tokens per
sample (1988 at p90), and the entire 1000-case x 3-condition x 2-model sweep
decodes in under two GPU-hours on one card. The time budget is dominated by
model downloads, warmup, debugging, and reruns — not by inference.

## Tests

```bash
./run-tests.sh
```

117 assertions across four suites, all local:

| Suite | Assertions | Covers |
|---|---|---|
| `test-helpers.sh` | 15 | JSON extraction, error classification, create payload shape |
| `test_matrix.py` | 45 | prompt extraction from the protocol, response parsing, case selection, end-to-end run |
| `test_orchestrator.py` | 12 | multi-worker sharding, no duplicate cases, dry run writes nothing |
| `test_scorer.py` | 45 | confusion matrix, F1 against hand-computed values, paired bootstrap |

No GPU, no token, no network beyond `127.0.0.1`. `mock_vllm.py` stands in for
a vLLM server.

## Files

| File | Purpose |
|---|---|
| `amd-provision.sh` | create and inspect the droplet |
| `serve-parallel.sh` | one vLLM instance per GPU |
| `run_matrix.py` | build prompts, call the endpoints, write JSONL |
| `run-all.sh` | shard the matrix across healthy instances |
| `score_matrix.py` | F1, confusion matrix, paired bootstrap |
| `mock_vllm.py` | local stand-in for a vLLM server |
| `run-tests.sh` | every test suite |
