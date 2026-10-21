"""Run existing OpenAI/Claude agents on identical PMo descriptions, with safe resume.

Only generation is performed; no BPMN quality judgments or silent repairs.
The previous batch_runs.jsonl remains append-only.
"""
import argparse
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def agent_python(root: Path) -> Path:
    for path in (
        root / '.venv' / 'Scripts' / 'python.exe',
        root.parent / '.venv' / 'Scripts' / 'python.exe',
        root / '.venv' / 'bin' / 'python',
        root.parent / '.venv' / 'bin' / 'python',
    ):
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(f'Missing .venv for {root} (in folder or parent).')


def load_journal(path: Path):
    """Use the latest record per (agent, process, repeat); skip broken lines."""
    latest = {}
    if path.exists():
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                key = (row['agent'], str(row['id']).zfill(2), int(row['repeat']))
                latest[key] = row
            except (ValueError, KeyError, TypeError):
                print(f'WARNING: Ignoring unreadable journal line {lineno}.')
    return latest


def saved_files(output: Path, process_id: int, provider: str):
    """Agents nest files at output/<source-file-stem>/<provider>/."""
    folder = output / f'{process_id:02d}' / provider
    return folder / 'initial_raw.txt', folder / 'metadata.json'


def has_saved_response(output: Path, process_id: int, provider: str) -> bool:
    """Generation success is a saved API response; invalid BPMN still counts."""
    raw, meta = saved_files(output, process_id, provider)
    if not (raw.is_file() and meta.is_file() and raw.stat().st_size > 0):
        return False
    try:
        data = json.loads(meta.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return False
    # A response with an ID is real generated output; don't require BPMN validity.
    return bool(data.get('response_id') or data.get('model_returned') or data.get('model_requested'))


def is_connection_error(stderr: str, stdout: str) -> bool:
    text = (stderr + '\n' + stdout).lower()
    return any(term in text for term in (
        'apiconnectionerror', 'connection error', 'connecterror', 'connecttimeout',
        'readtimeout', 'temporary failure in name resolution',
        'name or service not known', 'network is unreachable',
    ))


def archive_partial_output(output: Path) -> None:
    """Retain failed/partial output instead of overwriting on retry."""
    if not output.exists():
        return
    if not any(output.iterdir()):
        return
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = output.with_name(f'{output.name}_interrupted_{stamp}')
    shutil.move(str(output), str(backup))
    print(f'  Preserved previous incomplete output: {backup}', flush=True)


def append_journal(path: Path, result: dict) -> None:
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(result, ensure_ascii=False) + '\n')
        f.flush()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset', type=Path, default=Path('PMo_ready'))
    p.add_argument('--agent', choices=['openai', 'claude', 'both'], required=True)
    p.add_argument('--openai-dir', type=Path)
    p.add_argument('--claude-dir', type=Path)
    p.add_argument('--start', type=int, default=1)
    p.add_argument('--end', type=int, default=55)
    p.add_argument('--repeats', type=int, default=1)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--resume', action='store_true', help='Skip previously completed generations and retry missing/failed runs.')
    p.add_argument('--max-retries', type=int, default=2, help='Extra attempts for a connection failure (default: 2).')
    p.add_argument('--retry-delay', type=float, default=8, help='Seconds between connection retries (default: 8).')
    p.add_argument('--stop-after-connection-errors', type=int, default=3,
                   help='Stop the batch after this many consecutive connection failures (default: 3).')
    args = p.parse_args()
    if not 1 <= args.start <= args.end <= 55:
        p.error('Invalid ID range (1 to 55).')
    if args.repeats < 1 or args.max_retries < 0 or args.retry_delay < 0 or args.stop_after_connection_errors < 1:
        p.error('Invalid repetitions/retry settings.')
    manifest = args.dataset / 'manifest.json'
    if not manifest.is_file() or json.loads(manifest.read_text(encoding='utf-8')).get('count') != 55:
        p.error('Prepare PMo_ready with 55 descriptions first.')

    requested = []
    if args.agent in ('openai', 'both'):
        requested.append(('openai', args.openai_dir))
    if args.agent in ('claude', 'both'):
        requested.append(('claude', args.claude_dir))
    agents = []
    for name, root in requested:
        if root is None:
            p.error(f'--{name}-dir is required.')
        root = root.resolve()
        script = root / 'agent.py'
        if not script.is_file():
            p.error(f'Missing agent script: {script}')
        if not args.dry_run and not (root / '.env').is_file():
            p.error(f'Missing local API configuration: {root / ".env"}')
        try:
            python = agent_python(root)
        except FileNotFoundError as error:
            p.error(str(error))
        agents.append((name, root, script, python))

    journal = Path('batch_runs.jsonl')
    latest = load_journal(journal)
    counts = {'skipped': 0, 'success': 0, 'error': 0, 'planned': 0}
    consecutive_connection_failures = 0

    for repeat in range(1, args.repeats + 1):
        for number in range(args.start, args.end + 1):
            desc = (args.dataset / 'descriptions' / f'{number:02d}.txt').resolve()
            if not desc.is_file():
                p.error(f'Missing description: {desc}')
            for name, root, script, python in agents:
                key = (name, f'{number:02d}', repeat)
                output = (Path.cwd() / 'batch_outputs' / f'repeat_{repeat:02d}' / name / f'pmo_{number:02d}').resolve()
                record = latest.get(key)
                saved = has_saved_response(output, number, name)
                # An orphan response after interruption also counts as completed.
                completed = saved and (record is None or record.get('status') == 'ok' or
                                       record.get('status') in ('error', 'timeout'))
                if args.resume and completed:
                    print(f'[{name}] PMo {number:02d}, repeat {repeat}: SKIP (saved response)', flush=True)
                    counts['skipped'] += 1
                    continue
                cmd = [str(python), str(script), '--input', str(desc), '--output', str(output)]
                if args.dry_run:
                    print(f'[{name}] PMo {number:02d}, repeat {repeat}: WOULD RUN', flush=True)
                    print('  ' + subprocess.list2cmdline(cmd), flush=True)
                    counts['planned'] += 1
                    continue
                archive_partial_output(output)
                for attempt in range(1, args.max_retries + 2):
                    print(f'[{name}] PMo {number:02d}, repeat {repeat}: attempt {attempt}', flush=True)
                    t0 = time.monotonic()
                    try:
                        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                                           errors='replace', timeout=240, check=False)
                        connection_error = is_connection_error(r.stderr, r.stdout)
                        status = 'ok' if r.returncode == 0 and has_saved_response(output, number, name) else 'error'
                        result = {
                            'agent': name, 'id': f'{number:02d}', 'repeat': repeat,
                            'status': status, 'exit_code': r.returncode,
                            'duration_seconds': round(time.monotonic() - t0, 2),
                            'output_dir': str(output), 'stdout_tail': r.stdout[-1200:],
                            'stderr_tail': r.stderr[-1200:], 'attempt': attempt,
                            'connection_error': connection_error,
                            'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                        }
                    except subprocess.TimeoutExpired:
                        connection_error = True
                        result = {
                            'agent': name, 'id': f'{number:02d}', 'repeat': repeat,
                            'status': 'timeout', 'output_dir': str(output), 'attempt': attempt,
                            'connection_error': True,
                            'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                        }
                    append_journal(journal, result)
                    latest[key] = result
                    print('  ' + result['status'], flush=True)
                    if result['status'] == 'ok':
                        counts['success'] += 1
                        consecutive_connection_failures = 0
                        break
                    if connection_error and attempt <= args.max_retries:
                        print(f'  Connection failure; retrying in {args.retry_delay:g} seconds...', flush=True)
                        time.sleep(args.retry_delay)
                        archive_partial_output(output)
                        continue
                    counts['error'] += 1
                    if connection_error:
                        consecutive_connection_failures += 1
                    else:
                        consecutive_connection_failures = 0
                    if consecutive_connection_failures >= args.stop_after_connection_errors:
                        print('STOPPING: repeated connection failures. Check internet and resume later.', flush=True)
                        print('Summary:', counts, flush=True)
                        return
                    break
    print('Done. Summary:', counts, flush=True)
    print('Generated outputs are not BPMN quality assessments.', flush=True)


if __name__ == '__main__':
    main()
