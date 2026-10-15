"""Reproducible local-only demonstration using the real simulator/gateway CLIs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from coldshield import __version__
from coldshield.config import default_policy, load_policy
from coldshield.limits import CLIENT_TIMEOUT
from coldshield.protocol import Frame, exchange, read_request, write_frame
from coldshield.storage import AuditStore, atomic_json


def stamp():
    return datetime.now(timezone.utc).isoformat()


def claim_output(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(path.iterdir()):
        raise ValueError('Demo output directory must be empty; choose a new directory')
    path.chmod(0o700)
    return path


def reserved_port():
    sock = socket.socket()
    try:
        sock.bind(('127.0.0.1', 0))
    except BaseException:
        sock.close()
        raise
    return sock


def audit_for_transaction(path, tid):
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(
            'SELECT * FROM events WHERE transaction_id=? ORDER BY id', (tid,))]
    finally:
        db.close()


def run_demo(output_dir, timeout=45):
    """Returns a measured report; exceptions and forced child cleanup mean failure."""
    output = claim_output(output_dir)
    if type(timeout) not in (int, float) or not 10 <= timeout <= 120:
        raise ValueError('Demo timeout must be 10..120 seconds')
    deadline = time.monotonic() + timeout
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    report = {'schema_version': 1, 'timestamp_utc': stamp(), 'code_version': __version__,
              'revision': revision, 'scope': 'synthetic loopback laboratory, 127.0.0.1 only',
              'commands': [], 'processes': [], 'errors': [], 'successful': False}
    children, handles, reservations = [], [], []
    policy = output / 'policy.json'
    runtime = output / 'runtime'
    runtime.mkdir(mode=0o700)
    audit_path = runtime / 'audit.sqlite3'
    atomic_json(policy, default_policy())
    next_tid = 100

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError('Overall demo deadline exceeded')
        return seconds

    def record(command, **fields):
        entry = {'timestamp_utc': stamp(), 'code_version': __version__, 'revision': revision,
                 'command': command, 'transaction_id': None, 'request_id': None,
                 'decision': None, 'reason': None, 'result': None, **fields}
        report['commands'].append(entry)
        return entry

    def local_command(arguments, action, *, cleanup=False):
        entry = record('python -m coldshield.maintenance ' + action)
        result = subprocess.run([sys.executable, '-m', 'coldshield.maintenance', *arguments,
                                 '--policy', str(policy)], cwd=ROOT, capture_output=True,
                                text=True, timeout=5 if cleanup else min(5, remaining()))
        entry.update(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
                     result='PASSED' if result.returncode == 0 else 'FAILED')
        if result.returncode:
            raise AssertionError(f'Maintenance {action} failed: {result.stderr}')
        state = load_policy(policy)
        if state.maintenance_open() != (action == 'open'):
            entry['result'] = 'FAILED'
            raise AssertionError(f'Maintenance {action} did not produce expected policy state')
        entry.update(decision='OPEN' if action == 'open' else 'CLOSED', reason='POLICY_STATE_VERIFIED')

    def start_child(name, arguments, reservation):
        log_path = output / f'{name}.log'
        handle = log_path.open('wb')
        handles.append(handle)
        port = reservation.getsockname()[1]
        reservation.close()
        process = subprocess.Popen([sys.executable, *arguments], cwd=ROOT,
                                   stdout=handle, stderr=subprocess.STDOUT)
        children.append((name, process))
        report['processes'].append({'name': name, 'pid': process.pid, 'port': port,
                                    'host': '127.0.0.1', 'log': log_path.name,
                                    'timestamp_utc': stamp(), 'code_version': __version__,
                                    'revision': revision,
                                    'command': ['python', *(argument.replace(str(output), '<output>')
                                                           for argument in arguments)]})
        while True:
            remaining()
            if process.poll() is not None:
                raise RuntimeError(f'{name} exited during startup ({process.returncode})')
            if f'127.0.0.1:{port}' in log_path.read_text(errors='replace'):
                return port
            time.sleep(0.02)

    def request(label, frame, expected_status, expected_reason, expected_values=None):
        entry = record(label, transaction_id=frame.transaction_id,
                       function=frame.function, request_hex=frame.encode().hex())
        try:
            response = exchange(gateway_port, frame, timeout=min(CLIENT_TIMEOUT, remaining()))
            if response.function & 0x80:
                status = 'DENIED' if response.pdu[1] in (1, 2, 3) else 'UNKNOWN'
            else:
                status = 'ACKNOWLEDGED'
            events = audit_for_transaction(audit_path, frame.transaction_id)
            ids = {event['request_id'] for event in events}
            if len(ids) != 1:
                raise AssertionError(f'{label}: missing or ambiguous audit correlation')
            event = events[-1]
            entry.update(status=status, request_id=event['request_id'], decision=event['decision'],
                         reason=event['reason'], audit_event_ids=[item['id'] for item in events],
                         response_hex=response.encode().hex(), result='FAILED')
            if status != expected_status or event['reason'] != expected_reason:
                raise AssertionError(f"{label}: expected {expected_status}/{expected_reason}, got {status}/{event['reason']}")
            expected_decision = 'BLOCKED' if expected_status == 'DENIED' else 'ACKNOWLEDGED'
            if event['decision'] != expected_decision:
                raise AssertionError(f'{label}: audit decision mismatch')
            if expected_values is not None:
                actual = list(struct.unpack(f'>{len(expected_values)}h', response.pdu[2:]))
                entry['register_values'] = actual
                if actual != expected_values:
                    raise AssertionError(f'{label}: state mismatch {actual} != {expected_values}')
            entry['result'] = 'PASSED'
        except Exception as exc:
            entry.update(result='FAILED', error=str(exc))
            raise

    def tid():
        nonlocal next_tid
        next_tid += 1
        return next_tid

    try:
        if __version__ != '0.2.1':
            raise AssertionError(f'Expected code version 0.2.1, got {__version__}')
        sim_reservation = reserved_port()
        reservations.append(sim_reservation)
        gateway_reservation = reserved_port()
        reservations.append(gateway_reservation)
        simulator_port = sim_reservation.getsockname()[1]
        gateway_port = gateway_reservation.getsockname()[1]
        start_child('simulator', ['danfoss_sim.py', '--port', str(simulator_port),
                                 '--runtime-dir', str(runtime)], sim_reservation)
        start_child('gateway', ['x_coldshield_proxy.py', '--port', str(gateway_port),
                               '--upstream-port', str(simulator_port), '--policy', str(policy),
                               '--runtime-dir', str(runtime)], gateway_reservation)
        request('CLOSED: legitimate setpoint -22', write_frame(0, -22, tid()),
                'DENIED', 'MAINTENANCE_CLOSED')
        request('CLOSED: verify unchanged temperature', read_request(0, 1, tid()),
                'ACKNOWLEDGED', 'VALIDATED_RESPONSE', [-20])
        local_command(['open', '--seconds', '300'], 'open')
        request('OPEN: legitimate setpoint -22', write_frame(0, -22, tid()),
                'ACKNOWLEDGED', 'VALIDATED_RESPONSE')
        request('OPEN: verify legitimate temperature', read_request(0, 1, tid()),
                'ACKNOWLEDGED', 'VALIDATED_RESPONSE', [-22])
        request('OPEN: unsafe setpoint +50', write_frame(0, 50, tid()), 'DENIED', 'THERMAL_LIMIT')
        request('OPEN: verify blocked temperature', read_request(0, 1, tid()),
                'ACKNOWLEDGED', 'VALIDATED_RESPONSE', [-22])
        request('OPEN: defrost register 10 ON', write_frame(10, 1, tid()),
                'ACKNOWLEDGED', 'VALIDATED_RESPONSE')
        request('OPEN: defrost register 11 ON', write_frame(11, 1, tid()),
                'DENIED', 'DEFROST_INTERLOCK')
        request('OPEN: verify defrost state', read_request(10, 3, tid()),
                'ACKNOWLEDGED', 'VALIDATED_RESPONSE', [1, 0, 0])
        request('OPEN: unsupported FC16', Frame(tid(), 1, bytes.fromhex('1000000001020032')),
                'DENIED', 'FUNCTION_NOT_ALLOWED')
        request('OPEN: unsupported register 999', write_frame(999, -22, tid()),
                'DENIED', 'REGISTER_NOT_ALLOWED')
    except Exception:
        report['errors'].append(traceback.format_exc().replace(str(ROOT), '<repository>').replace(str(output), '<output>'))
    finally:
        try:
            # The private policy is closed even if its child services failed.
            local_command(['close'], 'close', cleanup=True)
            report['maintenance_closed'] = not load_policy(policy).maintenance_open()
        except Exception:
            report['maintenance_closed'] = False
            report['errors'].append(traceback.format_exc().replace(str(output), '<output>'))
        for reservation in reservations:
            reservation.close()
        for name, process in reversed(children):
            item = next(entry for entry in report['processes'] if entry['pid'] == process.pid)
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    item['forced_termination'] = True
                    report['errors'].append(f'{name} did not stop within controlled shutdown budget')
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
            item.update(exit_code=process.returncode, stopped=process.poll() is not None)
            if process.returncode != 0:
                report['errors'].append(f'{name} exited with {process.returncode}')
        for handle in handles:
            handle.close()
        try:
            if not audit_path.is_file():
                raise AssertionError('Demo audit database missing')
            export_path = output / 'audit-export.json'
            AuditStore(audit_path).export(export_path)
            report['audit_export'] = export_path.name
        except Exception:
            report['errors'].append(traceback.format_exc().replace(str(output), '<output>'))
        report['completed_utc'] = stamp()
        report['successful'] = bool(not report['errors'] and report.get('maintenance_closed') and
                                    len(report['processes']) == 2 and
                                    len(report['commands']) == 13 and
                                    all(item['result'] == 'PASSED' for item in report['commands']) and
                                    all(item['stopped'] for item in report['processes']))
        report['result'] = 'PASSED' if report['successful'] else 'FAILED'
        report['artifacts'] = {path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in sorted(output.rglob('*')) if path.is_file()}
        (output / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        lines = [f"# X ColdShield {__version__} local demonstration", '',
                 f"Result: {report['result']}", f"UTC: {report['timestamp_utc']}",
                 f"Revision: `{revision}`", '', report['scope'], '',
                 '| UTC | Command | Transaction | Decision | Reason | Result |',
                 '| --- | --- | --- | --- | --- | --- |']
        for entry in report['commands']:
            lines.append(f"| {entry['timestamp_utc']} | {entry['command']} | {entry['transaction_id']} | {entry['decision']} | {entry['reason']} | {entry['result']} |")
        lines.extend(['', f"Private maintenance policy closed: {report.get('maintenance_closed')}",
                      '', '## Processes', ''])
        for child in report['processes']:
            lines.append(f"- {child['name']}: stopped={child.get('stopped', False)}, "
                         f"exit={child.get('exit_code')}, forced={child.get('forced_termination', False)}")
        lines.extend(['', '## Errors', '', *(report['errors'] or ['None.'])])
        (output / 'report.md').write_text('\n'.join(lines) + '\n')
        manifest = {path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(output.rglob('*')) if path.is_file()}
        (output / 'manifest.json').write_text(json.dumps({'algorithm': 'sha256', 'files': manifest}, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'runtime/demo-run')
    parser.add_argument('--timeout', type=float, default=45)
    args = parser.parse_args()
    try:
        report = run_demo(args.output_dir, args.timeout)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Demo rejected: {exc}\n')
    print(f"Local demo: {report['result']}; {args.output_dir / 'report.json'}")
    return 0 if report['successful'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
