"""Structural (syntactic) checks on the 88 usable generated models and the 55 reference models."""
import collections
import xml.etree.ElementTree as ET

import pandas as pd

from common import REFERENCES, SELECTED, require_pmo, save

require_pmo()
ACT = {"task", "userTask", "serviceTask", "manualTask", "scriptTask", "receiveTask", "sendTask",
       "businessRuleTask", "callActivity", "subProcess"}
GW = {"exclusiveGateway", "inclusiveGateway", "parallelGateway", "eventBasedGateway", "complexGateway"}
EV = {"startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent"}


def local(tag):
    return tag.rsplit("}", 1)[-1]


def check(path):
    root = ET.parse(path).getroot()
    r = collections.Counter()
    procs = [e for e in root.iter() if local(e.tag) == "process"]
    lanes = any(local(e.tag) == "lane" for e in root.iter())
    parts = [e for e in root.iter() if local(e.tag) == "participant"]
    r["more_than_one_pool"] = int(len(procs) > 1)
    r["no_lanes_no_pools"] = int(not lanes and not parts)
    for p in procs:
        nodes = {}

        def walk(e):
            for c in e:
                if local(c.tag) in ACT | GW | EV and c.get("id"):
                    nodes[c.get("id")] = c
                if local(c.tag) == "subProcess":
                    walk(c)
        walk(p)
        flows = [(e.get("sourceRef"), e.get("targetRef"), e) for e in p.iter() if local(e.tag) == "sequenceFlow"]
        inn = collections.Counter(t for s, t, _ in flows)
        out = collections.Counter(s for s, t, _ in flows)
        succ = collections.defaultdict(list)
        for s, t, _ in flows:
            succ[s].append(t)
        acts = [i for i, e in nodes.items() if local(e.tag) in ACT]
        if not acts:
            continue
        starts = [i for i, e in nodes.items() if local(e.tag) == "startEvent"]
        ends = [i for i, e in nodes.items() if local(e.tag) == "endEvent"]
        r["pool_without_start_event"] += int(not starts)
        r["pool_without_end_event"] += int(not ends)
        r["unlabelled_activity"] += sum(1 for i in acts if not (nodes[i].get("name") or "").strip())
        for i, e in nodes.items():
            if local(e.tag) in ACT | GW:
                r["node_without_incoming_flow"] += int(inn[i] == 0)
                r["node_without_outgoing_flow"] += int(out[i] == 0)
        for g in (i for i, e in nodes.items() if local(e.tag) in GW):
            r["gateway_one_in_one_out"] += int(inn[g] <= 1 and out[g] <= 1)
            r["gateway_split_and_join"] += int(inn[g] >= 2 and out[g] >= 2)
            if out[g] >= 2 and local(nodes[g].tag) == "exclusiveGateway":
                labelled = [(e.get("name") or "").strip() or any(local(c.tag) == "conditionExpression" for c in e)
                            for s, t, e in flows if s == g]
                r["decision_branch_without_label"] += int(not all(labelled))
        r["activity_with_several_incoming_flows"] += sum(1 for i in acts if inn[i] >= 2)
        seen, stack = set(starts), list(starts)
        while stack:
            x = stack.pop()
            for y in succ[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        if starts:
            r["activity_unreachable_from_start"] += sum(1 for i in acts if i not in seen)
    return r


rows = []
for g in ["openai", "claude"]:
    for n in range(1, 56):
        f = SELECTED / g / f"pmo_{n:02d}" / "initial.bpmn"
        if f.exists():
            rows.append({"pmo_id": f"{n:02d}", "model": g, **check(f)})
for n in range(1, 56):
    rows.append({"pmo_id": f"{n:02d}", "model": "reference", **check(REFERENCES / f"{n:02d}.bpmn")})
df = pd.DataFrame(rows).fillna(0)
save(df, "structural_checks_per_model.csv")
cols = [c for c in df.columns if c not in ("pmo_id", "model")]
summary = pd.DataFrame({m: (df[df.model == m][cols] > 0).sum() for m in ["openai", "claude", "reference"]})
summary.insert(0, "check", summary.index)
summary.columns = ["check", "openai_models", "claude_models", "reference_models"]
save(summary.reset_index(drop=True), "structural_checks.csv")
