"""Outcome of the refinement runs (usability and change in activity correspondence)."""
import json

import pandas as pd

from common import REFERENCES, REFINEMENT, SELECTED, require_pmo, save

require_pmo()
import validate_ground_truth as v  # noqa: E402

rows = []
for run_set in sorted(p for p in REFINEMENT.iterdir() if p.is_dir()):
    for run in sorted(run_set.glob("pmo_*/*/*/run.json")):
        d = json.loads(run.read_text(encoding="utf-8-sig"))
        pmo, gen, strategy = run.parts[-4][4:], run.parts[-3], run.parts[-2]
        val = d.get("validation") or {}
        ref = v.parse(REFERENCES / f"{pmo}.bpmn")
        before = v.compare(ref, v.parse(SELECTED / gen / f"pmo_{pmo}" / "initial.bpmn"), 0.6)
        refined = run.with_name("refined.bpmn")
        after = v.compare(ref, v.parse(refined), 0.6) if refined.exists() else {}
        rows.append({
            "run_set": run_set.name, "pmo_id": pmo, "generator": gen, "strategy": strategy,
            "model_returned": (d.get("api") or {}).get("model_returned"),
            "usable": val.get("usable"), "duplicate_ids": val.get("duplicate_ids"),
            "unresolved_flow_refs": val.get("unresolved_flow_refs"),
            "error": (d.get("error") or "")[:80],
            "recall_before": before.get("activity_recall_proxy"), "recall_after": after.get("activity_recall_proxy"),
            "precision_before": before.get("activity_precision_proxy"), "precision_after": after.get("activity_precision_proxy"),
            "gateways_before": before.get("candidate_gateways"), "gateways_after": after.get("candidate_gateways"),
        })
df = pd.DataFrame(rows)
save(df, "refinement_runs.csv")
pilot = df[df.run_set == "pilot_v1_neutral_prompt"]
summary = pilot.assign(usable=pilot.usable.fillna(False).astype(bool)).groupby(["generator", "strategy"]).usable.agg(["sum", "count"]).reset_index()
summary.columns = ["generator", "strategy", "usable", "runs"]
save(summary, "refinement_pilot_usability.csv")
