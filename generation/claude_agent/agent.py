"""Agent 2: one-shot text-to-BPMN using Anthropic Claude Messages API.

Research baseline. No reference models, evaluation, revision, or auto repair.
"""
import argparse
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from layout import make_visualization

SYSTEM_PROMPT = 'You are a business process modeler. Convert a natural-language process description DIRECTLY into a complete BPMN 2.0 XML document.\nReturn only XML, with no Markdown code fences or commentary.\nUse the BPMN model namespace http://www.omg.org/spec/BPMN/20100524/MODEL and BPMN DI namespace http://www.omg.org/spec/BPMN/20100524/DI; also include namespaces http://www.omg.org/spec/DD/20100524/DC and http://www.omg.org/spec/DD/20100524/DI.\nProvide bpmn:definitions, bpmn:process, appropriate BPMN events, tasks, gateways, and sequenceFlow elements.\nALSO output a bpmndi:BPMNDiagram with bpmndi:BPMNPlane bpmnElement referencing the process ID.\nFor EVERY BPMN flow node, include a bpmndi:BPMNShape with a dc:Bounds (x,y,width,height); for EVERY sequenceFlow, include a bpmndi:BPMNEdge with at least two di:waypoint elements. If you create lanes, include BPMNShape coordinates for each lane.\nUse unique IDs. Every BPMNShape and BPMNEdge bpmnElement MUST exactly match the ID of its semantic BPMN element. Every sequenceFlow sourceRef and targetRef must refer to existing flow nodes.\nPlace nodes left to right in roughly execution order, with adequate spacing; put different participant lanes in separate horizontal rows when needed.\nRepresent exactly the activities, conditions and responsibilities in the description. Do not invent business rules or process steps. Do not use any external reference model.\nDo not explain the XML. The BPMN diagram layout is REQUIRED, not optional.\n'

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


def generate(client, model: str, description: str, max_tokens: int):
    return client.messages.create(
        model=model,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": description}],
        max_tokens=max_tokens,
    )


def response_text(response):
    return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")


def extract_xml(raw: str) -> tuple[str | None, str]:
    """Remove ONLY enclosing Markdown XML fences, never modify BPMN semantics.

    Retain the raw response separately. Reject unsupported surrounding text.
    """
    cleaned = raw.strip().lstrip("\ufeff")
    fenced = re.fullmatch(r"```(?:xml|bpmn)?[ \t]*\r?\n(.*?)\r?\n```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
        status = "markdown_fences_removed"
    else:
        candidate = cleaned
        status = "unchanged"
    try:
        root = ET.fromstring(candidate)
    except ET.ParseError as exc:
        return None, f"invalid_xml_after_extraction: {exc}"
    if root.tag != "{http://www.omg.org/spec/BPMN/20100524/MODEL}definitions":
        return None, "not_bpmn_definitions"
    return candidate, status


def run(description_path: Path, output_root: Path, model: str,
        max_tokens: int = 8192, client=None) -> Path:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    description = description_path.read_text(encoding="utf-8").strip()
    if not description:
        raise ValueError("Process description file is empty")
    if client is None:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY missing. Create a local .env file using .env.example.")
        from anthropic import Anthropic
        client = Anthropic(timeout=120.0)
    case_dir = output_root / description_path.stem / "claude"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "input_description.txt").write_text(description + "\n", encoding="utf-8")
    (case_dir / "prompt_system.txt").write_text(SYSTEM_PROMPT, encoding="utf-8")
    requested_at = datetime.now(timezone.utc).isoformat()
    start = time.perf_counter()
    try:
        response = generate(client, model, description, max_tokens)
    except Exception as exc:
        error = {"timestamp_utc": requested_at, "model_requested": model,
                 "error_type": type(exc).__name__, "error": str(exc)}
        (case_dir / "api_error.json").write_text(json.dumps(error, indent=2), encoding="utf-8")
        raise
    elapsed = time.perf_counter() - start
    text = response_text(response)
    (case_dir / "initial_raw.txt").write_text(text, encoding="utf-8")
    raw_diagnostics = check_xml(text)
    extracted_xml, extraction_status = extract_xml(text)
    if extracted_xml is not None:
        (case_dir / "initial.bpmn").write_text(extracted_xml, encoding="utf-8")
        diagnostics = check_xml(extracted_xml)
        visual, visual_status = make_visualization(extracted_xml)
    else:
        (case_dir / "initial.bpmn").unlink(missing_ok=True)
        (case_dir / "visualization.bpmn").unlink(missing_ok=True)
        diagnostics = raw_diagnostics
        visual, visual_status = None, "No valid BPMN XML available for visualization"
    if visual is not None:
        (case_dir / "visualization.bpmn").write_text(visual, encoding="utf-8")
    usage = getattr(response, "usage", None)
    usage_data = usage.model_dump() if usage is not None and hasattr(usage,"model_dump") else None
    metadata = {"timestamp_utc": requested_at, "provider": "anthropic",
                "model_requested": model, "model_returned": getattr(response,"model",None),
                "response_id": getattr(response,"id",None), "stop_reason": getattr(response,"stop_reason",None),
                "elapsed_seconds": round(elapsed,3), "usage": usage_data,
                "output_character_count": len(text), "max_tokens": max_tokens,
                "diagnostics": diagnostics, "raw_response_diagnostics": raw_diagnostics,
                "extraction_status": extraction_status, "extraction_applied": extraction_status == "markdown_fences_removed",
                "prompt_version":"initial-v2-with-DI",
                "temperature":"API default (not explicitly set)",
                "reference_model_used":False,"auto_repair":False,
                "visualization_adapter_status":visual_status,
                "visualization_is_original":visual is not None and visual==text,
                "visualization_matches_extracted":visual is not None and visual==extracted_xml}
    (case_dir / "metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    return case_dir


def main():
    load_dotenv(Path(__file__).resolve().parent / ".env")
    parser=argparse.ArgumentParser(description="Generate BPMN XML using Claude (one-shot).")
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=Path("outputs"))
    parser.add_argument("--model",default=os.getenv("ANTHROPIC_MODEL","claude-sonnet-4-5-20250929"))
    parser.add_argument("--max-tokens",type=int,default=int(os.getenv("ANTHROPIC_MAX_TOKENS","8192")))
    args=parser.parse_args()
    try:
        output=run(args.input,args.output,args.model,args.max_tokens)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}",file=sys.stderr)
        raise SystemExit(1)
    metadata=json.loads((output/"metadata.json").read_text(encoding="utf-8"))
    print(f"Saved output to {output.resolve()}")
    print(f"Raw response XML well formed: {metadata['raw_response_diagnostics']['xml_well_formed']}")
    print(f"Extracted BPMN XML well formed: {metadata['diagnostics']['xml_well_formed']}")
    print(f"Extraction status: {metadata['extraction_status']}")
    print(f"BPMN diagram in original: {metadata['diagnostics']['has_bpmn_diagram']}")
    print(f"Response stop reason: {metadata['stop_reason']}")
    print("Files: initial_raw.txt (unaltered response); initial.bpmn (extracted XML if valid)")
    print("Visualization copy: visualization.bpmn (if available; not experimental raw output)")
    print("Note: not comprehensive BPMN validity or quality assessment.")

if __name__=='__main__':
    main()
