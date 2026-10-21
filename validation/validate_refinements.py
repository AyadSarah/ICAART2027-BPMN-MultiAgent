"""Post-hoc independent reference comparison. MUST be run separately from refinement_runner.py.
Lexical activity matching is only a heuristic proxy; NOT semantic/behavioral equivalence.
"""
import argparse,csv,importlib.util,json
from pathlib import Path

def load_validator(path):
    spec=importlib.util.spec_from_file_location('independent_gt_validator',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dataset',type=Path,required=True)
    ap.add_argument('--refinements',type=Path,required=True)
    ap.add_argument('--validator-script',type=Path,required=True)
    ap.add_argument('--output',type=Path,default=Path('validation_results'))
    ap.add_argument('--threshold',type=float,default=0.6)
    args=ap.parse_args()
    assert 0<=args.threshold<=1
    validator=load_validator(args.validator_script.resolve())
    dataset=args.dataset.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    rows=[]; detail=[]
    manifest=args.refinements/'refinement_manifest.csv'
    with manifest.open(encoding='utf-8-sig',newline='') as f:entries=list(csv.DictReader(f))
    for entry in entries:
        if entry['status'] not in ('COMPLETED_USABLE','COMPLETED_INVALID'):continue
        pmo=entry['pmo_id'];gen=entry['generator'];strategy=entry['strategy']
        ref=validator.parse(dataset/'ground_truth_RESTRICTED'/f'{pmo}.bpmn')
        original=validator.parse(dataset/'selected_for_analysis'/gen/f'pmo_{pmo}'/'initial.bpmn')
        refined=validator.parse(Path(entry['output_path']))
        before=validator.compare(ref,original,args.threshold)
        after=validator.compare(ref,refined,args.threshold)
        record={'pmo_id':pmo,'generator':gen,'strategy':strategy,
                'original_status':before.get('comparison_status'),'refined_status':after.get('comparison_status')}
        for fld in ('activity_precision_proxy','activity_recall_proxy'):
            v0=before.get(fld);v1=after.get(fld)
            record['original_'+fld]=v0;record['refined_'+fld]=v1
            record['delta_'+fld]=round(v1-v0,6) if isinstance(v0,(int,float)) and isinstance(v1,(int,float)) else None
        rows.append(record)
        detail.append({'case':record,'before':before,'after':after})
    with (out/'validation_manifest.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=list(rows[0]) if rows else ['pmo_id','generator','strategy']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    (out/'validation_details.json').write_text(json.dumps(detail,indent=2,ensure_ascii=False),encoding='utf-8')
    print('Compared',len(rows),'refinements; lexical activity matches only. Results:',out)

if __name__=='__main__':main()
