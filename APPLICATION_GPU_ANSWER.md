The study measures whether CWE operational criteria in a prompt (the indicators
that must be visible, the conditions that negate a finding, and a mandatory
evidence citation) improve LLM vulnerability detection compared with naming the
CWE alone. Conditions P1 and P2 see identical code models and decoding settings;
only the instruction block differs.

What already exists. The dataset is downloaded, hashed, and audited. The prompt
protocol is frozen at v0.1 before any run. The cost scenario is computed. All of
it is in a public, MIT-licensed repository and reproduces with the standard
library in one command. No inference has been run yet, so this grant is what
starts the measurement phase rather than extending one.

Sizing is measured, not guessed. From the audit, the dataset runs 779 tokens per
sample on average, 1988 at p90, and 10993 at the maximum. At batched vLLM
throughput on a 24 GB card (7-8B parameters at 4-bit), the whole matrix of 1000
cases x 3 conditions x 2 models is under 2 GPU-hours of pure decoding. The
approximately 30 GPU-hours requested is therefore dominated by engineering
rather than by compute:

- model reload and warmup while prompts and the parser are iterated: about 3 h
- invalid-JSON retries and long-context tails: counted inside the above
- 5-seed reruns for confidence intervals on a paired design: about 9 h
- held-out CWE and length-stratified robustness pass: about 8 h
- headroom for one unplanned replication: about 7 h

Hardware fit. One 24 GB card covers Qwen2.5-Coder-7B-Instruct and
Llama-3.1-8B-Instruct at 4-bit. One 40-80 GB card covers
DeepSeek-Coder-V2-Lite (about 2.4B active parameters) at bf16 with no sharding.
There is no training and no fine-tuning. The only weights placed on disk are the
served checkpoints, and no derivative is redistributed.

Why a grant matters when the number is small. The binding constraint is not
FLOPs. It is that a pinned model revision cannot be guaranteed on a free tier,
and a handful of paid API calls cannot produce confidence intervals on a paired
design. Granted compute buys reproducibility, not scale.

Note on the bundled data. The repository ships VulDetectBench task1/test so the
audit can be re-run and checked by a reviewer. That output is a NO-GO for the
original per-CWE framing, and it is published rather than revised after the
fact. The test split is not used to develop prompts.

Links
- Public artifact (MIT): https://github.com/IGustianaa/cwe-prompt-benchmark-pilot
- Dataset audit output: https://github.com/IGustianaa/cwe-prompt-benchmark-pilot/blob/main/dataset_audit.json
- Prompt protocol v0.1: https://github.com/IGustianaa/cwe-prompt-benchmark-pilot/blob/main/protokol_prompt_cwe_v0.1.md
- Run plan and cost scenario: https://github.com/IGustianaa/cwe-prompt-benchmark-pilot/blob/main/RENCANA_PILOT_DAN_BIAYA.md
- License: https://github.com/IGustianaa/cwe-prompt-benchmark-pilot/blob/main/LICENSE
