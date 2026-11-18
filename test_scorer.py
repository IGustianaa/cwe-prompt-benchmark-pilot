"""Tests for score_matrix.py against hand-built fixtures with known answers.

The point is that the metric implementation is checked against arithmetic we
can do by hand, not against a previous run of the same code.
"""
import json, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import score_matrix as sm

PASS = 0
FAIL = 0


def t(name, expected, actual, tol=None):
    global PASS, FAIL
    if tol is not None:
        ok = abs(expected - actual) <= tol
    else:
        ok = expected == actual
    if ok:
        print(f"ok   {name:<48} {actual}")
        PASS += 1
    else:
        print(f"FAIL {name:<48} expected=[{expected}] got=[{actual}]")
        FAIL += 1


def t_true(name, cond):
    t(name, True, bool(cond))


# ------------------------------------------------------- confusion & prf
m = {"YES": {"YES": 3, "NO": 1}, "NO": {"YES": 1, "NO": 5}}
p = sm.prf(m)
t("tp", 3, p["tp"]); t("fp", 1, p["fp"]); t("fn", 1, p["fn"]); t("tn", 5, p["tn"])
t("precision 3/4", 0.75, p["precision"], tol=1e-9)
t("recall 3/4", 0.75, p["recall"], tol=1e-9)
t("f1 0.75", 0.75, p["f1"], tol=1e-9)
t("accuracy 8/10", 0.8, p["accuracy"], tol=1e-9)
t("n", 10, p["n"])

m2 = {"YES": {"YES": 0, "NO": 2}, "NO": {"YES": 0, "NO": 8}}
p2 = sm.prf(m2)
t("no positives -> precision 0", 0.0, p2["precision"], tol=1e-9)
t("no positives -> recall 0", 0.0, p2["recall"], tol=1e-9)
t("no positives -> f1 0", 0.0, p2["f1"], tol=1e-9)
t("no positives -> accuracy 0.8", 0.8, p2["accuracy"], tol=1e-9)

# ------------------------------------------------------- confusion builder
c = sm.confusion([("YES", "vulnerable"), ("YES", "not_vulnerable"),
                  ("NO", "vulnerable"), ("NO", "not_vulnerable")])
t("confusion tp", 1, c["YES"]["YES"])
t("confusion fn", 1, c["YES"]["NO"])
t("confusion fp", 1, c["NO"]["YES"])
t("confusion tn", 1, c["NO"]["NO"])
c2 = sm.confusion([("YES", None), ("YES", "garbage")])
t("unparseable predictions are excluded", 0, c2["YES"]["YES"] + c2["YES"]["NO"])

# ------------------------------------------------------- per case grouping
def row(cid, cond, true_lab, pred, model="m1", seed=1000, parse="ok"):
    return {
        "sample_id": cid, "prompt_condition": cond, "true_label": true_lab,
        "predicted_label": pred, "model_name": model, "seed": seed,
        "parse_status": parse, "insufficient_context": False,
        "input_tokens": 100, "output_tokens": 50, "latency_ms": 10,
    }

# Two cases. P1 always right, P2 always wrong. F1(P1) = 1, F1(P2) = 0.
rows = []
for i in range(4):
    cid = f"c{i}"
    rows.append(row(cid, "P1", "YES", "vulnerable"))
    rows.append(row(cid, "P1", "NO", "not_vulnerable"))
    rows.append(row(cid, "P2", "YES", "not_vulnerable"))
    rows.append(row(cid, "P2", "NO", "vulnerable"))

cases = sm.per_case(rows)
t("4 cases grouped", 4, len(cases))
t_true("each case holds 4 rows", all(len(v) == 4 for v in cases.values()))
t("P1 F1 is 1.0", 1.0, sm.metric_for(cases, "P1")["f1"], tol=1e-9)
t("P2 F1 is 0.0", 0.0, sm.metric_for(cases, "P2")["f1"], tol=1e-9)

d = sm.bootstrap_diff(cases, "P1", "P2", 200, seed=3)
t("bootstrap mean diff is 1.0", 1.0, d["mean"], tol=1e-9)
t("bootstrap ci low is 1.0", 1.0, d["ci95_low"], tol=1e-9)
t("bootstrap ci high is 1.0", 1.0, d["ci95_high"], tol=1e-9)
t("bootstrap p(diff>0) is 1.0", 1.0, d["p_gt_zero"], tol=1e-9)

# Identical conditions -> zero difference, and the interval must contain 0.
d2 = sm.bootstrap_diff(cases, "P1", "P1", 200, seed=3)
t("same condition diff is 0", 0.0, d2["mean"], tol=1e-9)
t_true("same-condition ci contains 0", d2["ci95_low"] <= 0 <= d2["ci95_high"])

# ------------------------------------------------------- group scores
res = sm.group_scores(rows, "model_name")
t_true("grouped by model", "m1" in res)
e = res["m1"]
t("P1 n is 8", 8, e["P1"]["n"])
t("P2 n is 8", 8, e["P2"]["n"])
t("invalid rate is 0", 0.0, e["invalid_rate"], tol=1e-9)
t("abstention rate is 0", 0.0, e["abstention_rate"], tol=1e-9)
t("input token mean is 100", 100, e["tokens"]["input_mean"], tol=1e-9)
t("output token mean is 50", 50, e["tokens"]["output_mean"], tol=1e-9)
t_true("paired bootstrap present", "P1-P2" in e["paired_bootstrap"])

# Invalid rows must be counted.
rows2 = rows + [row("c0", "P1", "YES", None, parse="invalid")]
e2 = sm.group_scores(rows2, "model_name")
t_true("invalid rate counts bad rows", e2["m1"]["invalid_rate"] > 0)

# Two models must be scored separately.
rows3 = rows + [row(f"c{i}", "P1", "YES", "vulnerable", model="m2") for i in range(4)]
e3 = sm.group_scores(rows3, "model_name")
t_true("two models scored", "m2" in e3 and "m1" in e3)
t("m2 has its own rows", 4, e3["m2"]["n_rows"])

# ------------------------------------------------------- end to end CLI
with tempfile.TemporaryDirectory() as td:
    run = Path(td) / "run.jsonl"
    run.write_text("\n".join(json.dumps(r) for r in rows))
    import subprocess
    r = subprocess.run([sys.executable, str(HERE / "score_matrix.py"), str(run),
                        "--bootstrap", "100"],
                       capture_output=True, text=True, timeout=180)
    t("score CLI exits 0", 0, r.returncode)
    t_true("score CLI reports P1 F1", "F1=1.0000" in r.stdout)
    out = Path(td) / "scores.json"
    r2 = subprocess.run([sys.executable, str(HERE / "score_matrix.py"), str(run),
                         "--bootstrap", "100", "--out", str(out)],
                        capture_output=True, text=True, timeout=180)
    t("score CLI with --out exits 0", 0, r2.returncode)
    t_true("scores json written", out.exists())
    j = json.loads(out.read_text())
    t("scores json n_rows", len(rows), j["n_rows"])
    t_true("scores json has by model", "model_name" in j["by"])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
