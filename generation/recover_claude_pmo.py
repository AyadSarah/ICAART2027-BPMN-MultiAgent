"""Recover the 17 PMo Claude generations absent from the initial BPMN validation.

Run from the pmo_research_setup folder. Does NOT touch batch_outputs,
original batch_runs.jsonl, or the original 8192-token baseline.
Reuses a saved PMo 06 recovery. Separate 16000-token condition.
"""
import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

MISSING = (6, 16, 17, 18, 20, 24, 25, 27, 28, 29, 32, 33, 35, 37, 38, 45, 55)

def completed(folder):
    xml_file = folder / 'initial.bpmn'
    meta_file = folder / 'metadata.json'
    if not xml_file.is_file() or not meta_file.is_file():
        return False
    try:
        import xml.etree.ElementTree as ET
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
        root = ET.parse(xml_file).getroot()
        return (root.tag == '{http://www.omg.org/spec/BPMN/20100524/MODEL}definitions'
                and meta.get('stop_reason') == 'end_turn')
    except (OSError, ValueError, ET.ParseError):
        return False

def append_record(journal, entry):
    with journal.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + '\n')

def connection_problem(text):
    text = text.lower()
    return any(token in text for token in ('apiconnectionerror', 'connection error',
        'connecterror', 'readtimeout', 'connecttimeout', 'network is unreachable',
        'name resolution', 'timed out'))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--claude-dir', type=Path, required=True)
    p.add_argument('--dataset', type=Path, default=Path('PMo_ready'))
    p.add_argument('--max-tokens', type=int, default=16000)
    p.add_argument('--dry-run', action='store_true', help='List actions without API calls.')
    p.add_argument('--retry-incomplete', action='store_true',
                   help='Make a new paid request for an existing incomplete recovery. Previous files are backed up.')
    p.add_argument('--max-retries', type=int, default=2, help='Extra retries after a network error.')
    p.add_argument('--timeout', type=int, default=600)
    args = p.parse_args()
    if args.max_tokens <= 0 or args.max_retries < 0 or args.timeout < 30:
        p.error('Invalid max-tokens, max-retries or timeout.')
    root = args.claude_dir.resolve()
    script = root / 'agent.py'
    python = root / '.venv' / 'Scripts' / 'python.exe'
    if not python.is_file():
        python = root.parent / '.venv' / 'Scripts' / 'python.exe'
    if not script.is_file() or not python.is_file():
        p.error('Claude agent.py or its virtual environment Python was not found.')
    if not args.dry_run and not (root / '.env').is_file():
        p.error('Claude .env is missing.')
    dataset = args.dataset.resolve()
    out = root / 'recovery_16000'
    journal = Path('claude_recovery_16000_runs.jsonl').resolve()
    summary = {'skipped_valid': 0, 'skipped_incomplete': 0, 'planned': 0,
               'success': 0, 'incomplete': 0, 'error': 0}
    for number in MISSING:
        desc = dataset / 'descriptions' / f'{number:02d}.txt'
        if not desc.is_file():
            p.error(f'Missing input description: {desc}')
        case = out / f'{number:02d}' / 'claude'
        if completed(case):
            print(f'PMo {number:02d}: SKIP (complete, valid XML already saved)', flush=True)
            summary['skipped_valid'] += 1
            continue
        if case.exists() and any(case.iterdir()) and not args.retry_incomplete:
            print(f'PMo {number:02d}: SKIP (existing incomplete recovery; use --retry-incomplete to repeat)', flush=True)
            summary['skipped_incomplete'] += 1
            continue
        cmd = [str(python.resolve()), str(script), '--input', str(desc),
               '--output', str(out), '--max-tokens', str(args.max_tokens)]
        if args.dry_run:
            print(f'PMo {number:02d}: WOULD RUN (max_tokens={args.max_tokens})', flush=True)
            summary['planned'] += 1
            continue
        if case.exists() and any(case.iterdir()):
            import shutil
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            archived = case.with_name(f'{case.name}_incomplete_{stamp}')
            shutil.move(str(case), str(archived))
            print(f'  Preserved incomplete recovery: {archived}', flush=True)
        for attempt in range(1, args.max_retries + 2):
            print(f'PMo {number:02d}: attempt {attempt}', flush=True)
            started = time.monotonic()
            try:
                result = subprocess.run(cmd, cwd=root, capture_output=True,
                    text=True, errors='replace', timeout=args.timeout, check=False)
                details = result.stdout + '\n' + result.stderr
                network = connection_problem(details)
                kind = ('complete' if completed(case) else
                        ('incomplete' if result.returncode == 0 else 'error'))
                exit_code = result.returncode
            except subprocess.TimeoutExpired:
                details = 'Subprocess timeout'
                network = True
                kind = 'error'
                exit_code = None
            append_record(journal, {'process_id': f'{number:02d}', 'status': kind,
                'attempt': attempt, 'max_tokens': args.max_tokens, 'exit_code': exit_code,
                'elapsed_seconds': round(time.monotonic() - started, 2),
                'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                'message_tail': details[-1600:]})
            print(f'  {kind.upper()}', flush=True)
            if kind == 'complete':
                summary['success'] += 1
                break
            if network and attempt <= args.max_retries:
                print('  Connection/timeout issue; retrying in 10 seconds...', flush=True)
                time.sleep(10)
                continue
            summary[kind] += 1
            if network:
                print('STOP: connection failure. Check internet and rerun this command.', flush=True)
                print('Summary:', summary, flush=True)
                return
            break
    print('Done. Summary:', summary, flush=True)
    print(f'Recoveries: {out}', flush=True)
    print('Original 8192-token baseline outputs and journal are unchanged.', flush=True)

if __name__ == '__main__':
    main()
