"""Build an auditable PMo analysis dataset without changing source experiments.

Usage (from the inner pmo_research_setup directory):
  py build_combined_pmo.py --claude-dir "C:\\...\\claude_bpmn_agent_2\\claude_bpmn_agent_2"

No API calls. The original 8192-token generation is retained separately. The
combined view substitutes valid 16000-token Claude recovery XML where available.
"""
import argparse
import csv
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BPMN_ROOT = '{http://www.omg.org/spec/BPMN/20100524/MODEL}definitions'
FIELDS = ['process_id','agent','selection','generation_condition','model_status',
          'reference_available','source_case','model_source_path','stop_reason',
          'output_tokens','max_tokens','xml_sha256','notes']

def fingerprint(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ''

def valid_xml(path):
    if not path.is_file():
        return False
    try:
        return ET.parse(path).getroot().tag == BPMN_ROOT
    except (ET.ParseError, OSError):
        return False

def meta_at(case):
    file = case / 'metadata.json'
    if not file.is_file():
        return {}
    try:
        return json.loads(file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}

def locate_original(base, agent, n):
    # Batch tool passes --output batch_outputs/repeat_01/<agent>/pmo_NN,
    # and each agent writes to <output>/NN/<agent>/.
    root = base / 'batch_outputs' / 'repeat_01' / agent / f'pmo_{n:02d}'
    return root / f'{n:02d}' / agent

def capture(source, dest):
    dest.mkdir(parents=True, exist_ok=True)
    for filename in ('initial_raw.txt','metadata.json','prompt_system.txt','input_description.txt','initial.bpmn'):
        f = source / filename
        if f.is_file():
            shutil.copy2(f, dest / filename)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--claude-dir', required=True, type=Path)
    p.add_argument('--project', type=Path, default=Path('.'))
    p.add_argument('--output', type=Path, default=Path('PMo_combined_analysis'))
    args = p.parse_args()
    project = args.project.resolve()
    recovery = args.claude_dir.resolve() / 'recovery_16000'
    output = args.output.resolve()
    if output == project or output == recovery or output == args.claude_dir.resolve():
        p.error('Choose a separate analysis output directory.')
    if output.exists():
        p.error(f'Output already exists: {output}. Nothing changed; choose a new --output or rename the existing folder.')
    reference_root = project / 'PMo_ready' / 'references_bpmn'
    description_root = project / 'PMo_ready' / 'descriptions'
    if not description_root.is_dir() or not reference_root.is_dir():
        p.error('Missing PMo_ready/descriptions or PMo_ready/references_bpmn; run from the inner setup directory.')
    output.mkdir(parents=True)
    manifest = []
    for n in range(1, 56):
        stem = f'{n:02d}'
        desc = description_root / f'{stem}.txt'
        ref = reference_root / f'{stem}.bpmn'
        if not desc.is_file():
            p.error(f'Missing process description: {desc}')
        if desc.is_file():
            dest = output / 'descriptions' / desc.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(desc, dest)
        if ref.is_file():
            dest = output / 'ground_truth_RESTRICTED' / ref.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ref, dest)
        for agent in ('openai', 'claude'):
            original = locate_original(project, agent, n)
            selected = original
            selection = 'original_baseline'
            condition = 'original'
            recovered = recovery / stem / 'claude'
            if agent == 'claude' and valid_xml(recovered / 'initial.bpmn'):
                # Selection conditioned ONLY on recovery having XML, not any quality score.
                selected = recovered
                selection = 'extended_token_recovery'
                condition = '16000_token_recovery'
            elif agent == 'claude' and recovered.is_dir():
                selection = 'original_baseline__recovery_unusable'
            selected_meta = meta_at(selected)
            original_meta = meta_at(original)
            original_dest = output / 'original_baseline' / agent / f'pmo_{stem}'
            capture(original, original_dest)
            if agent == 'claude' and recovered.is_dir():
                capture(recovered, output / 'recovery_archive' / agent / f'pmo_{stem}')
            model = selected / 'initial.bpmn'
            status = 'XML_AVAILABLE' if valid_xml(model) else 'NO_VALID_XML'
            if model.is_file() and not valid_xml(model):
                status = 'INVALID_XML_FILE'
            out_case = output / 'selected_for_analysis' / agent / f'pmo_{stem}'
            out_case.mkdir(parents=True, exist_ok=True)
            if valid_xml(model):
                shutil.copy2(model, out_case / 'initial.bpmn')
            # Keep selected raw response and metadata with model; never fabricate BPMN XML.
            for f in ('initial_raw.txt', 'metadata.json'):
                if (selected / f).is_file():
                    shutil.copy2(selected / f, out_case / f)
            usage = selected_meta.get('usage') or {}
            notes = []
            if not original.is_dir():
                notes.append('original_output_missing')
            if agent == 'claude' and recovered.is_dir() and selected == original:
                notes.append('recovery_exists_but_no_valid_xml')
            if selected_meta.get('stop_reason') == 'max_tokens':
                notes.append('output_token_limit_reached')
            if status != 'XML_AVAILABLE':
                notes.append('not_scoreable_as_complete_xml')
            record = dict(process_id=stem, agent=agent, selection=selection,
                generation_condition=condition, model_status=status,
                reference_available=ref.is_file(), source_case=str(selected),
                model_source_path=str(model) if model.is_file() else '',
                stop_reason=selected_meta.get('stop_reason',''),
                output_tokens=usage.get('output_tokens',''),
                max_tokens=selected_meta.get('max_tokens',''),
                xml_sha256=fingerprint(model) if valid_xml(model) else '',
                notes=';'.join(notes))
            manifest.append(record)
    with (output / 'analysis_manifest.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(manifest)
    stats = {agent:dict(Counter(r['model_status'] for r in manifest if r['agent']==agent)) for agent in ('openai','claude')}
    summary = {'created_utc': datetime.now(timezone.utc).isoformat(),
               'rows':len(manifest), 'counts_by_agent':stats,
               'recovered_claude_used': sum(r['selection']=='extended_token_recovery' for r in manifest),
               'missing_or_invalid': [{'id':r['process_id'],'agent':r['agent'],'status':r['model_status']} for r in manifest if r['model_status']!='XML_AVAILABLE'],
               'reference_files_found':sum((reference_root / f'{i:02d}.bpmn').is_file() for i in range(1,56))}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2),encoding='utf-8')
    (output / 'README.txt').write_text('''PMo combined analysis dataset\n\n'
'original_baseline/: Copies of raw original agent outputs (8192-token Claude condition retained).\n'
'recovery_archive/: Copies of 16000-token Claude recovery outputs, including failed PMo 18.\n'
'selected_for_analysis/: One selected output per process and provider; incomplete outputs have no initial.bpmn.\n'
'ground_truth_RESTRICTED/: Reference models. NEVER expose to generating or feedback agents.\n'
'analysis_manifest.csv: Provenance, configurations, and statuses.\n'
'IMPORTANT: This is a combined analysis view, NOT a homogeneous-token-budget baseline.\n'
'Models selected from recovery have a different output limit. Do not conflate their quality with the original setting.\n'
'Selection is based on parseable BPMN XML availability, not semantic correctness.\n'''.replace("'\n'", ''),encoding='utf-8')
    print('Completed. Analysis folder:',output)
    print(json.dumps(summary,indent=2))
    print('Original experiment folders were not modified. No API requests made.')

if __name__ == '__main__':
    main()
