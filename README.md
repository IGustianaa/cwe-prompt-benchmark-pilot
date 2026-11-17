# CWE-Criteria Prompt Study — Public Pilot Artifact

Public working artifact for an undergraduate thesis in Informatika
(Universitas Siliwangi). **This repository is the computational-artifact and
pilot-plan half of the work. The thesis manuscript itself is not here.**

## What the study asks

LLM-based vulnerability detectors are usually prompted with a target weakness
named ("find CWE-787 issues"). Does that name alone carry the work, or does the
model need the *operational criteria* — which indicators must be visible, which
conditions negate the finding, and a requirement to cite evidence from the
code?

Three conditions, identical code and identical model configuration:

| # | Condition | Prompt carries |
|---|---|---|
| P1 | CWE-name | target CWE id + official name only |
| P2 | criteria + evidence | same, plus operational criteria, negating conditions, and an evidence-citation requirement |
| P0 | generic (optional) | a broad "find vulnerabilities" instruction, no target CWE |

P0 is reported separately and is **not** the primary comparator — the task it
poses is a different one.

## Why this artifact exists

Two things in this space are routinely glossed over:

1. **Prevalence balance is not class balance.** VulDetectBench task 1 is 500
   `YES` / 500 `NO` overall, which reads as a balanced benchmark. Per CWE it is
   not: only CWE-120 appears under both labels, and only once as `YES`. A
   per-CWE positive/negative comparison therefore cannot be assembled from this
   task *as it stands*. That is measured here, not assumed.
2. **A benchmark's `test` split must not be used to choose prompts.** The audit
   records the split name explicitly because the mitigation — build prompts on
   a separate development split — depends on knowing which split was looked at.

## Measured, on the public data

`audit_dataset.py` is metadata-only: it never sends a sample to a model, makes
no network calls, and uses only the standard library.

- 1000 rows, labels balanced: `YES` 500 / `NO` 500
- 500 samples carry CWE `0` in the `NO` class — the field is not populated for
  clean code the way it is for vulnerable code
- 57 distinct `cwe` values across the file
- **Only CWE-120 carries both labels**: 42 `NO`, 1 `YES`
- 1000 distinct code bodies, but only 967 distinct `idx` — 33 `idx` values are
  reused across different samples, so `idx` is **not** a valid row key
- SHA-256 of the dataset file is recorded in `dataset_audit.json`

Consequence, stated plainly: this task supports *recall over one CWE family*,
not a per-CWE precision/recall comparison. The plan below records that as a
**NO-GO** for the original per-CWE framing rather than quietly re-labelling the
metric after seeing results.

## Pilot plan status

`protokol_prompt_cwe_v0.1.md` fixes the research questions, the conditions, the
output schema, the metrics, and the GO/NO-GO gates **before** any run. `RENCANA_PILOT_DAN_BIAYA.md` is the execution plan and cost scenario.

What is done: dataset downloaded, hashed, audited; protocol written; cost
scenario computed.
What is **not** done: no LLM inference has been run; no accuracy, F1, precision or
recall number exists anywhere in this repository; no CWE has been selected as
final.

Any number in these files that looks like a result is a *scenario* built from
published list prices, labelled as such. Do not read them as measurements.

## Compute need

The pilot is API-inference-bound, not training-bound: no model weights are
downloaded or fine-tuned, and the dataset is ~3 MB. What is being measured is
prompt-construction quality and evaluation-harness reliability at small scale,
which makes a low-end GPU instance appropriate — enough to run the orchestration Docker
stack, a local vLLM endpoint for a small open model as a cross-check against the
hosted API, and a local parser/validator without serialising the 400-call
batch. Cost scenario in `RENCANA_PILOT_DAN_BIAYA.md` §D.

## Reproduce

```
python3 audit_dataset.py                      # writes dataset_audit.json
python3 audit_dataset.py out.json             # or elsewhere
python3 cost_estimator.py --cases 200         # scenario, not a bill
```

Standard library only, Python 3.11+. Both scripts run from any working
directory.

## Data

`data/vuldetectbench_task1_code.jsonl` is VulDetectBench `task1/test`, from
https://github.com/Sweetaroo/VulDetectBench , distributed under that
repository's licence (MIT, Copyright (c) 2024 Lang Gao). Upstream terms govern;
check them before redistributing. The `test` split is included so the audit
above can be re-run and checked — it is **not** the split prompts are to be
developed against.

## License

MIT, see `LICENSE`. Original code, protocol and audit files here:
Copyright (c) 2026 IGustianaa. The bundled VulDetectBench data remains
Copyright (c) 2024 Lang Gao under the same MIT terms.

## Manuscript

Thesis text is not published here. The study's framing, related work, and
results are in the undergraduate thesis, to be deposited with Universitas
Siliwangi after defence.
