"""Generation outcomes, causes of unusable output, and complexity of failed descriptions."""
import re
import xml.etree.ElementTree as ET

import pandas as pd
from scipy import stats

from common import GEN, REFERENCES, SELECTED, load_records, require_pmo, save

require_pmo()
import validate_ground_truth as v  # noqa: E402

d = load_records()


def parses(xml):
    try:
        ET.fromstring(xml.encode())
        return True
    except ET.ParseError:
        return False


manifest = pd.read_csv(GEN / "analysis_manifest.csv", encoding="utf-8-sig", dtype={"process_id": str})

# Generation outcomes per generator
rows = []
for g in ["openai", "claude"]:
    x = d[d.generator == g]
    m = manifest[manifest.agent == g]
    rows.append({
        "generator": g,
        "attempts": len(x),
        "usable": int((x.generation_outcome == "USABLE_XML").sum()),
        "usable_rate_pct": round(100 * (x.generation_outcome == "USABLE_XML").mean(), 1),
        "recovered_with_16000_tokens": int((m.selection == "extended_token_recovery").sum()),
    })
save(pd.DataFrame(rows), "generation_outcomes.csv")

# Causes of unusable outputs
causes = []
for _, r in d[d.generation_outcome != "USABLE_XML"].iterrows():
    raw = SELECTED / r.generator / f"pmo_{r.pmo_id}" / "initial_raw.txt"
    cause = "output truncated (token limit)"
    if r.generator == "openai" and raw.exists():
        text = raw.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"<\?xml.*|<(bpmn2?:)?definitions.*", text, re.S)
        xml = re.sub(r"```.*$", "", m.group(0), flags=re.S).strip() if m else ""
        if parses(xml):
            cause = "parses"
        elif parses(amp := re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", xml)):
            cause = "unescaped & in a label"
        elif parses(re.sub(r"<(?![A-Za-z_/?!])", "&lt;", amp)):
            cause = "unescaped < in a label"
        else:
            cause = "mismatched closing tag"
    causes.append({"pmo_id": r.pmo_id, "generator": r.generator, "cause": cause})
c = pd.DataFrame(causes)
save(c.groupby(["generator", "cause"]).size().reset_index(name="models"), "failure_causes.csv")

# Size of failed descriptions (number of reference activities)
ref_acts = pd.Series({f"{n:02d}": v.parse(REFERENCES / f"{n:02d}.bpmn")["task_count"] for n in range(1, 56)})
failed = c[c.generator == "openai"].pmo_id
a, b = ref_acts[ref_acts.index.isin(failed)], ref_acts[~ref_acts.index.isin(failed)]
recovered = manifest[(manifest.agent == "claude") & (manifest.selection == "extended_token_recovery")].process_id
baseline = manifest[(manifest.agent == "claude") & (manifest.selection == "original_baseline")].process_id
out = pd.DataFrame([
    {"group": "OpenAI failed", "n": len(a), "mean_reference_activities": round(a.mean(), 1)},
    {"group": "OpenAI succeeded", "n": len(b), "mean_reference_activities": round(b.mean(), 1)},
    {"group": "Claude recovered (16000 tokens)", "n": len(recovered), "mean_reference_activities": round(ref_acts[recovered].mean(), 1)},
    {"group": "Claude original limit (8192 tokens)", "n": len(baseline), "mean_reference_activities": round(ref_acts[baseline].mean(), 1)},
])
out["mann_whitney_p_openai"] = round(stats.mannwhitneyu(a, b).pvalue, 3)
save(out, "failed_descriptions_size.csv")
