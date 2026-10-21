"""Reproducible BPMN refinement runner (separate from the original Agent 3 code).

No ground-truth files are read. No edits to the original BPMN models. Three configurations:
self (reconstructed conversation continuation), same (external same-provider report),
cross (external other-provider report). Each refinement STARTS FROM the original model.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

BPMN_ROOT = '{http://www.omg.org/spec/BPMN/20100524/MODEL}definitions'
STRATEGIES = ('self', 'same', 'cross')
SYSTEM = """You are an expert BPMN 2.0 modeler revising a previously generated model.
Return ONLY a complete BPMN 2.0 XML document with BPMN DI layout; no markdown or explanation.
Keep all correctly modeled activities, gateway logic, responsibilities and event conditions.
Repair justified errors based on the textual description and supplied feedback, but do NOT
blindly follow a suggested correction that contradicts the description. Do not invent activities,
branches or responsibilities. Preserve valid existing IDs where possible; ensure unique IDs,
resolved sequence flows, BPMN shapes, BPMN edges, Bounds and waypoints. No reference BPMN
model is provided or permitted. Your goal is quality, not superficial changes.
"""

def digest(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def extract_xml(text):
    s = text.strip().lstrip('\ufeff')
    fenced = re.fullmatch(r'```(?:xml|bpmn)?[ \t]*\r?\n(.*?)\r?\n```', s, flags=re.I | re.S)
    if fenced:
        s = fenced.group(1).strip()
    try:
        root=ET.fromstring(s)
        if root.tag != BPMN_ROOT:
            return None, 'WRONG_BPMN_ROOT'
        return s, 'XML_PARSED_BPMN_ROOT'
    except ET.ParseError as e:
        return None, f'XML_PARSE_ERROR: {e}'

def load_feedback(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows=list(csv.DictReader(f))
    keys={}
    for r in rows:
        key=(r.get('pmo_id','').strip().zfill(2),r.get('generator','').strip().lower())
        if key in keys:
            raise ValueError(f'Duplicate feedback key {key}')
        keys[key]=r
    required={'openai_suggested_corrections','claude_suggested_corrections',
              'openai_identified_issues','claude_identified_issues'}
    if rows and not required.issubset(rows[0]):
        raise ValueError(f'Missing columns: {required-set(rows[0])}')
    return keys

def feedback_for(row, generator, strategy):
    evaluator=generator if strategy=='same' else ('claude' if generator=='openai' else 'openai')
    if row.get(f'{evaluator}_evaluation_status','COMPLETE').strip().upper()!='COMPLETE':
        raise ValueError(f'{evaluator} evaluation not complete')
    issues=row.get(evaluator+'_identified_issues','').strip()
    corrections=row.get(evaluator+'_suggested_corrections','').strip()
    # Completed reviews can have no identified issues or suggested corrections.
    return evaluator, issues, corrections

def create_messages(description, xml, strategy, issues='', corrections=''):
    base=('ORIGINAL PROCESS DESCRIPTION:\n'+description+'\n\nORIGINAL BPMN XML:\n'+xml)
    if strategy=='self':
        # Reconstructed continuation: original hidden context is not recoverable from files.
        return [{'role':'user','content':'Generate a BPMN 2.0 model from this description:\n'+description},
                {'role':'assistant','content':xml},
                {'role':'user','content':'Now independently inspect your preceding BPMN output for syntactic, semantic, and pragmatic problems. Revise it once and return complete corrected BPMN XML only. Respect the original process description. Do not use any external evaluator feedback.'}]
    no_feedback = not issues.strip() and not corrections.strip()
    feedback = (
        'The completed evaluation contains no identified issues or suggested corrections. '
        'Do not invent defects or change a correct model just to produce an edit.'
        if no_feedback else 'ISSUES:\n'+issues+'\n\nSUGGESTED CORRECTIONS:\n'+corrections
    )
    return [{'role':'user','content':base+'\n\nINDEPENDENT EVALUATION FEEDBACK:\n'+
             feedback+'\n\nInspect against the description and revise only if justified.'}]

def call_api(provider, model, messages, max_tokens):
    start=time.perf_counter()
    if provider=='openai':
        from openai import OpenAI
        rsp=OpenAI(timeout=240).chat.completions.create(
            model=model,messages=[{'role':'system','content':SYSTEM}]+messages,
            max_completion_tokens=max_tokens)
        output=rsp.choices[0].message.content or ''
        usage=rsp.usage.model_dump() if rsp.usage else None
        meta={'model_returned':rsp.model,'response_id':rsp.id,'finish_reason':rsp.choices[0].finish_reason}
    elif provider=='claude':
        from anthropic import Anthropic
        rsp=Anthropic(timeout=240).messages.create(
            model=model,max_tokens=max_tokens,system=SYSTEM,messages=messages)
        output=''.join(x.text for x in rsp.content if getattr(x,'type',None)=='text')
        usage=rsp.usage.model_dump() if rsp.usage else None
        meta={'model_returned':rsp.model,'response_id':rsp.id,'finish_reason':rsp.stop_reason}
    else:
        raise ValueError(provider)
    return output,usage,meta,round(time.perf_counter()-start,3)

def validate(xml):
    if xml is None: return {'usable':False, 'check':'no_parseable_xml'}
    root=ET.fromstring(xml)
    ids=[e.get('id') for e in root.iter() if e.get('id')]
    duplicates=len(ids)-len(set(ids))
    nodes={e.get('id') for e in root.iter() if e.tag.startswith('{http://www.omg.org/spec/BPMN/20100524/MODEL}') and
           e.tag.rsplit('}',1)[-1] in {'task','userTask','serviceTask','sendTask','receiveTask','manualTask','scriptTask','businessRuleTask','subProcess','callActivity','startEvent','endEvent','boundaryEvent','intermediateCatchEvent','intermediateThrowEvent','exclusiveGateway','inclusiveGateway','parallelGateway','eventBasedGateway','complexGateway'}}
    flows=[e for e in root.iter() if e.tag=='{http://www.omg.org/spec/BPMN/20100524/MODEL}sequenceFlow']
    unresolved=sum(1 for e in flows for attr in ('sourceRef','targetRef') if e.get(attr) not in nodes)
    return {'usable':bool(nodes) and duplicates==0 and unresolved==0,'check':'basic_parse_and_references_only',
            'node_count':len(nodes),'flow_count':len(flows),'duplicate_ids':duplicates,'unresolved_flow_refs':unresolved,
            'not_proven':'XSD conformance, behavioral soundness, semantic or pragmatic quality'}

def get_ids(s):
    if s.lower()=='all':return [f'{i:02d}' for i in range(1,56)]
    return [str(int(k.strip())).zfill(2) for k in s.split(',') if k.strip()]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dataset',type=Path,required=True,help='Path to PMo_combined_analysis')
    ap.add_argument('--feedback',type=Path,required=True,help='agent3_side_by_side_all.csv')
    ap.add_argument('--output',type=Path,default=Path('refinement_results'))
    ap.add_argument('--ids',default='01,02,03,04,05')
    ap.add_argument('--generators',choices=['both','openai','claude'],default='both')
    ap.add_argument('--strategies',default='self,same,cross')
    ap.add_argument('--openai-model',default=os.getenv('OPENAI_MODEL',''))
    ap.add_argument('--claude-model',default=os.getenv('ANTHROPIC_MODEL',''))
    ap.add_argument('--max-tokens',type=int,default=12000)
    ap.add_argument('--dry-run',action='store_true',help='No API calls, report paths and evidence only')
    ap.add_argument('--overwrite',action='store_true',help='Rerun an existing case; does not touch originals')
    args=ap.parse_args()
    dataset=args.dataset.resolve(); output=args.output.resolve()
    if dataset==output or dataset in output.parents or output in dataset.parents:
        ap.error('Output and dataset must be separate directories')
    cases=get_ids(args.ids)
    if not cases or any(int(x)<1 or int(x)>55 for x in cases):ap.error('PMo IDs must be 1-55')
    strategies=[x.strip() for x in args.strategies.split(',')]
    if not strategies or any(x not in STRATEGIES for x in strategies):ap.error('Invalid strategies')
    generators=['openai','claude'] if args.generators=='both' else [args.generators]
    reviews=load_feedback(args.feedback)
    output.mkdir(parents=True,exist_ok=True)
    index=[]
    for pmo in cases:
        for gen in generators:
            original=dataset/'selected_for_analysis'/gen/f'pmo_{pmo}'/'initial.bpmn'
            desc=dataset/'descriptions'/f'{pmo}.txt'
            entry=reviews.get((pmo,gen))
            for strategy in strategies:
                dest=output/f'pmo_{pmo}'/gen/strategy
                row={'pmo_id':pmo,'generator':gen,'strategy':strategy,'original_path':str(original),
                     'description_path':str(desc),'output_path':str(dest/'refined.bpmn'),
                     'status':'PLANNED','evaluator':('none' if strategy=='self' else (gen if strategy=='same' else ('claude' if gen=='openai' else 'openai')))}
                if not original.exists() or not desc.exists():
                    row['status']='MISSING_INPUT'
                    index.append(row); print(row['status'],pmo,gen,strategy)
                    continue
                if entry is None and strategy!='self':
                    row['status']='MISSING_EVALUATION_ROW'; index.append(row);continue
                try:
                    xml=original.read_text(encoding='utf-8')
                    description=desc.read_text(encoding='utf-8').strip()
                    if not description:raise ValueError('Empty description')
                    parsed,_=extract_xml(xml)
                    if parsed is None:raise ValueError('Original is not parseable BPMN XML')
                    evaluator, issues,corrections= ('none','','') if strategy=='self' else feedback_for(entry,gen,strategy)
                    messages=create_messages(description,parsed,strategy,issues,corrections)
                    row['evaluator']=evaluator
                    row['original_sha256']=digest(xml)
                    row['feedback_sha256']=digest(issues+'\n'+corrections) if strategy!='self' else ''
                except Exception as e:
                    row['status']='PREPARATION_ERROR';row['error']=str(e);index.append(row);continue
                if args.dry_run:
                    row['status']='READY'; index.append(row);print('READY',pmo,gen,strategy);continue
                if dest.exists() and (dest/'run.json').exists() and not args.overwrite:
                    row['status']='SKIPPED_EXISTS';index.append(row);continue
                model=args.openai_model if gen=='openai' else args.claude_model
                if not model:
                    row['status']='MISSING_MODEL_ID';index.append(row);continue
                dest.mkdir(parents=True,exist_ok=True)
                (dest/'prompt.json').write_text(json.dumps({'system':SYSTEM,'messages':messages},indent=2,ensure_ascii=False),encoding='utf-8')
                try:
                    raw, usage,meta,seconds=call_api(gen,model,messages,args.max_tokens)
                    (dest/'refined_raw.txt').write_text(raw,encoding='utf-8')
                    refined,extract_status=extract_xml(raw)
                    if refined is not None:(dest/'refined.bpmn').write_text(refined,encoding='utf-8')
                    diagnostics=validate(refined)
                    row.update({'status':'COMPLETED_USABLE' if diagnostics['usable'] else 'COMPLETED_INVALID',
                                'elapsed_seconds':seconds,'refined_sha256':digest(refined) if refined is not None else '',
                                'changed_xml':refined != parsed if refined is not None else '',
                                'extract_status':extract_status,**{f'check_{k}':v for k,v in diagnostics.items() if isinstance(v,(str,int,bool))}})
                    manifest={'case':row,'api':meta,'model_requested':model,'usage':usage,
                              'validation':diagnostics,'timestamp_utc':datetime.now(timezone.utc).isoformat(),
                              'original_sha256':row['original_sha256'],
                              'method_note':'Self uses reconstructed continuation; original hidden context was not recorded. Separate-case branches always restart at original XML.'}
                except Exception as e:
                    row.update({'status':'API_ERROR','error':type(e).__name__+': '+str(e)})
                    manifest={'case':row,'timestamp_utc':datetime.now(timezone.utc).isoformat()}
                (dest/'run.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
                index.append(row);print(row['status'],pmo,gen,strategy)
    fields=sorted(set().union(*(r.keys() for r in index))) if index else ['status']
    with (output/'refinement_manifest.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(index)
    print('Saved manifest:',output/'refinement_manifest.csv')
    return 0

if __name__=='__main__':sys.exit(main())
