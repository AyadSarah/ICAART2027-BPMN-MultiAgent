"""Independent, deterministic BPMN reference comparison. Does not modify Agent 3.
Compares labels heuristically; no claim of semantic equivalence or full BPMN validity.
"""
import argparse,csv,json,re,xml.etree.ElementTree as ET
from pathlib import Path
from difflib import SequenceMatcher

NS='http://www.omg.org/spec/BPMN/20100524/MODEL'
ACT={'task','userTask','serviceTask','manualTask','scriptTask','receiveTask','sendTask','businessRuleTask','callActivity','subProcess'}
GATES={'exclusiveGateway','inclusiveGateway','parallelGateway','eventBasedGateway','complexGateway'}
EVENTS={'startEvent','endEvent','intermediateCatchEvent','intermediateThrowEvent','boundaryEvent'}
def local(tag):return tag.rsplit('}',1)[-1]
def norm(s):return ' '.join(re.findall(r'[a-z0-9]+',(s or '').lower()))
def parse(path):
    if not path.exists():return {'status':'MISSING','error':str(path)}
    try:root=ET.parse(path).getroot()
    except ET.ParseError as ex:return {'status':'INVALID_XML','error':str(ex)}
    all_e=list(root.iter()); nodes={e.get('id'):e for e in all_e if local(e.tag) in ACT|GATES|EVENTS and e.get('id')}
    tasks=[{'id':i,'label':e.get('name',''),'kind':local(e.tag)} for i,e in nodes.items() if local(e.tag) in ACT]
    flows=[(e.get('sourceRef'),e.get('targetRef')) for e in all_e if local(e.tag)=='sequenceFlow']
    lanes={}
    for e in all_e:
        if local(e.tag)=='lane':
            for child in e:
                if local(child.tag)=='flowNodeRef' and child.text:lanes[child.text.strip()]=e.get('name') or e.get('id','')
    participants=[e.get('name') or e.get('id') for e in all_e if local(e.tag)=='participant']
    return {'status':'PARSED','tasks':tasks,'nodes':nodes,'flows':flows,'lanes':lanes,'participants':participants,
      'node_count':len(nodes),'task_count':len(tasks),'gateway_count':sum(local(e.tag) in GATES for e in nodes.values()),
      'event_count':sum(local(e.tag) in EVENTS for e in nodes.values()),'flow_count':len(flows)}
def similarity(a,b):return SequenceMatcher(None,norm(a),norm(b)).ratio() if norm(a) and norm(b) else 0.0
def compare(ref,model,threshold):
    if ref['status']!='PARSED' or model['status']!='PARSED':return {'comparison_status':'NOT_COMPARABLE','reference_status':ref['status'],'candidate_status':model['status'],'reason':model.get('error') or ref.get('error')}
    pairs=[]
    for i,a in enumerate(ref['tasks']):
        for j,b in enumerate(model['tasks']):
            s=similarity(a['label'],b['label'])
            if s>=threshold:pairs.append((s,i,j))
    pairs.sort(reverse=True);usedr=set();usedm=set();matches=[]
    for s,i,j in pairs:
        if i not in usedr and j not in usedm:
            usedr.add(i);usedm.add(j)
            matches.append({'reference':ref['tasks'][i]['label'],'candidate':model['tasks'][j]['label'],'score':round(s,3),'reference_id':ref['tasks'][i]['id'],'candidate_id':model['tasks'][j]['id']})
    absent=[x for i,x in enumerate(ref['tasks']) if i not in usedr]
    extra=[x for i,x in enumerate(model['tasks']) if i not in usedm]
    # Only direct flow edges between matched task IDs; indirect paths, equivalent gateways and behavior are NOT inferred.
    mapids={x['reference_id']:x['candidate_id'] for x in matches}
    redges={(a,b) for a,b in ref['flows'] if a in mapids and b in mapids}
    medges=set(model['flows'])
    matched_edges=sum((mapids[a],mapids[b]) in medges for a,b in redges)
    responsibility=[]
    for m in matches:
        rl=ref['lanes'].get(m['reference_id']);cl=model['lanes'].get(m['candidate_id'])
        if rl or cl:responsibility.append({'activity':m['reference'],'reference_lane':rl,'candidate_lane':cl,'label_similarity':round(similarity(rl,cl),3) if rl and cl else None})
    return {'comparison_status':'HEURISTIC_ONLY','reference_tasks':ref['task_count'],'candidate_tasks':model['task_count'],
      'matched_tasks':len(matches),'activity_precision_proxy':round(len(matches)/model['task_count'],3) if model['task_count'] else None,
      'activity_recall_proxy':round(len(matches)/ref['task_count'],3) if ref['task_count'] else None,
      'matched_activity_pairs':matches,'unmatched_reference_activities':absent,'unmatched_candidate_activities':extra,
      'reference_gateways':ref['gateway_count'],'candidate_gateways':model['gateway_count'],
      'reference_events':ref['event_count'],'candidate_events':model['event_count'],
      'reference_flows':ref['flow_count'],'candidate_flows':model['flow_count'],
      'reference_direct_task_edges':len(redges),'matching_direct_task_edges':matched_edges,
      'responsibility_alignment_evidence':responsibility,
      'limitations':['Lexical activity matching is heuristic and may miss synonyms or wrongly match similar names.',
      'Different task decomposition and abstraction can be equally valid.',
      'Direct edge comparisons are not behavioral equivalence or process soundness.',
      'Lane names alone cannot determine responsibility correctness.',
      'Agent 3 issues are not automatically confirmed or rejected by this report.']}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--ids',default='01')
    p.add_argument('--output',type=Path,default=Path('ground_truth_reports'))
    p.add_argument('--threshold',type=float,default=0.6)
    a=p.parse_args()
    if not (0<=a.threshold<=1):p.error('threshold must be in [0,1]')
    root=a.dataset.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    ids=range(1,56) if a.ids.lower()=='all' else [int(s) for s in a.ids.split(',')]
    result=[];table=[]
    for n in ids:
        ref=parse(root/'ground_truth_RESTRICTED'/f'{n:02d}.bpmn')
        for gen in ['openai','claude']:
            candidate=parse(root/'selected_for_analysis'/gen/f'pmo_{n:02d}'/'initial.bpmn')
            c=compare(ref,candidate,a.threshold)
            result.append({'pmo_id':f'{n:02d}','generator':gen,'comparison':c})
            table.append({'pmo_id':f'{n:02d}','generator':gen,'status':c['comparison_status'],
                          'reference_tasks':c.get('reference_tasks'),'candidate_tasks':c.get('candidate_tasks'),
                          'matched_tasks':c.get('matched_tasks'),'precision_proxy':c.get('activity_precision_proxy'),
                          'recall_proxy':c.get('activity_recall_proxy'),'unmatched_reference':'; '.join(x['label'] for x in c.get('unmatched_reference_activities',[])),
                          'unmatched_candidate':'; '.join(x['label'] for x in c.get('unmatched_candidate_activities',[])),
                          'candidate_status':c.get('candidate_status','PARSED')})
            print(f'PMo {n:02d} {gen}: {c["comparison_status"]}; matched activities={c.get("matched_tasks","N/A")}')
    (out/'ground_truth_details.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    with (out/'ground_truth_summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
    print(f'Saved {len(table)} comparisons to {out}')
    print('Caution: heuristic correspondence evidence, NOT ground-truth proof of semantic correctness.')
if __name__=='__main__':main()
