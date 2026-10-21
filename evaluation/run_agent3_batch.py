"""Resume-safe batch orchestration for the UNMODIFIED agent3.py evaluator.

One folder per generator/evaluator/PMo; retains all 110 records and never reads ground truths.
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROVIDERS = ('openai','claude')
FIELDS = ['pmo_id','generator','openai_semantic_score','openai_pragmatic_score',
          'openai_identified_issues','openai_suggested_corrections',
          'claude_semantic_score','claude_pragmatic_score',
          'claude_identified_issues','claude_suggested_corrections',
          'openai_evaluation_status','claude_evaluation_status','ground_truth_verification']

def env_file(path):
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        x=line.strip()
        if not x or x.startswith('#') or '=' not in x:
            continue
        k,v=x.split('=',1)
        k=k.strip()
        if k in ('OPENAI_API_KEY','ANTHROPIC_API_KEY'):
            os.environ.setdefault(k,v.strip().strip('"').strip("'"))

def read_report(folder):
    file=folder/'agent3_details.json'
    if not file.is_file():
        return None
    try:
        obj=json.loads(file.read_text(encoding='utf-8'))
        return obj[0] if len(obj)==1 else None
    except (ValueError,IndexError,TypeError):
        return None

def finished(report):
    if not report:
        return False
    if report.get('llm_error'):
        return report.get('llm_error','').startswith('NOT_SCOREABLE:')
    return isinstance(report.get('semantic'),dict) and isinstance(report.get('pragmatic'),dict)

def flatten_issues(dimension):
    results=[]; corrections=[]
    for dim in ('semantic','pragmatic'):
        for item in (dimension.get(dim) or {}).get('issues',[]):
            if not isinstance(item,dict):
                continue
            cat=item.get('category') or 'unspecified'
            msg=item.get('explanation') or item.get('evidence_model') or ''
            results.append(f'{dim}: [{cat}] {msg}')
            fix=item.get('suggested_correction')
            if fix: corrections.append(f'{dim}: {fix}')
    return ' | '.join(results), ' | '.join(corrections)

def compile_results(base, ids):
    rows=[]; audit=[]
    for n in ids:
        for generator in PROVIDERS:
            row={'pmo_id':f'{n:02d}','generator':generator,'ground_truth_verification':'PENDING_INDEPENDENT_REVIEW'}
            for evaluator in PROVIDERS:
                report=read_report(base/evaluator/generator/f'pmo_{n:02d}')
                status='MISSING'
                if report:
                    if report.get('llm_error'):
                        status=report['llm_error']
                    elif finished(report):
                        status='COMPLETE'
                    else: status='INCOMPLETE'
                    issues,fixes=flatten_issues(report)
                    row[f'{evaluator}_semantic_score']=(report.get('semantic') or {}).get('score')
                    row[f'{evaluator}_pragmatic_score']=(report.get('pragmatic') or {}).get('score')
                    row[f'{evaluator}_identified_issues']=issues
                    row[f'{evaluator}_suggested_corrections']=fixes
                row[f'{evaluator}_evaluation_status']=status
                audit.append({'pmo_id':f'{n:02d}','generator':generator,'evaluator':evaluator,'status':status})
            rows.append(row)
    base.mkdir(parents=True,exist_ok=True)
    with (base/'agent3_side_by_side_all.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
    with (base/'agent3_run_status.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['pmo_id','generator','evaluator','status']);writer.writeheader();writer.writerows(audit)
    return audit

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=Path('../../PMo_combined_analysis'))
    parser.add_argument('--agent3',type=Path,default=Path('agent3.py'))
    parser.add_argument('--output',type=Path,default=Path('agent3_batch_reports'))
    parser.add_argument('--openai-model',default='gpt-4.1')
    parser.add_argument('--claude-model',default='claude-sonnet-4-5-20250929')
    parser.add_argument('--ids',default='all',help='all or comma-separated list, e.g. 01,02,03')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--max-retries',type=int,default=1)
    parser.add_argument('--stop-on-error',action='store_true',help='Stop on first failed paid evaluation')
    parser.add_argument('--max-calls',type=int,default=0,help='Maximum new paid API attempts, 0 means no limit')
    args=parser.parse_args()
    root=Path.cwd(); dataset=args.dataset.resolve(); script=args.agent3.resolve(); output=args.output.resolve()
    ids=list(range(1,56)) if args.ids.lower()=='all' else sorted(set(int(a.strip()) for a in args.ids.split(',') if a.strip()))
    if not ids or any(i<1 or i>55 for i in ids): parser.error('IDs must be within 01..55')
    if not script.is_file(): parser.error(f'Missing evaluator script: {script}')
    if not (dataset/'selected_for_analysis').is_dir(): parser.error(f'Missing combined dataset: {dataset}')
    if not (dataset/'descriptions').is_dir(): parser.error('Missing descriptions')
    if dataset == output or dataset in output.parents: parser.error('Output must be outside dataset')
    if args.max_retries<0 or args.max_calls<0: parser.error('Invalid limits')
    env_file(root/'.env')
    # Import the four previously successful PMo 01 pilot reports without new API charges.
    pilot_dirs={
        ('openai','openai'):'agent3_openai_test_v2',
        ('openai','claude'):'agent3_claude_test_v3',
        ('claude','openai'):'agent3_claude_generated_openai_eval_v2',
        ('claude','claude'):'agent3_claude_generated_claude_eval_v2',
    }
    if 1 in ids:
        for (generator,evaluator),folder in pilot_dirs.items():
            dest=output/evaluator/generator/'pmo_01'
            if finished(read_report(dest)):
                continue
            source=root/folder
            original=read_report(source)
            if finished(original) and not original.get('llm_error') and original.get('evaluator_model')==(args.openai_model if evaluator=='openai' else args.claude_model):
                if args.dry_run:
                    print(f'WOULD IMPORT existing PMo 01 {generator}->{evaluator} from {folder}',flush=True)
                else:
                    dest.mkdir(parents=True,exist_ok=True)
                    for filename in ('agent3_details.json','agent3_summary.csv'):
                        if (source/filename).is_file():shutil.copy2(source/filename,dest/filename)
                    print(f'IMPORTED existing PMo 01 {generator}->{evaluator}',flush=True)
    planned=0; skipped=0; failures=0; successes=0; paid=0
    for n in ids:
        for generator in PROVIDERS:
            model_file=dataset/'selected_for_analysis'/generator/f'pmo_{n:02d}'/'initial.bpmn'
            for evaluator in PROVIDERS:
                dest=output/evaluator/generator/f'pmo_{n:02d}'
                existing=read_report(dest)
                if finished(existing):
                    print(f'SKIP PMo {n:02d} {generator}->{evaluator}: saved',flush=True)
                    skipped+=1;continue
                is_usable=model_file.is_file()
                provider=evaluator if is_usable else 'none'
                if is_usable and not args.dry_run and not os.getenv('OPENAI_API_KEY' if evaluator=='openai' else 'ANTHROPIC_API_KEY'):
                    print(f'ERROR: API key not loaded for {evaluator}; stopping without API requests for this case.',flush=True)
                    compile_results(output,ids)
                    return 2
                if args.dry_run:
                    print(f'WOULD RUN PMo {n:02d} {generator}->{evaluator}: {"paid LLM" if is_usable else "structural-only; no XML"}',flush=True)
                    planned+=1;continue
                if is_usable and args.max_calls and paid>=args.max_calls:
                    print('Reached --max-calls; safely stopped.',flush=True)
                    compile_results(output,ids)
                    return 0
                model=args.openai_model if evaluator=='openai' else args.claude_model
                cmd=[sys.executable,str(script),'--dataset',str(dataset),'--agent',generator,'--ids',f'{n:02d}',
                     '--provider',provider,'--output',str(dest)]
                if provider!='none':cmd+=['--model',model]
                for attempt in range(args.max_retries+1):
                    if is_usable:paid+=1
                    print(f'RUN PMo {n:02d} {generator}->{evaluator} attempt {attempt+1}',flush=True)
                    try:
                        result=subprocess.run(cmd,cwd=root,capture_output=True,text=True,errors='replace',timeout=480)
                        report=read_report(dest)
                        if result.returncode==0 and (finished(report) or (not is_usable and report)):
                            print('  SAVED',flush=True); successes+=1;break
                        error=(report or {}).get('llm_error') or result.stderr[-400:] or 'Incomplete report'
                        print(f'  ERROR: {error}',flush=True)
                    except subprocess.TimeoutExpired:
                        print('  ERROR: request timeout',flush=True)
                    if attempt>=args.max_retries or (args.max_calls and paid>=args.max_calls):
                        failures+=1
                        if args.stop_on_error:
                            compile_results(output,ids)
                            print('STOPPED on error; rerun same command to resume.',flush=True)
                            return 1
                    else: time.sleep(5)
    if not args.dry_run:
        audit=compile_results(output,ids)
        print(f'Done: saved={successes} skipped={skipped} failed={failures}; status_rows={len(audit)}; new_paid_attempts={paid}',flush=True)
        print(f'Reports in: {output}',flush=True)
    else:print(f'DRY RUN: planned={planned} skipped={skipped} (no API calls)',flush=True)
    return 0
if __name__=='__main__':sys.exit(main())
