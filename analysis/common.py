"""Shared paths and helpers for the analysis scripts.

Run every script from the repository root, e.g.  python analysis/01_generation.py
The PMo reference models are read from data/PMo_ready (created by data/prepare_pmo.py).
"""
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PMO = ROOT / "data" / "PMo_ready"
REFERENCES = PMO / "references_bpmn"
GEN = ROOT / "results" / "generation" / "PMo_combined_analysis"
SELECTED = GEN / "selected_for_analysis"
EVAL_CSV = ROOT / "results" / "evaluation" / "PMo_55_Combined_Evaluation.csv"
REFINEMENT = ROOT / "results" / "refinement"
TABLES = ROOT / "results" / "tables"
TABLES.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "src" / "validation"))


def require_pmo():
    if not REFERENCES.exists():
        sys.exit("PMo references not found. Run:  python data/prepare_pmo.py --out data/PMo_ready")


def load_records():
    """All 110 generation records with evaluator scores and reference proxies."""
    return pd.read_csv(EVAL_CSV, encoding="utf-8-sig", dtype={"pmo_id": str})


def load_usable():
    d = load_records()
    return d[d.generation_outcome == "USABLE_XML"].copy()


def split_issues(text):
    """Split an evaluator issue string into (dimension, category, comment) items."""
    items = []
    if not isinstance(text, str):
        return items
    for part in text.split(" | "):
        m = re.match(r"\s*(\w+):\s*\[([^\]]+)\]\s*(.*)", part, re.S)
        if m:
            items.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
    return items


def save(df, name):
    path = TABLES / name
    df.to_csv(path, index=False)
    print(f"-> {path.relative_to(ROOT)}")
