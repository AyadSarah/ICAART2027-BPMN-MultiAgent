"""Research prototype: one-shot text-to-BPMN using the OpenAI Responses API.

No quality feedback, iterative correction, reference-model access, or auto-repair.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
import xml.etree.ElementTree as ET

from dotenv import load_dotenv
from layout import make_visualization

SYSTEM_PROMPT = """You are a business process modeler. Convert a natural-language process description DIRECTLY into a complete BPMN 2.0 XML document.
Return only XML, with no Markdown code fences or commentary.
Use the BPMN model namespace http://www.omg.org/spec/BPMN/20100524/MODEL and BPMN DI namespace http://www.omg.org/spec/BPMN/20100524/DI; also include namespaces http://www.omg.org/spec/DD/20100524/DC and http://www.omg.org/spec/DD/20100524/DI.
Provide bpmn:definitions, bpmn:process, appropriate BPMN events, tasks, gateways, and sequenceFlow elements.
ALSO output a bpmndi:BPMNDiagram with bpmndi:BPMNPlane bpmnElement referencing the process ID.
For EVERY BPMN flow node, include a bpmndi:BPMNShape with a dc:Bounds (x,y,width,height); for EVERY sequenceFlow, include a bpmndi:BPMNEdge with at least two di:waypoint elements. If you create lanes, include BPMNShape coordinates for each lane.
Use unique IDs. Every BPMNShape and BPMNEdge bpmnElement MUST exactly match the ID of its semantic BPMN element. Every sequenceFlow sourceRef and targetRef must refer to existing flow nodes.
Place nodes left to right in roughly execution order, with adequate spacing; put different participant lanes in separate horizontal rows when needed.
Represent exactly the activities, conditions and responsibilities in the description. Do not invent business rules or process steps. Do not use any external reference model.
Do not explain the XML. The BPMN diagram layout is REQUIRED, not optional.
"""


def check_xml(xml_text: str) -> dict:
    """Basic parsing/structural diagnostics only. NOT BPMN XSD or semantic validation."""
    result = {"xml_well_formed": False, "bpmn_namespace_root": False,
              "process_count": 0, "flow_node_count": 0,
              "sequence_flow_count": 0, "dangling_flow_references": [], "duplicate_ids": [],
              "note": "These checks do not establish BPMN 2.0 validity, soundness, semantic quality, or pragmatic quality.",
              "has_bpmn_diagram": False, "missing_node_shapes": [], "missing_flow_edges": []}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        result["parse_error"] = str(exc)
        return result
    result["xml_well_formed"] = True
    ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"
    result["bpmn_namespace_root"] = root.tag == f"{{{ns}}}definitions"
    result["process_count"] = len(root.findall(f"{{{ns}}}process"))
    ids = []
    for element in root.iter():
        if "id" in element.attrib:
            ids.append(element.attrib["id"])
    result["duplicate_ids"] = sorted({v for v in ids if ids.count(v) > 1})
    flow_node_names = {"startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent",
                       "task", "userTask", "serviceTask", "manualTask", "businessRuleTask", "scriptTask",
                       "sendTask", "receiveTask", "subProcess", "callActivity", "exclusiveGateway",
                       "inclusiveGateway", "parallelGateway", "eventBasedGateway", "complexGateway"}
    nodes = {e.attrib["id"] for e in root.iter() if e.tag.startswith(f"{{{ns}}}") and e.tag.split("}")[-1] in flow_node_names and "id" in e.attrib}
    result["flow_node_count"] = len(nodes)
    flows = root.findall(f".//{{{ns}}}sequenceFlow")
    result["sequence_flow_count"] = len(flows)
    for flow in flows:
        for attr in ("sourceRef", "targetRef"):
            if flow.get(attr) not in nodes:
                result["dangling_flow_references"].append({"flow_id": flow.get("id"), "attribute": attr, "value": flow.get(attr)})
    planes = root.findall(f".//{{http://www.omg.org/spec/BPMN/20100524/DI}}BPMNPlane")
    result["has_bpmn_diagram"] = bool(planes)
    shape_refs = {e.get("bpmnElement") for e in root.findall(f".//{{http://www.omg.org/spec/BPMN/20100524/DI}}BPMNShape")}
    edge_refs = {e.get("bpmnElement") for e in root.findall(f".//{{http://www.omg.org/spec/BPMN/20100524/DI}}BPMNEdge")}
    result["missing_node_shapes"] = sorted(nodes - shape_refs)
    result["missing_flow_edges"] = sorted({f.get("id") for f in flows if f.get("id")} - edge_refs)
    return result


def generate(client, model: str, description: str):
    return client.responses.create(model=model, instructions=SYSTEM_PROMPT, input=description)


def run(description_path: Path, output_root: Path, model: str, client=None) -> Path:
    load_dotenv()
    description = description_path.read_text(encoding="utf-8").strip()
    if not description:
        raise ValueError("Process description file is empty")
    if client is None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is missing. Add it to a local .env file (see .env.example).")
        from openai import OpenAI
        client = OpenAI()
    case_dir = output_root / description_path.stem / "openai"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "input_description.txt").write_text(description + "\n", encoding="utf-8")
    (case_dir / "prompt_system.txt").write_text(SYSTEM_PROMPT, encoding="utf-8")
    start = time.perf_counter()
    requested_at = datetime.now(timezone.utc).isoformat()
    try:
        response = generate(client, model, description)
    except Exception as exc:
        error = {"timestamp_utc": requested_at, "model_requested": model, "error_type": type(exc).__name__, "error": str(exc)}
        (case_dir / "api_error.json").write_text(json.dumps(error, indent=2), encoding="utf-8")
        raise
    elapsed = time.perf_counter() - start
    text = response.output_text or ""
    # Preserve the exact response text, even if the model violates XML-only instructions.
    (case_dir / "initial_raw.txt").write_text(text, encoding="utf-8")
    # Do not auto-correct or transform malformed XML: retain experimental failures.
    (case_dir / "initial.bpmn").write_text(text, encoding="utf-8")
    diagnostics = check_xml(text)
    # Independent convenience artifact only; never overwrite the original.
    visual, visual_status = make_visualization(text)
    if visual is not None:
        (case_dir / "visualization.bpmn").write_text(visual, encoding="utf-8")
    usage = getattr(response, "usage", None)
    metadata = {"timestamp_utc": requested_at, "model_requested": model,
                "model_returned": getattr(response, "model", None),
                "response_id": getattr(response, "id", None),
                "elapsed_seconds": round(elapsed, 3),
                "usage": usage.model_dump() if usage is not None and hasattr(usage, "model_dump") else None,
                "output_character_count": len(text), "diagnostics": diagnostics,
                "prompt_version": "initial-v2-with-DI", "temperature": "API default (not explicitly set)",
                "reference_model_used": False, "auto_repair": False,
                "visualization_adapter_status": visual_status,
                "visualization_is_original": visual is not None and visual == text}
    (case_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return case_dir


def main():
    parser = argparse.ArgumentParser(description="Generate one BPMN XML model from a text description using OpenAI.")
    parser.add_argument("--input", type=Path, required=True, help="UTF-8 text file containing one process description")
    parser.add_argument("--output", type=Path, default=Path("outputs"), help="Root folder for generated results")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5-mini"), help="Available OpenAI API model ID")
    args = parser.parse_args()
    try:
        output = run(args.input, args.output, args.model)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
    diagnostics = json.loads((output / "metadata.json").read_text(encoding="utf-8"))["diagnostics"]
    print(f"Saved output to {output.resolve()}")
    print(f"XML well formed: {diagnostics['xml_well_formed']}")
    print(f"BPMN diagram in original: {diagnostics['has_bpmn_diagram']}")
    print("Visualization copy: visualization.bpmn (not the experimental raw output)")
    print("Note: this is NOT comprehensive BPMN validity or quality assessment.")


if __name__ == "__main__":
    main()
