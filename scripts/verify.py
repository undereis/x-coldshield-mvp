"""Run the full local unittest suite and save measured evidence (no real devices)."""
import hashlib
import io
import json
import platform
from pathlib import Path
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    output = ROOT / 'docs' / f'test-results-python{sys.version_info.major}{sys.version_info.minor}'
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    start = time.monotonic()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    elapsed = time.monotonic() - start
    transcript = stream.getvalue().replace(str(ROOT), '<repository>')
    print(transcript, end='')
    paths = sorted([*ROOT.glob('*.py'), *ROOT.glob('coldshield/*.py'),
                    *ROOT.glob('tests/*.py'), *ROOT.glob('scripts/*.py'),
                    ROOT / 'requirements.txt', ROOT / 'requirements.lock', ROOT / 'policy_config.json',
                    ROOT / '.github/workflows/tests.yml'])
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode() + b'\0' + path.read_bytes() + b'\0')
    try:
        import streamlit
        version = streamlit.__version__
    except ImportError:
        version = None
    evidence = {
        'run_date_utc': datetime.now(timezone.utc).isoformat(),
        'command': f'python{sys.version_info.major}.{sys.version_info.minor} scripts/verify.py',
        'python': platform.python_version(), 'platform': f'{platform.system()} {platform.machine()}',
        'streamlit': version,
        'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_tree_sha256': digest.hexdigest(),
        'tests_run': result.testsRun, 'failures': len(result.failures),
        'errors': len(result.errors), 'skipped': len(result.skipped),
        'successful': result.wasSuccessful(), 'elapsed_seconds': round(elapsed, 6),
        'scope': 'loopback TCP, socketpair, isolated temporary files, mocked faults, headless Streamlit AppTest',
    }
    output.with_suffix('.txt').write_text(transcript)
    output.with_suffix('.json').write_text(json.dumps(evidence, indent=2) + '\n')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
