"""Score a matrix run: F1, precision, recall, confusion matrix, bootstrap CIs.

Reads the JSONL written by run_matrix.py and produces the primary metric
(F1 on the `vulnerable` class and the P2-P1 difference on the same cases), the
secondary metrics (invalid-output rate, abstention rate, token cost, latency),
and the paired bootstrap interval.

The bootstrap resamples **cases**, not rows: every row belonging to a case
moves together, because the design is paired and a case contributes several
rows (one per condition and seed). Resampling rows would treat a case's
responses as independent observations and would understate the interval.

Usage:
    python3 score_matrix.py runs/matrix.jsonl
    python3 score_matrix.py runs/matrix.jsonl --bootstrap 2000 --out scores.json
"""
from __future__ import annotations

import argparse, json, math, random, statistics, sys
from collections import defaultdict
from pathlib import Path


def load(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def confusion(pairs):
    """pairs: iterable of (true_label, predicted_label). Returns a 2x2 matrix."""
    m = {"YES": {"YES": 0, "NO": 0}, "NO": {"YES": 0, "NO": 0}}
    for t, p in pairs:
        if t not in m or p not in ("vulnerable", "not_vulnerable"):
            continue
        pv = "YES" if p == "vulnerable" else "NO"
        m[t][pv] += 1
    return m


def prf(m):
    tp = m["YES"]["YES"]
    fp = m["NO"]["YES"]
    fn = m["YES"]["NO"]
    tn = m["NO"]["NO"]
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    acc = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) else 0.0
    return {
        "precision": prec, "recall": rec, "f1": f1, "accuracy": acc,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "n": tp + tn + fp + fn,
    }


def per_case(rows):
    """Group rows by case, keeping every condition and seed together."""
    by_case = defaultdict(list)
    for r in rows:
        by_case[r["sample_id"]].append(r)
    return by_case


def metric_for(cases, condition, model=None):
    """F1 for one condition (optionally restricted to one model)."""
    pairs = []
    for cid, rs in cases.items():
        for r in rs:
            if r["prompt_condition"] != condition:
                continue
            if model and r.get("model_name") != model:
                continue
            if not r.get("predicted_label"):
                continue
            pairs.append((r["true_label"], r["predicted_label"]))
    return prf(confusion(pairs))


def bootstrap_diff(cases, cond_a, cond_b, iters, seed=7):
    """Paired bootstrap of F1(cond_a) - F1(cond_b) over cases.

    A case contributes to both conditions inside the same resample, which is
    what makes the interval a paired one.
    """
    ids = sorted(cases.keys())
    if not ids:
        return None
    rng = random.Random(seed)
    diffs = []
    for _ in range(iters):
        sample = [ids[rng.randrange(len(ids))] for _ in range(len(ids))]
        sub = {cid: cases[cid] for cid in sample}
        a = metric_for(sub, cond_a)
        b = metric_for(sub, cond_b)
        diffs.append(a["f1"] - b["f1"])
    diffs.sort()
    lo = diffs[max(0, int(0.025 * len(diffs)) - 1)]
    hi = diffs[min(len(diffs) - 1, int(0.975 * len(diffs)))]
    return {
        "mean": statistics.fmean(diffs),
        "ci95_low": lo, "ci95_high": hi,
        "iters": iters,
        "p_gt_zero": sum(1 for d in diffs if d > 0) / len(diffs),
    }


def group_scores(rows, by):
    out = {}
    groups = defaultdict(list)
    for r in rows:
        groups[r.get(by)].append(r)
    for key, rs in groups.items():
        if key is None:
            continue
        cases = per_case(rs)
        entry = {"n_rows": len(rs)}
        for cond in sorted({r["prompt_condition"] for r in rs}):
            entry[cond] = metric_for(cases, cond)
        # paired diffs, when both conditions are present
        conds = sorted({r["prompt_condition"] for r in rs})
        diffs = {}
        for i in range(len(conds)):
            for j in range(i + 1, len(conds)):
                d = bootstrap_diff(cases, conds[i], conds[j], 1000)
                if d:
                    diffs[f"{conds[i]}-{conds[j]}"] = d
        entry["paired_bootstrap"] = diffs
        entry["invalid_rate"] = sum(1 for r in rs if r.get("parse_status") != "ok") / len(rs)
        entry["abstention_rate"] = sum(1 for r in rs if r.get("insufficient_context")) / len(rs)
        tok_in = [r["input_tokens"] for r in rs if r.get("input_tokens")]
        tok_out = [r["output_tokens"] for r in rs if r.get("output_tokens")]
        lat = [r["latency_ms"] for r in rs if r.get("latency_ms") is not None]
        entry["tokens"] = {
            "input_mean": statistics.fmean(tok_in) if tok_in else None,
            "output_mean": statistics.fmean(tok_out) if tok_out else None,
            "input_total": sum(tok_in), "output_total": sum(tok_out),
        }
        entry["latency_ms"] = {
            "mean": statistics.fmean(lat) if lat else None,
            "p50": statistics.median(lat) if lat else None,
            "p95": sorted(lat)[int(0.95 * (len(lat) - 1))] if lat else None,
        }
        out[str(key)] = entry
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", help="JSONL produced by run_matrix.py")
    ap.add_argument("--by", default="model_name",
                    help="group results by this field: model_name, prompt_condition, seed")
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rows = load(args.run)
    if not rows:
        print("no rows", file=sys.stderr)
        sys.exit(1)

    print(f"rows: {len(rows)}")
    print(f"cases: {len({r['sample_id'] for r in rows})}")
    print(f"conditions: {sorted({r['prompt_condition'] for r in rows})}")
    print(f"models: {sorted({r.get('model_name') for r in rows})}")
    print()

    result = {
        "run_file": args.run,
        "n_rows": len(rows),
        "n_cases": len({r["sample_id"] for r in rows}),
        "conditions": sorted({r["prompt_condition"] for r in rows}),
        "models": sorted({str(r.get("model_name")) for r in rows}),
        "by": {},
    }

    for by in ("model_name", "prompt_condition"):
        result["by"][by] = group_scores(rows, by)

    for model, entry in result["by"]["model_name"].items():
        print(f"== {model}  ({entry['n_rows']} rows)")
        for cond in ("P0", "P1", "P2"):
            if cond not in entry:
                continue
            m = entry[cond]
            print(f"  {cond}: F1={m['f1']:.4f} P={m['precision']:.4f} "
                  f"R={m['recall']:.4f} Acc={m['accuracy']:.4f} n={m['n']} "
                  f"(tp={m['tp']} fp={m['fp']} fn={m['fn']} tn={m['tn']})")
        for name, d in entry.get("paired_bootstrap", {}).items():
            print(f"  {name} F1 diff: {d['mean']:+.4f} "
                  f"[{d['ci95_low']:+.4f}, {d['ci95_high']:+.4f}] "
                  f"P(diff>0)={d['p_gt_zero']:.3f}")
        print(f"  invalid={entry['invalid_rate']:.3f} "
              f"abstain={entry['abstention_rate']:.3f} "
              f"tok_in_mean={entry['tokens']['input_mean']} "
              f"tok_out_mean={entry['tokens']['output_mean']}")
        print()

    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
