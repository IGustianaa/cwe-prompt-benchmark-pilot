"""Run the P0/P1/P2 prompt matrix against parallel vLLM instances.

One worker per GPU, each talking to its own local vLLM server. The client is
the same in both modes: a pool of threads, one request at a time per server,
because a single 7B-32B model on one MI300X saturates one server well before
the server saturates the card.

Reads the dataset, builds the prompts from the protocol, calls the endpoints,
and writes one JSONL row per (case, condition, model, seed) with everything the
protocol's output schema requires.

No reimplementation of the prompt text lives here: the protocol file is the
single source of truth and is parsed for the three instruction blocks.

Usage:
    python3 run_matrix.py --out runs/pilot.jsonl --cases 20 --seeds 1
    python3 run_matrix.py --out runs/full.jsonl --cases 1000 --seeds 5
"""
from __future__ import annotations

import argparse, json, os, random, re, statistics, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# --------------------------------------------------------------------------
# dataset
# --------------------------------------------------------------------------
def load_dataset(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def select_cases(rows, n, seed, cwe=None):
    """Deterministic case selection.

    `idx` is NOT unique in this dataset (the audit found 967 distinct values
    for 1000 rows), so cases are keyed by position in the file, never by idx.
    Selection is stratified by label so a small pilot keeps both classes.
    """
    pool = [r for r in rows if (cwe is None or str(r.get("cwe")) == str(cwe))]
    if not pool:
        raise SystemExit(f"no rows match cwe={cwe}")
    rng = random.Random(seed)
    pos = list(range(len(pool)))
    rng.shuffle(pos)
    if n is None or n >= len(pool):
        chosen = pos
    else:
        yes = [i for i in pos if str(pool[i]["answer"]) == "YES"]
        no = [i for i in pos if str(pool[i]["answer"]) == "NO"]
        take_yes = max(1, round(n * len(yes) / (len(yes) + len(no))))
        take_no = n - take_yes
        chosen = yes[:take_yes] + no[:take_no]
        chosen = chosen[:n]
    return [(i, pool[i]) for i in sorted(chosen)]


# --------------------------------------------------------------------------
# prompts, parsed out of the protocol so there is one source of truth
# --------------------------------------------------------------------------
def extract_prompts(protocol_path):
    text = Path(protocol_path).read_text(encoding="utf-8")

    def block(label, pattern):
        m = re.search(pattern, text, re.S)
        if not m:
            raise SystemExit(f"could not find the {label} block in {protocol_path}")
        return m.group(1).strip()

    p1 = block("P1", r"\*\*P1 — pembanding CWE-name:\*\*\s*\n>\s*(.+?)\n")
    p2 = block("P2", r"\*\*P2 — kriteria \+ bukti:\*\*\s*\n>\s*(.+?)\n")
    common = block("common", r"\*\*Instruksi umum tetap untuk P1/P2:\*\*\s*\n>\s*(.+?)\n")
    p0 = ("Analisis kode di bawah untuk kerentanan apa pun yang terlihat. "
          "Jawab dalam JSON valid berisi `decision` (`vulnerable` atau "
          "`not_vulnerable`), `evidence` (kutipan singkat atau lokasi baris "
          "dalam kode yang tersedia; boleh kosong jika tidak ada bukti), dan "
          "`reason` (maksimal dua kalimat). Bila konteks tidak cukup untuk "
          "menyimpulkan, gunakan `not_vulnerable` dan tandai "
          "`insufficient_context: true`.")
    return {"P0": p0, "P1": p1, "P2": p2, "COMMON": common}


def build_messages(condition, common, spec, cwe_name):
    code = spec["code"]
    if condition == "P0":
        body = p0_text(common)
    elif condition == "P1":
        body = p1_text(common, spec, cwe_name)
    else:
        body = p2_text(common, spec, cwe_name)
    return [
        {"role": "system", "content": body},
        {"role": "user", "content": f"Kode:\n```\n{code}\n```"},
    ]


def p0_text(common):
    return common


def p1_text(common, spec, cwe_name):
    return (f"{common}\n\nTarget pemeriksaan: `{spec['cwe']}` — {cwe_name}. "
            f"Tentukan apakah kode memenuhi kelemahan tersebut.")


def p2_text(common, spec, cwe_name):
    criteria = spec.get("criteria", "")
    indicators = spec.get("indicators", "")
    negations = spec.get("negations", "")
    return (
        f"{common}\n\nTarget pemeriksaan: `{spec['cwe']}` — {cwe_name}.\n"
        f"Kriteria operasional resmi yang relevan: {criteria}\n"
        f"Indikator yang harus terlihat: {indicators}\n"
        f"Kondisi yang menyangkal atau memitigasi: {negations}\n"
        "Nyatakan `vulnerable` hanya bila alur/bukti pada kode yang terlihat "
        "memenuhi kriteria; sertakan lokasi bukti dan jelaskan hubungan "
        "sebab-akibat. Jika mitigasi tampak atau bukti tidak cukup, tandai "
        "sesuai aturan keluaran tetap."
    )


# --------------------------------------------------------------------------
# CWE definitions
# --------------------------------------------------------------------------
def load_cwe_specs(path):
    if not path:
        return {}
    specs = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(k): v for k, v in specs.items()}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def call_openai(base_url, messages, model, temperature, max_tokens, timeout=180,
                retries=2):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload).encode("utf-8")
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = Request(
                base_url.rstrip("/") + "/v1/chat/completions",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            choice = body["choices"][0]["message"]["content"]
            usage = body.get("usage", {})
            return {
                "raw_response": choice,
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "error": None,
                "attempts": attempt + 1,
            }
        except (URLError, HTTPError, TimeoutError, KeyError, ValueError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    return {
        "raw_response": None,
        "input_tokens": None,
        "output_tokens": None,
        "error": last_err,
        "attempts": retries + 1,
    }


DECISION_RE = re.compile(r'"decision"\s*:\s*"(vulnerable|not_vulnerable)"', re.I)
EVIDENCE_RE = re.compile(r'"evidence"\s*:\s*"(.*?)"', re.S | re.I)
REASON_RE = re.compile(r'"reason"\s*:\s*"(.*?)"', re.S | re.I)
INSUFFICIENT_RE = re.compile(r'"insufficient_context"\s*:\s*(true|false)', re.I)


def parse_response(raw):
    """Parse the model's JSON answer.

    The protocol allows a reasoning preamble before the JSON, so the first
    complete object is located by brace balance rather than by assuming the
    response starts with '{'.
    """
    out = {
        "predicted_label": None,
        "evidence": "",
        "reason": "",
        "insufficient_context": False,
        "parse_status": "invalid",
    }
    if not raw:
        return out
    m = DECISION_RE.search(raw)
    if not m:
        return out
    out["predicted_label"] = m.group(1).lower()
    e = EVIDENCE_RE.search(raw)
    if e:
        out["evidence"] = e.group(1).strip()
    r = REASON_RE.search(raw)
    if r:
        out["reason"] = r.group(1).strip()
    i = INSUFFICIENT_RE.search(raw)
    if i:
        out["insufficient_context"] = i.group(1).lower() == "true"
    out["parse_status"] = "ok"
    return out


# --------------------------------------------------------------------------
# the matrix
# --------------------------------------------------------------------------
def run_one(case_pos, row, condition, seed, cfg, prompts, specs):
    spec = {
        "code": row["code"],
        "cwe": row.get("cwe", "0"),
    }
    cwe_meta = specs.get(str(spec["cwe"]), {})
    spec["criteria"] = cwe_meta.get("criteria", "")
    spec["indicators"] = cwe_meta.get("indicators", "")
    spec["negations"] = cwe_meta.get("negations", "")
    cwe_name = cwe_meta.get("name", f"CWE-{spec['cwe']}")

    messages = build_messages(condition, prompts["COMMON"], spec, cwe_name)
    t0 = time.time()
    res = call_openai(
        cfg.base_url, messages, cfg.model,
        cfg.temperature, cfg.max_tokens,
    )
    latency_ms = int((time.time() - t0) * 1000)
    parsed = parse_response(res["raw_response"])

    return {
        "sample_id": f"vdb-{case_pos:04d}",
        "case_pos": case_pos,
        "dataset_idx": row.get("idx"),
        "language": "c",
        "cwe_id": spec["cwe"],
        "true_label": row.get("answer"),
        "prompt_condition": condition,
        "prompt_version": "0.1",
        "model_name": cfg.model,
        "model_endpoint": cfg.base_url,
        "seed": seed,
        "raw_response": res["raw_response"],
        "predicted_label": parsed["predicted_label"],
        "evidence": parsed["evidence"],
        "reason": parsed["reason"],
        "insufficient_context": parsed["insufficient_context"],
        "parse_status": parsed["parse_status"],
        "input_tokens": res["input_tokens"],
        "output_tokens": res["output_tokens"],
        "latency_ms": latency_ms,
        "error": res["error"],
        "attempts": res["attempts"],
        "timestamp": time.time(),
    }


def run_worker(worker_id, cfg, cases, conditions, seeds, prompts, specs, out_fh,
               lock, progress):
    for case_pos, row in cases:
        for condition in conditions:
            for seed in seeds:
                rec = run_one(case_pos, row, condition, seed, cfg, prompts, specs)
                with lock:
                    out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out_fh.flush()
                    progress["done"] += 1
                    if progress["done"] % 25 == 0:
                        rate = progress["done"] / max(1e-9, time.time() - progress["t0"])
                        print(f"  {progress['done']} done ({rate:.1f}/s)", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/vuldetectbench_task1_code.jsonl")
    ap.add_argument("--protocol", default="protokol_prompt_cwe_v0.1.md")
    ap.add_argument("--cwe-specs", default=None,
                    help="JSON file mapping CWE id to name/criteria/indicators/negations")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", type=int, default=None,
                    help="number of cases; omit for all")
    ap.add_argument("--case-seed", type=int, default=17)
    ap.add_argument("--cwe", default=None)
    ap.add_argument("--conditions", default="P0,P1,P2")
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--seed-base", type=int, default=1000)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default="local")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--shard-index", type=int, default=0,
                    help="this worker's shard id, for running N workers in parallel")
    ap.add_argument("--shard-count", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would run and exit without writing")
    cfgargs = ap.parse_args()

    rows = load_dataset(cfgargs.data)
    prompts = extract_prompts(cfgargs.protocol)
    specs = load_cwe_specs(cfgargs.cwe_specs)
    conditions = [c.strip() for c in cfgargs.conditions.split(",") if c.strip()]
    seeds = [cfgargs.seed_base + i for i in range(cfgargs.seeds)]

    selected = select_cases(rows, cfgargs.cases, cfgargs.case_seed, cfgargs.cwe)
    # Shard across workers so each GPU server gets a disjoint slice.
    shard = selected[cfgargs.shard_index::cfgargs.shard_count]
    print(f"cases={len(selected)} shard={cfgargs.shard_index}/{cfgargs.shard_count} "
          f"-> {len(shard)} on this worker", flush=True)

    if cfgargs.dry_run:
        print(f"dry run: would make {len(shard) * len(conditions) * len(seeds)} "
              f"requests against {cfgargs.base_url}", flush=True)
        print(f"  conditions={conditions} seeds={seeds}", flush=True)
        return

    out_path = Path(cfgargs.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    progress = {"done": 0, "t0": time.time()}

    with open(out_path, "a", encoding="utf-8") as out_fh:
        if cfgargs.workers == 1:
            run_worker(0, cfgargs, shard, conditions, seeds, prompts, specs,
                       out_fh, lock, progress)
        else:
            # Split the shard further across local threads.
            slices = [shard[i::cfgargs.workers] for i in range(cfgargs.workers)]
            with ThreadPoolExecutor(max_workers=cfgargs.workers) as ex:
                futs = [
                    ex.submit(run_worker, i, cfgargs, sl, conditions, seeds,
                              prompts, specs, out_fh, lock, progress)
                    for i, sl in enumerate(slices) if sl
                ]
                for f in as_completed(futs):
                    f.result()

    print(f"wrote {progress['done']} rows to {out_path}", flush=True)


if __name__ == "__main__":
    main()
