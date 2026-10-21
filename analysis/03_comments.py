"""Evaluator comments: themes, model-level overlap, abstraction level, and comment style."""
import re
from pathlib import Path

import pandas as pd

from common import load_usable, save, split_issues

u = load_usable()

# Keyword-based themes on the evaluators' own category tags
THEMES = [
    ("Missing content", r"missing|coverage|omit|incomplete|complete"),
    ("Control flow", r"flow|branch|order|sequenc|gateway logic|synchron|loop|parallel|conditional|decision|merge|join|split|event"),
    ("Responsibilities", r"responsib|resource|lane|role|actor|participant|pool"),
    ("Abstraction", r"abstraction|granular|specific|general|decompos"),
    ("Invented content", r"invent|hallucin|extra|unsupported|assum|redundan"),
    ("Labelling", r"label|nam|terminolog|wording"),
    ("Complexity", r"complex|comprehens|readab|layout|understand|clutter"),
]
SEMANTIC_ONLY = {"Missing content", "Control flow", "Responsibilities"}
PRAGMATIC_ONLY = {"Labelling", "Complexity"}


def theme(dim, tag):
    for name, pattern in THEMES:
        if dim == "pragmatic" and name in SEMANTIC_ONLY:
            continue
        if dim == "semantic" and name in PRAGMATIC_ONLY:
            continue
        if re.search(pattern, tag.lower()):
            return name
    return "Other"


rows = []
for _, r in u.iterrows():
    for ev in ["openai", "claude"]:
        for dim, tag, txt in split_issues(r[f"{ev}_identified_issues"]):
            rows.append({"pmo_id": r.pmo_id, "generator": r.generator, "evaluator": ev,
                         "dimension": dim, "category": tag, "theme": theme(dim, tag), "comment": txt})
issues = pd.DataFrame(rows)
save(issues, "evaluator_comments_long.csv")

# Theme table: share of comments and number of models raising the theme
out = []
totals = issues.groupby("evaluator").size()
for (dim, th), x in issues.groupby(["dimension", "theme"]):
    row = {"dimension": dim, "theme": th}
    models = {}
    for ev in ["openai", "claude"]:
        y = x[x.evaluator == ev]
        row[f"{ev}_share_pct"] = round(100 * len(y) / totals[ev], 1)
        models[ev] = set(zip(y.pmo_id, y.generator))
        row[f"{ev}_models"] = len(models[ev])
    row["both_models"] = len(models["openai"] & models["claude"])
    out.append(row)
save(pd.DataFrame(out), "comment_themes.csv")
save(issues.groupby(["evaluator", "dimension"]).size().reset_index(name="comments"), "comment_counts.csv")

# Abstraction level (manual coding of semantic comments, see analysis/abstraction_manual_coding.csv)
coding = pd.read_csv(Path(__file__).with_name("abstraction_manual_coding.csv"), dtype={"pmo": str})
g = coding[coding.code != "not_granularity"]
summary = []
for code, x in g.groupby("code"):
    summary.append({"code": code, "comments": len(x), "models": x.groupby(["pmo", "generator"]).ngroups,
                    "by_openai": int((x.evaluator == "openai").sum()), "by_claude": int((x.evaluator == "claude").sum()),
                    "openai_generated_models": x[x.generator == "openai"].pmo.nunique(),
                    "claude_generated_models": x[x.generator == "claude"].pmo.nunique()})
save(pd.DataFrame(summary), "abstraction_level.csv")

# Comment style
issues["quotes"] = issues.comment.str.contains(r"'[^']{3,}'|\"[^\"]{3,}\"")
issues["hedging"] = issues.comment.str.lower().str.contains(r"\b(?:could|may|might|minor|slightly|somewhat|generally|acceptable)\b")
issues["words"] = issues.comment.str.split().str.len()
style = issues.groupby("evaluator").agg(median_words=("words", "median"),
                                         quotes_pct=("quotes", "mean"), hedging_pct=("hedging", "mean")).reset_index()
style[["quotes_pct", "hedging_pct"]] = (100 * style[["quotes_pct", "hedging_pct"]]).round(1)
save(style, "comment_style.csv")
