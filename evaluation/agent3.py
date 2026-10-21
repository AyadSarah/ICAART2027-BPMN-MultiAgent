"""Agent 3: deterministic BPMN diagnostics plus optional independent LLM review.
No PMo ground truths are read. No automatic correction is performed.
"""
import argparse, csv, json, os, re, time
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET

BPMN = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
BPMNDI = 'http://www.omg.org/spec/BPMN/20100524/DI'
DC = 'http://www.omg.org/spec/DD/20100524/DC'
DI = 'http://www.omg.org/spec/DD/20100524/DI'
NODE_TYPES = {'startEvent','endEvent','intermediateCatchEvent','intermediateThrowEvent','boundaryEvent',
 'task','userTask','serviceTask','scriptTask','manualTask','sendTask','receiveTask','businessRuleTask',
 'subProcess','callActivity','exclusiveGateway','inclusiveGateway','parallelGateway','eventBasedGateway','complexGateway'}

RUBRIC = '''You are an independent BPMN quality evaluator. Assess ONLY the supplied natural-language
process description and candidate BPMN XML. You have no ground-truth model and no access to a
generator's previous reasoning or other candidates. Never assume a reference model.
Assess SEMANTIC quality (coverage of all explicitly stated actions/events/conditions, correct order,
branch logic, responsibilities, no invented steps, appropriate task abstraction) and PRAGMATIC
quality (specific verb-object activity names, consistent labels, unnecessary complexity,
comprehensibility). Do not pretend XML parsing proves semantic correctness. Give evidence from
the description and BPMN for each observation. Do not invent errors when unsure.
Return ONLY one JSON object with exactly these fields:
{"semantic":{"score":null,"uncertain":true,"issues":[]},
 "pragmatic":{"score":null,"uncertain":true,"issues":[]},"overall_notes":""}
For each dimension, score an INTEGER from 0 to 4 (0 severe problems; 1 major;
2 moderate; 3 minor; 4 no apparent problems) or null if evidence insufficient.
Set uncertain boolean. Each issue is an object with keys category, severity
(high|medium|low), evidence_description, evidence_model, explanation,
suggested_correction. Do NOT assign scores if insufficient evidence. Do not
include Markdown. Scores are provisional judgments requiring independent validation.'''

def assess_structural(xml_path):
    result = {'xml_well_formed':False,'bpmn_root':False,'errors':[], 'warnings':[],
              'nodes':0,'sequence_flows':0,'duplicate_id_values':0, 'unresolved_refs':0,
              'missing_shapes':0,'missing_edges':0,'has_diagram':False}
    if not xml_path.is_file():
        result['errors'].append({'code':'NO_VALID_XML','detail':'No initial.bpmn saved'})
        return result
    try: root = ET.parse(xml_path).getroot()
    except ET.ParseError as ex:
        result['errors'].append({'code':'XML_PARSE_ERROR','detail':str(ex)})
        return result
    result['xml_well_formed']=True
    result['bpmn_root'] = root.tag == f'{{{BPMN}}}definitions'
    if not result['bpmn_root']: result['errors'].append({'code':'WRONG_ROOT','detail':root.tag})
    elements = list(root.iter())
    ids = Counter(x.attrib['id'] for x in elements if 'id' in x.attrib)
    duplicate = [k for k,v in ids.items() if v>1]
    result['duplicate_id_values'] = len(duplicate)
    if duplicate: result['errors'].append({'code':'DUPLICATE_IDS','count':len(duplicate),'examples':duplicate[:12]})
    nodes = {x.attrib['id']:x for x in elements if x.tag.startswith(f'{{{BPMN}}}') and x.tag.split('}')[-1] in NODE_TYPES and 'id' in x.attrib}
    flows = [x for x in elements if x.tag == f'{{{BPMN}}}sequenceFlow']
    result['nodes']=len(nodes); result['sequence_flows']=len(flows)
    missing=[]
    for f in flows:
        for att in ('sourceRef','targetRef'):
            if f.get(att) not in nodes: missing.append({'flow':f.get('id'), 'ref_kind':att,'ref':f.get(att)})
    result['unresolved_refs']=len(missing)
    if missing: result['errors'].append({'code':'UNRESOLVED_SEQUENCE_REFS','count':len(missing),'examples':missing[:12]})
    shape_refs = {x.get('bpmnElement') for x in elements if x.tag == f'{{{BPMNDI}}}BPMNShape'}
    edge_refs = {x.get('bpmnElement') for x in elements if x.tag == f'{{{BPMNDI}}}BPMNEdge'}
    planes = [x for x in elements if x.tag == f'{{{BPMNDI}}}BPMNPlane']
    result['has_diagram'] = bool(planes)
    if not planes: result['warnings'].append({'code':'NO_DIAGRAM'})
    no_shapes = sorted(set(nodes)-shape_refs); no_edges=sorted({f.get('id') for f in flows if f.get('id')}-edge_refs)
    result['missing_shapes']=len(no_shapes); result['missing_edges']=len(no_edges)
    if no_shapes: result['warnings'].append({'code':'MISSING_DI_SHAPES','count':len(no_shapes),'examples':no_shapes[:12]})
    if no_edges: result['warnings'].append({'code':'MISSING_DI_EDGES','count':len(no_edges),'examples':no_edges[:12]})
    for shape in [e for e in elements if e.tag == f'{{{BPMNDI}}}BPMNShape']:
        b=shape.find(f'{{{DC}}}Bounds')
        if b is None or any(b.get(k) is None for k in ('x','y','width','height')):
            result['warnings'].append({'code':'MALFORMED_SHAPE_BOUNDS','shape':shape.get('id')})
    for edge in [e for e in elements if e.tag == f'{{{BPMNDI}}}BPMNEdge']:
        if len(edge.findall(f'{{{DI}}}waypoint'))<2:
            result['warnings'].append({'code':'TOO_FEW_WAYPOINTS','edge':edge.get('id')})
    if not nodes: result['warnings'].append({'code':'NO_FLOW_NODES'})
    result['status'] = 'FAIL' if result['errors'] else ('FLAGGED' if result['warnings'] else 'PASS')
    return result

def parse_json_reply(txt):
    s=txt.strip()
    if s.startswith('```'):
        s=re.sub(r'^```(?:json)?\s*','',s,flags=re.I)
        s=re.sub(r'\s*```$','',s)
    out=json.loads(s)
    if not isinstance(out,dict) or not all(k in out for k in ('semantic','pragmatic')):
        raise ValueError('Unexpected evaluator JSON schema')
    return out

def llm_review(provider, model, description, xml_text):
    content = 'PROCESS DESCRIPTION:\n'+description+'\n\nGENERATED BPMN:\n'+xml_text
    if provider=='openai':
        from openai import OpenAI
        response=OpenAI(timeout=240).chat.completions.create(model=model, temperature=0,
               messages=[{'role':'system','content':RUBRIC},{'role':'user','content':content}])
        raw=response.choices[0].message.content or ''
        usage=response.usage.model_dump() if response.usage else None
    else:
        from anthropic import Anthropic
        response=Anthropic(timeout=240).messages.create(model=model,max_tokens=3500,
               system=RUBRIC,messages=[{'role':'user','content':content}])
        raw=''.join(b.text for b in response.content if getattr(b,'type',None)=='text')
        usage=response.usage.model_dump() if response.usage else None
    return raw,usage

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,default=Path('PMo_combined_analysis'))
    p.add_argument('--output',type=Path,default=Path('agent3_reports'))
    p.add_argument('--provider',choices=['none','openai','claude'],default='none',help='none runs deterministic rules only, without API credits')
    p.add_argument('--model',help='Model ID required for paid LLM calls')
    p.add_argument('--agent',choices=['openai','claude','both'],default='both',help='Which GENERATED models to assess')
    p.add_argument('--ids',default='01,02,03',help='Comma-separated PMo IDs; use all for 55')
    p.add_argument('--dry-run',action='store_true')
    args=p.parse_args()
    root=args.dataset.resolve(); out=args.output.resolve()
    if not (root/'selected_for_analysis').is_dir(): p.error('Missing combined dataset: '+str(root))
    if args.provider!='none' and not args.model: p.error('--model required for provider calls')
    ids = list(range(1,56)) if args.ids.lower()=='all' else [int(x.strip()) for x in args.ids.split(',') if x.strip()]
    if not ids or any(n<1 or n>55 for n in ids): p.error('IDs must be between 01 and 55')
    if root == out or root in out.parents: p.error('Reports must be outside dataset folder')
    records=[]
    for n in ids:
        for generator in (('openai','claude') if args.agent=='both' else (args.agent,)):
            case=root/'selected_for_analysis'/generator/f'pmo_{n:02d}'
            description=root/'descriptions'/f'{n:02d}.txt'
            model_file=case/'initial.bpmn'
            if not description.is_file(): p.error('Missing description: '+str(description))
            if args.dry_run:
                print(f'WOULD ASSESS PMo {n:02d} / generator={generator} / XML={model_file.is_file()} / evaluator={args.provider}')
                continue
            structural=assess_structural(model_file)
            report={'id':f'{n:02d}','generator':generator,'evaluator_provider':args.provider,
                    'evaluator_model':args.model if args.provider!='none' else None,
                    'structural':structural,'semantic':None,'pragmatic':None,
                    'llm_error':None,'usage':None,
                    'scoring_note':'No reference models used; LLM scores are provisional and non-ground-truth.'}
            if args.provider!='none' and structural['xml_well_formed'] and structural['bpmn_root']:
                try:
                    raw,usage=llm_review(args.provider,args.model,description.read_text(encoding='utf-8'),model_file.read_text(encoding='utf-8'))
                    report['usage']=usage
                    report['llm_raw']=raw
                    scored=parse_json_reply(raw)
                    report['semantic']=scored['semantic'];report['pragmatic']=scored['pragmatic']
                    report['overall_notes']=scored.get('overall_notes','')
                except Exception as exc: report['llm_error']=f'{type(exc).__name__}: {exc}'
            elif args.provider!='none':
                report['llm_error']='NOT_SCOREABLE: no valid BPMN XML; preserve as generation failure'
            records.append(report)
            print(f"PMo {n:02d} {generator}: {structural.get('status','FAIL')} / evaluator={args.provider}")
    if args.dry_run: return
    out.mkdir(parents=True,exist_ok=True)
    (out/'agent3_details.json').write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding='utf-8')
    with (out/'agent3_summary.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=['id','generator','evaluator_provider','structural_status','duplicate_ids','unresolved_refs','missing_shapes','missing_edges','semantic_score','pragmatic_score','llm_error'])
        writer.writeheader()
        for r in records:
            s=r['structural'];writer.writerow({'id':r['id'],'generator':r['generator'],'evaluator_provider':args.provider,
                'structural_status':s.get('status','FAIL'),'duplicate_ids':s['duplicate_id_values'],
                'unresolved_refs':s['unresolved_refs'],'missing_shapes':s['missing_shapes'],
                'missing_edges':s['missing_edges'],'semantic_score':(r['semantic'] or {}).get('score'),
                'pragmatic_score':(r['pragmatic'] or {}).get('score'),'llm_error':r['llm_error']})
    print(f'Saved {len(records)} assessments to {out}')
    print('CAUTION: Not BPMN XSD validation, soundness analysis, ground-truth assessment, or expert-validated semantic scoring.')

if __name__=='__main__': main()
