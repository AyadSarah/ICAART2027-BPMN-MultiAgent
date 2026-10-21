"""Quality measures for the PMo 05 case study (Claude original model and its three refinements).

Measures follow the syntactic, semantic and pragmatic metrics of Ayad (2013). Values that need a
reading of the description (e.g. whether the optional site visit is modelled) are reported in the
paper and in case_study/README.md; this script computes the countable ones.
"""
import collections
import xml.etree.ElementTree as ET

import pandas as pd

from common import REFERENCES, ROOT, require_pmo, save

require_pmo()
import validate_ground_truth as v  # noqa: E402

MODELS = ROOT / "case_study" / "models"
ACT = {"task", "userTask", "manualTask", "sendTask", "receiveTask", "serviceTask", "subProcess"}


def local(tag):
    return tag.rsplit("}", 1)[-1]


ref = v.parse(REFERENCES / "05.bpmn")
rows = []
for name in ["claude_original", "claude_self_refined", "claude_same_refined", "claude_cross_refined"]:
    path = MODELS / f"{name}.bpmn"
    root = ET.parse(path).getroot()
    E = list(root.iter())
    acts = [e for e in E if local(e.tag) in ACT]
    gws = [e for e in E if "Gateway" in local(e.tag)]
    sf = [e for e in E if local(e.tag) == "sequenceFlow"]
    out = collections.Counter(e.get("sourceRef") for e in sf)
    pairs = collections.Counter((e.get("sourceRef"), e.get("targetRef")) for e in sf)
    parent = {c: p for p in E for c in p}
    assoc = [e for e in E if local(e.tag) in ("dataInputAssociation", "dataOutputAssociation")]
    with_input = {parent[a].get("id") for a in assoc if local(a.tag) == "dataInputAssociation"}
    with_output = {parent[a].get("id") for a in assoc if local(a.tag) == "dataOutputAssociation"}
    lane_refs = {c.text.strip() for e in E if local(e.tag) == "lane" for c in e if local(c.tag) == "flowNodeRef" and c.text}
    procs_with_pool = {e.get("processRef") for e in E if local(e.tag) == "participant" and e.get("processRef")}
    actor = 0
    for p in (e for e in E if local(e.tag) == "process"):
        for a in (x for x in p.iter() if local(x.tag) in ACT):
            actor += int(a.get("id") in lane_refs or p.get("id") in procs_with_pool)
    xor_splits = [g for g in gws if local(g.tag) == "exclusiveGateway" and out[g.get("id")] >= 2]
    unlabelled_edges = sum(1 for g in xor_splits for e in sf if e.get("sourceRef") == g.get("id") and not (e.get("name") or "").strip())
    c = v.compare(ref, v.parse(path), 0.6)
    names = [a.get("name") or "" for a in acts]
    rows.append({
        "model": name,
        "activities": len(acts),
        "gateways": len(gws),
        "flow_nodes": len(acts) + len(gws) + sum(local(e.tag) in ("startEvent", "endEvent") for e in E),
        "sequence_flows": len(sf),
        "duplicate_sequence_flows": sum(n - 1 for n in pairs.values() if n > 1),
        "unlabelled_xor_outgoing_edges": unlabelled_edges,
        "pools": sum(local(e.tag) == "participant" for e in E),
        "pools_without_activities": sum(1 for e in E if local(e.tag) == "participant" and not e.get("processRef")),
        "activities_with_actor": actor,
        "activities_with_input_resource": len(with_input),
        "activities_with_output_resource": len(with_output),
        "data_artifacts": sum(local(e.tag) in ("dataObject", "dataStoreReference") for e in E),
        "message_flows": sum(local(e.tag) == "messageFlow" for e in E),
        "model_richness_recall": c["activity_recall_proxy"],
        "activity_precision": c["activity_precision_proxy"],
        "labels_beginning_with_verb_note": "checked manually: all activity labels begin with a verb",
        "compound_activity_labels": sum(" and " in n for n in names),
        "redundant_activity_names": sum(n2 - 1 for n2 in collections.Counter(names).values() if n2 > 1),
    })
save(pd.DataFrame(rows), "case_study_pmo05_quality.csv")
