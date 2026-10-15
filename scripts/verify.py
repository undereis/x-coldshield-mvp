"""Run the exact unittest inventory and persist measured, reproducible evidence."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.agents', '.claude', '.codex', 'runtime', 'docs', '__pycache__',
            '.pytest_cache', 'node_modules', 'build', 'dist'}


def source_manifest(root):
    """Hash source/configuration recursively; paths are always repository relative."""
    root = Path(root)
    files = {}
    paths = []
    for directory, subdirectories, names in os.walk(root):
        subdirectories[:] = sorted(name for name in subdirectories
                                   if name not in EXCLUDED and not name.startswith('.venv'))
        paths.extend(Path(directory) / name for name in names)
    for path in sorted(paths):
        relative = path.relative_to(root)
        included = (path.suffix in {'.py', '.toml', '.cfg', '.ini', '.lock', '.yml', '.yaml'} or
                    (relative.parts[0] in {'coldshield', 'tests', 'scripts'} and
                     path.suffix in {'.json', '.sh'}) or
                    relative.as_posix().startswith('.github/workflows/') or
                    path.name in {'requirements.txt', 'policy_config.json', '.gitignore',
                                  'expected_inventory.json', 'Dockerfile'})
        if included:
            files[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    canonical = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    return {'files': files, 'sha256': hashlib.sha256(canonical).hexdigest()}


def git_state(root):
    def command(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True,
                                       stderr=subprocess.STDOUT).rstrip('\n')
    status = command('status', '--porcelain=v1', '--untracked-files=all')
    return {'commit': command('rev-parse', 'HEAD'),
            'branch': command('symbolic-ref', '--quiet', '--short', 'HEAD')
            if subprocess.run(['git', 'symbolic-ref', '--quiet', 'HEAD'], cwd=root,
                              capture_output=True).returncode == 0 else '(detached)',
            'dirty': bool(status), 'status': status.splitlines()}


def test_ids(suite):
    if isinstance(suite, unittest.TestSuite):
        return [item for child in suite for item in test_ids(child)]
    return [suite.id()]


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed_ids = []

    def startTest(self, test):
        self.executed_ids.append(test.id())
        super().startTest(test)


def run_verification(root, output_dir, expected_path=None, loader=None, *, require_clean=False):
    """Always produce evidence, including discovery/collection failures. Dirty is recorded."""
    root, output_dir = Path(root).resolve(), Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise ValueError('Evidence output directory must be empty; select a new run directory')
    expected_path = Path(expected_path) if expected_path else root / 'tests/expected_inventory.json'
    stream = io.StringIO()
    start = time.monotonic()
    evidence = {'schema_version': 1, 'run_date_utc': datetime.now(timezone.utc).isoformat(),
                'command': 'python scripts/verify.py',
                'python': platform.python_version(), 'platform': f'{platform.system()} {platform.machine()}',
                'environment': {'implementation': platform.python_implementation(),
                                'executable_name': Path(sys.executable).name,
                                'ci': bool(os.environ.get('CI')),
                                'packages': {}},
                'expected_inventory_path': str(expected_path.relative_to(root))
                if expected_path.is_relative_to(root) else '<external inventory>',
                'discovered_test_ids': [], 'executed_test_ids': [], 'expected_test_ids': [],
                'tests_run': 0, 'failures': 0, 'errors': 0, 'skipped': 0,
                'failure_details': [], 'error_details': [], 'skip_details': [],
                'collection_errors': [], 'validation_errors': [], 'successful': False}
    evidence['require_clean'] = require_clean
    result = None
    try:
        # These snapshots precede expected-inventory reading and discovery/import.
        evidence['git_before'] = git_state(root)
        evidence['source_before'] = source_manifest(root)
        if require_clean and evidence['git_before']['dirty']:
            evidence['validation_errors'].append('A clean Git worktree is required for this run')
        for package in ('streamlit', 'pandas', 'plotly'):
            try:
                evidence['environment']['packages'][package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                evidence['environment']['packages'][package] = None
        expected = json.loads(expected_path.read_text())
        if not isinstance(expected, list) or any(not isinstance(item, str) for item in expected):
            raise ValueError('Expected inventory must be a JSON list of exact test IDs')
        evidence['expected_test_ids'] = sorted(expected)
        if not expected or len(set(expected)) != len(expected):
            evidence['validation_errors'].append('Expected inventory is empty or has duplicate IDs')
        with redirect_stdout(stream), redirect_stderr(stream):
            active_loader = loader if loader is not None else unittest.TestLoader()
            suite = active_loader.discover(str(root / 'tests'))
            discovered = test_ids(suite)
            evidence['discovered_test_ids'] = sorted(discovered)
            evidence['collection_errors'] = list(active_loader.errors)
            if not discovered or len(discovered) != len(set(discovered)):
                evidence['validation_errors'].append('Discovery is empty or has duplicate IDs')
            if sorted(discovered) != sorted(expected):
                evidence['validation_errors'].append('Discovered inventory differs from explicit expected inventory')
            if active_loader.errors:
                evidence['validation_errors'].append('Test collection reported errors')
            result = unittest.TextTestRunner(stream=stream, verbosity=2,
                                             resultclass=EvidenceResult).run(suite)
        evidence.update(tests_run=result.testsRun, failures=len(result.failures),
                        errors=len(result.errors), skipped=len(result.skipped),
                        executed_test_ids=result.executed_ids,
                        failure_details=[{'test_id': item.id(), 'traceback': trace} for item, trace in result.failures],
                        error_details=[{'test_id': item.id(), 'traceback': trace} for item, trace in result.errors],
                        skip_details=[{'test_id': item.id(), 'reason': reason} for item, reason in result.skipped])
        if result.skipped:
            evidence['validation_errors'].append('Unexpected skipped test(s)')
        if result.testsRun != len(discovered) or sorted(result.executed_ids) != sorted(expected):
            evidence['validation_errors'].append('Executed inventory/count differs from discovery or expected inventory')
    except BaseException:
        trace = traceback.format_exc().replace(str(root), '<repository>')
        evidence['collection_errors'].append(trace)
        evidence['validation_errors'].append('Verification setup, discovery, or execution raised an exception')
        stream.write(trace)
    finally:
        try:
            evidence['source_after'] = source_manifest(root)
            evidence['source_unchanged'] = evidence.get('source_before') == evidence['source_after']
            if not evidence['source_unchanged']:
                evidence['validation_errors'].append('Source manifest changed during verification')
            evidence['git_after'] = git_state(root)
            if evidence.get('git_before', {}).get('commit') != evidence['git_after']['commit']:
                evidence['validation_errors'].append('Git revision changed during verification')
            if evidence.get('git_before', {}).get('branch') != evidence['git_after']['branch']:
                evidence['validation_errors'].append('Git branch changed during verification')
            if evidence.get('git_before', {}).get('status') != evidence['git_after']['status']:
                evidence['validation_errors'].append('Git worktree status changed during verification')
        except Exception:
            evidence['validation_errors'].append('Post-run source/Git snapshot failed')
            stream.write(traceback.format_exc())
        evidence['elapsed_seconds'] = round(time.monotonic() - start, 6)
        evidence['successful'] = bool(result and result.wasSuccessful() and not evidence['validation_errors']
                                      and not evidence['collection_errors'])
        evidence['result'] = 'PASSED' if evidence['successful'] else 'FAILED'
        transcript = stream.getvalue().replace(str(root), '<repository>')
        encoded = transcript.encode('utf-8')
        evidence['transcript_sha256'] = hashlib.sha256(encoded).hexdigest()
        for key in ('collection_errors', 'failure_details', 'error_details'):
            evidence[key] = json.loads(json.dumps(evidence[key]).replace(str(root), '<repository>'))
        (output_dir / 'transcript.txt').write_bytes(encoded)
        (output_dir / 'evidence.json').write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'runtime/verification' /
                        f'python{sys.version_info.major}{sys.version_info.minor}')
    parser.add_argument('--expected-inventory', type=Path, default=ROOT / 'tests/expected_inventory.json')
    parser.add_argument('--require-clean', action='store_true', default=bool(os.environ.get('CI')),
                        help='Reject a dirty worktree (enabled automatically in CI)')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    try:
        evidence = run_verification(ROOT, args.output_dir, args.expected_inventory,
                                    require_clean=args.require_clean)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Verification output rejected: {exc}\n')
    print((args.output_dir / 'transcript.txt').read_text(), end='')
    print(f"Evidence: {evidence['result']} ({evidence['tests_run']} tests); {args.output_dir}")
    for error in evidence['validation_errors']:
        print(error)
    return 0 if evidence['successful'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
