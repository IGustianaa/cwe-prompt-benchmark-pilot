"""Tests for run_matrix.py: prompt building, parsing, selection, and the
end-to-end matrix against the local mock endpoint.

No network beyond 127.0.0.1, no GPU, no token.
"""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_matrix as rm

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


# ---------------------------------------------------------------- prompts
protocol = HERE / "protokol_prompt_cwe_v0.1.md"
t_true("protocol file exists", protocol.exists())
prompts = rm.extract_prompts(protocol)
for key in ("P0", "P1", "P2", "COMMON"):
    t_true(f"prompt {key} extracted", len(prompts.get(key, "")) > 20)
t_true("P1 mentions CWE target", "Target pemeriksaan" in prompts["P1"])
t_true("P2 mentions criteria", "kriteria" in prompts["P2"].lower())
t_true("P2 mentions evidence", "bukti" in prompts["P2"].lower())
t_true("COMMON asks for JSON", "JSON" in prompts["COMMON"])

spec = {
    "code": "void f(char *d){ strcpy(d, src); }",
    "cwe": "120",
    "criteria": "unchecked copy into a fixed buffer",
    "indicators": "strcpy/memcpy without a length check",
    "negations": "a bounds check, or a non-fixed destination",
}
m1 = rm.build_messages("P1", prompts["COMMON"], spec, "CWE-120")
m2 = rm.build_messages("P2", prompts["COMMON"], spec, "CWE-120")
m0 = rm.build_messages("P0", prompts["COMMON"], spec, "CWE-120")
t("P1 has system+user", 2, len(m1))
t("P2 carries the criteria text", True, "unchecked copy" in m2[0]["content"])
t("P2 carries the indicators", True, "strcpy/memcpy" in m2[0]["content"])
t("P2 carries the negations", True, "bounds check" in m2[0]["content"])
t("P1 does not carry the criteria", False, "unchecked copy" in m1[0]["content"])
t("P0 does not name a CWE", False, "CWE-120" in m0[0]["content"])
t("all conditions carry the same code", True,
  spec["code"] in m1[1]["content"] and spec["code"] in m2[1]["content"]
  and spec["code"] in m0[1]["content"])

# ---------------------------------------------------------------- parsing
ok_raw = ('Sure. ```json\n{"decision":"vulnerable","evidence":"line 3",'
          '"reason":"bad copy","insufficient_context":false}\n```')
p = rm.parse_response(ok_raw)
t("parse: label", "vulnerable", p["predicted_label"])
t("parse: evidence", "line 3", p["evidence"])
t("parse: reason", "bad copy", p["reason"])
t("parse: status", "ok", p["parse_status"])
t("parse: insufficient false", False, p["insufficient_context"])

p2 = rm.parse_response('{"decision":"not_vulnerable","evidence":"","reason":"clean"}')
t("parse: negative label", "not_vulnerable", p2["predicted_label"])
t("parse: empty evidence", "", p2["evidence"])

p3 = rm.parse_response("no json here at all")
t("parse: invalid status", "invalid", p3["parse_status"])
t("parse: invalid label", None, p3["predicted_label"])

p4 = rm.parse_response('{"decision":"vulnerable","insufficient_context":true}')
t("parse: insufficient true", True, p4["insufficient_context"])

p5 = rm.parse_response(None)
t("parse: None input", "invalid", p5["parse_status"])

# ---------------------------------------------------------------- selection
data = HERE / "data" / "vuldetectbench_task1_code.jsonl"
rows = rm.load_dataset(data)
t("dataset loads 1000 rows", 1000, len(rows))
sel = rm.select_cases(rows, 20, 17, None)
t("select 20 cases", 20, len(sel))
labels = [r["answer"] for _, r in sel]
t("selection keeps both labels", True, "YES" in labels and "NO" in labels)
t("selection is deterministic", True,
  [i for i, _ in sel] == [i for i, _ in rm.select_cases(rows, 20, 17, None)])
t("selection differs by seed", True,
  [i for i, _ in sel] != [i for i, _ in rm.select_cases(rows, 20, 18, None)])
uniq_idx = len({r.get("idx") for r in rows})
t("idx really is non-unique in this dataset", True, uniq_idx < len(rows))
sh = rm.select_cases(rows, 20, 17, None)[0::2]
sh2 = rm.select_cases(rows, 20, 17, None)[1::2]
t("sharding is disjoint", 0, len(set(i for i, _ in sh) & set(i for i, _ in sh2)))

# ---------------------------------------------------------------- end to end
port = 8765
proc = subprocess.Popen([sys.executable, str(HERE / "mock_vllm.py"), str(port)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)
try:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "run.jsonl"
        cmd = [sys.executable, str(HERE / "run_matrix.py"),
               "--data", str(data), "--protocol", str(protocol),
               "--out", str(out), "--cases", "5", "--seeds", "2",
               "--conditions", "P0,P1,P2",
               "--base-url", f"http://127.0.0.1:{port}", "--model", "mock"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        t("matrix run exits 0", 0, r.returncode)
        if r.returncode != 0:
            print(r.stdout[-1500:])
            print(r.stderr[-1500:])
        recs = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        t("5 cases x 3 conditions x 2 seeds = 30 rows", 30, len(recs))
        t_true("all rows parsed", all(x["parse_status"] == "ok" for x in recs))
        t_true("all rows have a predicted label",
               all(x["predicted_label"] in ("vulnerable", "not_vulnerable") for x in recs))
        t_true("all rows carry token usage",
               all(x["input_tokens"] and x["output_tokens"] for x in recs))
        t_true("all rows carry latency", all(x["latency_ms"] >= 0 for x in recs))
        t_true("seeds recorded", sorted({x["seed"] for x in recs}) == [1000, 1001])
        t_true("conditions recorded",
               sorted({x["prompt_condition"] for x in recs}) == ["P0", "P1", "P2"])
        t_true("sample_ids unique per case",
               len({(x["sample_id"], x["prompt_condition"], x["seed"]) for x in recs}) == 30)
        t_true("true_label preserved", all(x["true_label"] in ("YES", "NO") for x in recs))
        # the mock marks a sample vulnerable when the code contains strcpy
        for x in recs:
            if "strcpy" in str(rm.load_dataset(data)[x["case_pos"]]["code"]):
                t_true("mock label reaches the record",
                       x["predicted_label"] == "vulnerable")
                break
finally:
    proc.terminate()
    proc.wait(timeout=10)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
