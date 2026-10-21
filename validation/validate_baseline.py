"""Conservative, non-destructive BPMN 2.0 structural checks for PMo generations.

No third-party Python packages or API keys needed.
This is NOT formal BPMN schema validation, soundness or semantic quality scoring.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

BPMN = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
BPMNDI = 'http://www.omg.org/spec/BPMN/20100524/DI'
DC = 'http://www.omg.org/spec/DD/20100524/DC'
DI = 'http://www.omg.org/spec/DD/20100524/DI'
FLOWS = {'sequenceFlow'}
NODES = {'startEvent','endEvent','intermediateCatchEvent','intermediateThrowEvent',
         'boundaryEvent','task','userTask','serviceTask','manualTask','scriptTask',
         'businessRuleTask','sendTask','receiveTask','callActivity','subProcess',
         'exclusiveGateway','inclusiveGateway','parallelGateway','eventBasedGateway',
         'complexGateway','transaction','adHocSubProcess'}
TARGETED_ATTRS = {'sourceRef','targetRef','processRef','attachedToRef','default','bpmnElement'}
COLUMNS = ['repeat','agent','process_id','source_file','xml_well_formed','bpmn_root',
           'num_processes','num_nodes','num_sequence_flows','num_message_flows',
           'duplicate_id_count','duplicate_ids','unresolved_reference_count',
           'unresolved_references','diagram_present','missing_shape_count','missing_shapes',
           'missing_edge_count','missing_edges','invalid_di_geometry_count',
           'invalid_di_geometry','raw_markdown_fenced','extraction_status',
           'xml_parse_error','baseline_flags_count','baseline_status']

def lname(tag):
    return tag.rsplit('}',1)[-1] if isinstance(tag,str) else ''

def xml_elements(root):
    return list(root.iter())

def inspect(path: Path):
    r = dict.fromkeys(COLUMNS, '')
    r.update(xml_well_formed=False,bpmn_root=False,num_processes=0,num_nodes=0,
             num_sequence_flows=0,num_message_flows=0,duplicate_id_count=0,
             unresolved_reference_count=0,diagram_present=False,missing_shape_count=0,
             missing_edge_count=0,invalid_di_geometry_count=0,baseline_flags_count=0,
             baseline_status='FAIL')
    if not path.is_file():
        r['xml_parse_error']='missing initial.bpmn'
        return r
    try:
        root=ET.parse(path).getroot()
    except (ET.ParseError, UnicodeError, OSError) as ex:
        r['xml_parse_error']=str(ex)
        return r
    r['xml_well_formed']=True
    r['bpmn_root']=root.tag == f'{{{BPMN}}}definitions'
    elems=xml_elements(root)
    semantics=[e for e in elems if e.tag.startswith('{'+BPMN+'}')]
    ids=[e.get('id') for e in elems if e.get('id')]
    counts=Counter(ids)
    dup=sorted(k for k,v in counts.items() if v>1)
    r['duplicate_id_count']=len(dup)
    r['duplicate_ids']='; '.join(dup)
    all_ids=set(ids)
    model_ids={e.get('id') for e in semantics if e.get('id')}
    nodes=[e for e in semantics if lname(e.tag) in NODES]
    flows=[e for e in semantics if lname(e.tag)=='sequenceFlow']
    messages=[e for e in semantics if lname(e.tag)=='messageFlow']
    r['num_processes']=sum(lname(e.tag)=='process' for e in semantics)
    r['num_nodes']=len(nodes)
    r['num_sequence_flows']=len(flows)
    r['num_message_flows']=len(messages)
    node_ids={e.get('id') for e in nodes if e.get('id')}
    errors=[]
    for e in elems:
        origin=f'{lname(e.tag)}[{e.get("id") or "no-id"}]'
        for attr in TARGETED_ATTRS:
            if attr not in e.attrib: continue
            target=e.get(attr)
            targets=model_ids if attr == 'bpmnElement' else all_ids
            if target not in targets:
                errors.append(f'{origin}.{attr}={target}')
    for flow in flows:
        for attr in ('sourceRef','targetRef'):
            if flow.get(attr) not in node_ids:
                tag=f'sequenceFlow[{flow.get("id") or "no-id"}].{attr} is not a flow node'
                if tag not in errors:errors.append(tag)
    for e in elems:
        if e.tag == f'{{{BPMN}}}flowNodeRef' and (e.text or '').strip() not in node_ids:
            errors.append(f'flowNodeRef={e.text!r}')
    r['unresolved_reference_count']=len(errors)
    r['unresolved_references']='; '.join(errors)
    diagram=list(root.iter(f'{{{BPMNDI}}}BPMNDiagram'))
    r['diagram_present']=bool(diagram)
    shapes=list(root.iter(f'{{{BPMNDI}}}BPMNShape'))
    edges=list(root.iter(f'{{{BPMNDI}}}BPMNEdge'))
    shape_refs={e.get('bpmnElement') for e in shapes}
    edge_refs={e.get('bpmnElement') for e in edges}
    missing_shapes=sorted(x for x in node_ids if x not in shape_refs)
    missing_edges=sorted(e.get('id') for e in flows if e.get('id') and e.get('id') not in edge_refs)
    r['missing_shape_count']=len(missing_shapes)
    r['missing_shapes']='; '.join(missing_shapes)
    r['missing_edge_count']=len(missing_edges)
    r['missing_edges']='; '.join(missing_edges)
    geometry=[]
    for s in shapes:
        bound=s.find(f'{{{DC}}}Bounds')
        if bound is None: geometry.append(f'shape[{s.get("id")}] missing Bounds');continue
        try:
            if float(bound.get('width','0'))<=0 or float(bound.get('height','0'))<=0:
                geometry.append(f'shape[{s.get("id")}] nonpositive dimensions')
            float(bound.get('x',''));float(bound.get('y',''))
        except ValueError:geometry.append(f'shape[{s.get("id")}] nonnumeric Bounds')
    for edge in edges:
        if len(edge.findall(f'{{{DI}}}waypoint'))<2:
            geometry.append(f'edge[{edge.get("id")}] fewer than 2 waypoints')
    r['invalid_di_geometry_count']=len(geometry)
    r['invalid_di_geometry']='; '.join(geometry)
    flags = int(not r['bpmn_root']) + int(r['num_processes']==0)+int(not r['diagram_present']) +sum([
        r['duplicate_id_count'],r['unresolved_reference_count'],r['missing_shape_count'],
        r['missing_edge_count'],r['invalid_di_geometry_count']])
    r['baseline_flags_count']=flags
    r['baseline_status']='PASS' if flags==0 else 'FLAGGED'
    return r

def find_models(folder):
    # Agent outputs may contain nested ID and agent folders from --output conventions.
    for p in sorted(folder.rglob('initial.bpmn')):
        if any(part in ('visualization',) for part in p.parts):continue
        parts=p.relative_to(folder).parts
        repeat=next((v for v in parts if re.fullmatch(r'repeat_\d+',v)), folder.name if re.fullmatch(r'repeat_\d+',folder.name) else 'unknown')
        agent=next((v for v in parts if v in ('openai','claude')), 'unknown')
        process=next((v for v in parts if re.fullmatch(r'pmo_\d+',v)), 'unknown')
        yield p,repeat,agent,process

def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--input',type=Path,default=Path('batch_outputs'),help='Batch outputs directory (all repeats or a single repeat)')
    a.add_argument('--report-dir',type=Path,default=Path('baseline_reports'))
    opt=a.parse_args()
    if not opt.input.is_dir():a.error(f'Missing directory: {opt.input}')
    opt.report_dir.mkdir(parents=True,exist_ok=True)
    rows=[]
    for p,repeat,agent,process in find_models(opt.input):
        report=inspect(p)
        report.update(repeat=repeat,agent=agent,process_id=process,source_file=str(p))
        raw=p.parent/'initial_raw.txt'
        if raw.is_file():
            s=raw.read_text(encoding='utf-8-sig',errors='replace').lstrip()
            report['raw_markdown_fenced']=s.startswith('```')
        md=p.parent/'metadata.json'
        if md.is_file():
            try:
                data=json.loads(md.read_text(encoding='utf-8'))
                report['extraction_status']=data.get('extraction_status', '')
            except (ValueError,OSError): report['extraction_status']='metadata_unreadable'
        rows.append(report)
    if not rows:a.error(f'No initial.bpmn files found inside {opt.input}')
    csv_path=opt.report_dir/'baseline_summary.csv'
    with csv_path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=COLUMNS);writer.writeheader();writer.writerows(rows)
    json_path=opt.report_dir/'baseline_details.json'
    json_path.write_text(json.dumps(rows,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f'Checked {len(rows)} generated models; PASS={sum(r["baseline_status"]=="PASS" for r in rows)}, FLAGGED={sum(r["baseline_status"]=="FLAGGED" for r in rows)}, FAIL={sum(r["baseline_status"]=="FAIL" for r in rows)}')
    for r in rows:
        print(f'{r["repeat"]} {r["agent"]:7s} {r["process_id"]:7s} {r["baseline_status"]:7s} duplicate_IDs={r["duplicate_id_count"]} unresolved_refs={r["unresolved_reference_count"]} missing_DI_shapes={r["missing_shape_count"]} missing_DI_edges={r["missing_edge_count"]}')
    print(f'Reports saved: {csv_path} and {json_path}')
    print('NOTE: PASS only means these preliminary structural checks passed; not full BPMN validity, soundness, or semantic/pragmatic quality.')

if __name__=='__main__':main()
