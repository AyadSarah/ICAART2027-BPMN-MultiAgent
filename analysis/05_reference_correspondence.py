"""Correspondence of the generated models with the PMo reference models (lexical activity matching)."""
import pandas as pd

from common import REFERENCES, SELECTED, require_pmo, save

require_pmo()
import validate_ground_truth as v  # noqa: E402  (src/validation)

rows = []
for g in ["openai", "claude"]:
    for n in range(1, 56):
        f = SELECTED / g / f"pmo_{n:02d}" / "initial.bpmn"
        if not f.exists():
            continue
        c = v.compare(v.parse(REFERENCES / f"{n:02d}.bpmn"), v.parse(f), 0.6)
        rows.append({"pmo_id": f"{n:02d}", "generator": g,
                     "reference_activities": c["reference_tasks"], "generated_activities": c["candidate_tasks"],
                     "matched_activities": c["matched_tasks"],
                     "precision": c["activity_precision_proxy"], "recall": c["activity_recall_proxy"],
                     "reference_gateways": c["reference_gateways"], "generated_gateways": c["candidate_gateways"]})
df = pd.DataFrame(rows)
save(df, "reference_correspondence_per_model.csv")

summary = []
for name, x in [("openai", df[df.generator == "openai"]), ("claude", df[df.generator == "claude"]), ("all", df)]:
    summary.append({"generator": name, "models": len(x),
                    "mean_precision": round(x.precision.mean(), 3), "mean_recall": round(x.recall.mean(), 3),
                    "fewer_activities_than_reference": int((x.generated_activities < x.reference_activities).sum()),
                    "same_number": int((x.generated_activities == x.reference_activities).sum()),
                    "more_activities": int((x.generated_activities > x.reference_activities).sum()),
                    "mean_generated_gateways": round(x.generated_gateways.mean(), 1),
                    "mean_reference_gateways": round(x.reference_gateways.mean(), 1),
                    "fewer_gateways_than_reference": int((x.generated_gateways < x.reference_gateways).sum())})
save(pd.DataFrame(summary), "reference_correspondence.csv")
