"""End-to-end test of run-all.sh against two mock vLLM servers.

Simulates the multi-worker setup: two instances on two ports, one orchestrator,
disjoint shards, one output file, and a check that no case is processed twice.
"""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PASS = 0
FAIL = 0


def t(name, expected, actual):
    global PASS, FAIL
    if expected == actual:
        print(f"ok   {name:<48} {actual}")
        PASS += 1
    else:
        print(f"FAIL {name:<48} expected=[{expected}] got=[{actual}]")
        FAIL += 1


def t_true(name, cond):
    t(name, True, bool(cond))


ports = [8766, 8767]
procs = []
for p in ports:
    procs.append(subprocess.Popen(
        [sys.executable, str(HERE / "mock_vllm.py"), str(p)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
time.sleep(1.5)

try:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "matrix.jsonl"
        env = dict(os.environ)
        env["PORT_BASE"] = str(ports[0])
        env["N_WORKERS"] = "2"
        env["DATA"] = str(HERE / "data" / "vuldetectbench_task1_code.jsonl")
        env["PROTOCOL"] = str(HERE / "protokol_prompt_cwe_v0.1.md")

        # 6 cases x 3 conditions x 2 seeds = 36 requests, split over 2 workers
        r = subprocess.run(
            ["bash", str(HERE / "run-all.sh"), "--cases", "6", "--seeds", "2",
             "--out", str(out)],
            capture_output=True, text=True, timeout=300, env=env, cwd=str(HERE),
        )
        t("run-all exits 0", 0, r.returncode)
        if r.returncode != 0:
            print(r.stdout[-2000:])
            print(r.stderr[-2000:])

        t_true("output file exists", out.exists())
        recs = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        t("6 cases x 3 conditions x 2 seeds = 36 rows", 36, len(recs))

        keys = [(x["sample_id"], x["prompt_condition"], x["seed"]) for x in recs]
        t("no duplicate case+condition+seed", len(keys), len(set(keys)))
        t("both shards contributed",
          len({x["model_endpoint"] for x in recs}), 2)
        t_true("all rows parsed", all(x["parse_status"] == "ok" for x in recs))
        t_true("all rows have true_label",
               all(x["true_label"] in ("YES", "NO") for x in recs))
        t_true("all rows have tokens",
               all(x["input_tokens"] and x["output_tokens"] for x in recs))
        # every case must appear in every condition and seed
        by_case = {}
        for x in recs:
            by_case.setdefault(x["sample_id"], set()).add(
                (x["prompt_condition"], x["seed"]))
        t_true("every case has all 3 conditions x 2 seeds",
               all(len(v) == 6 for v in by_case.values()))
        t("6 distinct cases", 6, len(by_case))

        # --- dry run must not write ---
        out2 = Path(td) / "dry.jsonl"
        r2 = subprocess.run(
            ["bash", str(HERE / "run-all.sh"), "--cases", "3", "--seeds", "1",
             "--out", str(out2), "--dry-run"],
            capture_output=True, text=True, timeout=120, env=env, cwd=str(HERE),
        )
        t("dry run exits 0", 0, r2.returncode)
        t_true("dry run wrote nothing", not out2.exists() or out2.stat().st_size == 0)
finally:
    for p in procs:
        p.terminate()
    for p in procs:
        p.wait(timeout=10)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
