"""Evaluator scores, agreement between evaluators, and paired generator comparison."""
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import cohen_kappa_score

from common import load_records, load_usable, save

u = load_usable()

# Mean (SD) scores by evaluator and generator
rows = []
for ev in ["openai", "claude"]:
    for dim in ["semantic", "pragmatic"]:
        col = f"{ev}_{dim}_score"
        row = {"evaluator": ev, "dimension": dim}
        for g in ["openai", "claude"]:
            x = u[u.generator == g][col]
            row[f"{g}_generated_mean"] = round(x.mean(), 2)
            row[f"{g}_generated_sd"] = round(x.std(), 2)
        row["all_mean"] = round(u[col].mean(), 2)
        row["all_sd"] = round(u[col].std(), 2)
        rows.append(row)
save(pd.DataFrame(rows), "scores_by_evaluator.csv")

# Agreement between the two evaluators
rng = np.random.default_rng(1)
rows = []
for dim in ["semantic", "pragmatic"]:
    a = u[f"openai_{dim}_score"].values
    c = u[f"claude_{dim}_score"].values
    diff = a - c
    labels = [0, 1, 2, 3, 4]
    boot = []
    for _ in range(5000):
        i = rng.integers(0, len(a), len(a))
        boot.append(cohen_kappa_score(a[i], c[i], weights="quadratic", labels=labels))
    rows.append({
        "dimension": dim,
        "n": len(a),
        "exact_agreement": int((diff == 0).sum()),
        "exact_agreement_pct": round(100 * (diff == 0).mean(), 1),
        "within_one_point": int((abs(diff) <= 1).sum()),
        "openai_higher": int((diff > 0).sum()),
        "claude_higher": int((diff < 0).sum()),
        "mean_difference_openai_minus_claude": round(diff.mean(), 2),
        "wilcoxon_p": stats.wilcoxon(a, c).pvalue,
        "chance_agreement_pct": round(100 * sum((a == k).mean() * (c == k).mean() for k in labels), 1),
        "quadratic_weighted_kappa": round(cohen_kappa_score(a, c, weights="quadratic", labels=labels), 2),
        "kappa_ci_low": round(np.percentile(boot, 2.5), 2),
        "kappa_ci_high": round(np.percentile(boot, 97.5), 2),
    })
save(pd.DataFrame(rows), "evaluator_agreement.csv")

# Paired comparison on descriptions where both generators produced a usable model
d = load_records()
ok = d.pivot(index="pmo_id", columns="generator", values="generation_outcome") == "USABLE_XML"
both = ok.index[ok.openai & ok.claude]
w = u[u.pmo_id.isin(both)].pivot(index="pmo_id", columns="generator")
rows = []
for col in ["activity_precision_proxy", "activity_recall_proxy", "candidate_activities",
            "openai_semantic_score", "openai_pragmatic_score", "claude_semantic_score", "claude_pragmatic_score"]:
    o, c = w[col]["openai"], w[col]["claude"]
    rows.append({"measure": col, "n_pairs": len(both), "openai_mean": round(o.mean(), 3),
                 "claude_mean": round(c.mean(), 3), "wilcoxon_p": round(stats.wilcoxon(o, c).pvalue, 3)})
save(pd.DataFrame(rows), "paired_comparison.csv")
