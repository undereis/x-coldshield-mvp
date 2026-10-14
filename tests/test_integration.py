"""Real TCP exchanges on ephemeral loopback ports and isolated runtime files."""
from contextlib import contextmanager
from datetime import timedelta
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from coldshield.config import default_policy, utcnow
from coldshield.gateway import Gateway, make_gateway
from coldshield.maintenance import set_window
from coldshield.protocol import (Frame, exchange, read_frame, read_request, write_frame)
from coldshield.simulator import make_simulator
from coldshield.storage import AuditError, AuditStore, atomic_json, read_events


@contextmanager
def running(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class LabIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root / "policy.json"
        atomic_json(self.policy, default_policy())
        set_window(self.policy, 300)
        self.simulator = make_simulator(0, self.root / "sim", timeout=0.25)
        self.sim_port = self.enterContext(running(self.simulator))
        self.gateway = make_gateway(0, self.sim_port, self.policy, self.root / "gateway", timeout=0.25)
        self.port = self.enterContext(running(self.gateway))

    def send(self, register, value, tid=1):
        return exchange(self.port, write_frame(register, value, tid), timeout=1)

    def events(self):
        return read_events(self.root / "gateway" / "audit.sqlite3")

    def test_legitimate_write_and_signed_read(self):
        self.assertEqual(self.send(0, -22).pdu, write_frame(0, -22).pdu)
        result = exchange(self.port, read_request(0, 3))
        self.assertEqual(struct.unpack(">3h", result.pdu[2:]), (-22, -20, -18))

    def test_thermal_upper_and_lower_boundaries(self):
        for value in (-40, -15):
            self.assertEqual(self.send(0, value).function, 6)
        for value in (-41, -14, 50, 32767):
            self.assertEqual(self.send(0, value).pdu, b'\x86\x03')
        self.assertEqual(self.simulator.simulator.registers[0], -15)

    def test_closed_window_allows_read_denies_all_writes(self):
        set_window(self.policy)
        for register, value in ((0, -22), (10, 1), (10, 0)):
            self.assertEqual(self.send(register, value).pdu, b'\x86\x03')
        self.assertEqual(exchange(self.port, read_request(0, 3)).function, 3)

    def test_expired_window(self):
        data = default_policy()
        now = utcnow()
        data["maintenance"] = {"enabled": True, "starts_at": (now-timedelta(seconds=30)).isoformat(),
                               "expires_at": (now-timedelta(seconds=1)).isoformat()}
        atomic_json(self.policy, data)
        self.assertEqual(self.send(0, -22).pdu, b'\x86\x03')

    def test_missing_corrupt_legacy_and_weakened_policy(self):
        for contents in ('{', '{"maintenance_window_open":true,"max_temp":0}',
                         json.dumps({**default_policy(), "max_temp": 0})):
            self.policy.write_text(contents)
            self.assertEqual(self.send(0, -22).pdu, b'\x86\x04')
        self.policy.unlink()
        self.assertEqual(self.send(0, -22).pdu, b'\x86\x04')
        self.assertEqual(self.simulator.simulator.registers[0], -20)

    def test_unknown_functions_units_registers_and_read_ranges(self):
        for function in (1, 5, 15, 16, 23, 43, 128):
            result = exchange(self.port, Frame(1, 1, bytes((function,))+b'\x00'*4))
            self.assertEqual(result.pdu, bytes((function|128, 1)))
        self.assertEqual(self.send(3, -22).pdu, b'\x86\x02')
        self.assertEqual(exchange(self.port, Frame(1, 2, write_frame(0,-22).pdu)).pdu, b'\x86\x02')
        self.assertEqual(exchange(self.port, read_request(2, 9)).pdu, b'\x83\x02')
        self.assertEqual(exchange(self.port, read_request(0, 0)).pdu, b'\x83\x03')

    def test_wrong_pdu_length(self):
        for pdu in (b'\x06', b'\x06\x00\x00\x00', write_frame(0, -22).pdu+b'\x00'):
            self.assertEqual(exchange(self.port, Frame(1,1,pdu)).pdu, b'\x86\x03')

    def test_defrost_values_cascade_and_idempotence(self):
        self.assertEqual(self.send(10, 2).pdu, b'\x86\x03')
        self.assertEqual(self.send(10, -1).pdu, b'\x86\x03')
        self.assertEqual(self.send(10, 1).function, 6)
        self.assertEqual(self.send(10, 1).function, 6)
        self.assertEqual(self.send(11, 1).pdu, b'\x86\x03')
        self.assertEqual(self.send(10, 0).function, 6)
        self.assertEqual(self.send(11, 1).pdu, b'\x86\x03')  # Persistent cooldown still applies.

    def test_active_defrost_remains_blocked_after_cooldown(self):
        self.send(10, 1)
        with patch('coldshield.gateway.time.time', return_value=time.time()+121):
            self.assertEqual(self.send(11, 1).pdu, b'\x86\x03')
        self.assertEqual(self.simulator.simulator.registers[11], 0)

    def test_restart_persists_cooldown_and_reconciles_direct_state(self):
        self.send(10, 1)
        self.send(10, 0)
        replacement = Gateway(self.policy, AuditStore(self.root/'gateway'/'audit.sqlite3'), self.sim_port, .25)
        self.assertEqual(replacement.process(write_frame(11,1)).pdu, b'\x86\x03')
        exchange(self.sim_port, write_frame(12,1))
        with patch('coldshield.gateway.time.time', return_value=time.time()+121):
            self.assertEqual(replacement.process(write_frame(11,1)).pdu, b'\x86\x03')

    def test_valid_shutdown_and_new_start_after_cooldown(self):
        self.send(10,1)
        self.send(10,0)
        with patch('coldshield.gateway.time.time', return_value=time.time()+121):
            self.assertEqual(self.send(11,1).function, 6)

    def test_grouped_frames_each_inspected(self):
        with socket.create_connection(("127.0.0.1",self.port)) as sock:
            sock.sendall(write_frame(0,-22,1).encode()+write_frame(1,50,2).encode())
            self.assertEqual(read_frame(sock).function,6)
            result=read_frame(sock)
            self.assertEqual(result.transaction_id,2)
            self.assertEqual(result.pdu,b'\x86\x03')
        self.assertEqual(self.simulator.simulator.registers[1],-20)

    def test_fragmented_header_and_body(self):
        with socket.create_connection(("127.0.0.1",self.port)) as sock:
            packet=write_frame(0,-22).encode()
            for start,end in ((0,2),(2,7),(7,9),(9,12)):
                sock.sendall(packet[start:end])
                time.sleep(.005)
            self.assertEqual(read_frame(sock).function,6)

    def test_partial_frame_closed_and_audited(self):
        with socket.create_connection(("127.0.0.1",self.port)) as sock:
            sock.sendall(write_frame(0,50).encode()[:9])
            sock.shutdown(socket.SHUT_WR)
            self.assertEqual(sock.recv(1),b'')
        self.assertTrue(any(e['reason']=='INVALID_FRAME' for e in self.events()))
        self.assertEqual(self.simulator.simulator.registers[0],-20)

    def test_invalid_header_closed(self):
        for protocol,length in ((1,6),(0,1),(0,255),(0,65535)):
            with socket.create_connection(("127.0.0.1",self.port)) as sock:
                sock.sendall(struct.pack('>HHHB',1,protocol,length,1))
                self.assertEqual(sock.recv(1),b'')

    def test_idle_client_does_not_stall_another(self):
        with socket.create_connection(("127.0.0.1",self.port)) as idle:
            self.assertEqual(self.send(0,-22).function,6)
            idle.settimeout(1)
            self.assertEqual(idle.recv(1),b'')

    def test_upstream_unavailable_is_failed_not_acknowledged(self):
        with socket.socket() as unused:
            unused.bind(('127.0.0.1',0))
            unavailable_port=unused.getsockname()[1]
        self.gateway.gateway.upstream_port=unavailable_port
        self.assertEqual(self.send(0,-22).pdu,b'\x86\x0b')
        self.assertEqual([e['decision'] for e in self.events()], ['FAILED','AUTHORIZED'])
        self.assertEqual(self.simulator.simulator.registers[0],-20)

    def test_audit_failure_prevents_forwarding(self):
        with patch.object(self.gateway.gateway.audit,'record',side_effect=AuditError('disk unavailable')):
            with self.assertLogs('coldshield.gateway',level='ERROR'):
                self.assertEqual(self.send(0,-22).pdu,b'\x86\x04')
        self.assertEqual(self.simulator.simulator.registers[0],-20)

    def test_post_delivery_audit_failure_reports_uncertainty(self):
        original=self.gateway.gateway.audit.record
        def record(*args,**kwargs):
            if args[1]=='outcome':
                raise AuditError('outcome disk failure')
            return original(*args,**kwargs)
        with patch.object(self.gateway.gateway.audit,'record',side_effect=record):
            with self.assertLogs('coldshield.gateway',level='ERROR'):
                self.assertEqual(self.send(0,-22).pdu,b'\x86\x04')
        self.assertEqual(self.simulator.simulator.registers[0],-22)
        self.assertEqual(self.events()[0]['phase'],'decision')

    def test_audit_correlation_reason_and_policy_hash(self):
        self.send(0,-22,17)
        events=self.events()
        self.assertEqual(len(events),2)
        self.assertEqual(events[0]['request_id'],events[1]['request_id'])
        self.assertEqual(events[0]['decision'],'ACKNOWLEDGED')
        for event in events:
            self.assertEqual(event['transaction_id'],17)
            self.assertEqual(event['register'],0)
            self.assertEqual(event['value'],-22)
            self.assertEqual(len(event['policy_hash']),64)
            self.assertIn('+00:00',event['timestamp'])

    def test_defrost_requests_serialized_across_clients(self):
        gate=threading.Barrier(3)
        replies=[]
        def worker(register):
            gate.wait()
            replies.append(self.send(register,1))
        workers=[threading.Thread(target=worker,args=(register,)) for register in (10,11)]
        for worker in workers: worker.start()
        gate.wait()
        for worker in workers: worker.join(timeout=2)
        self.assertEqual(sorted(reply.function for reply in replies),[6,134])
        self.assertEqual(sum(self.simulator.simulator.registers[i] for i in (10,11,12)),1)

    def test_same_runtime_rejects_second_gateway(self):
        with self.assertRaises(BlockingIOError):
            make_gateway(0,self.sim_port,self.policy,self.root/'gateway')

    def test_direct_simulator_bypass_remains_explicit_lab_demo(self):
        self.assertEqual(exchange(self.sim_port,write_frame(0,50)).function,6)
        self.assertEqual(self.simulator.simulator.registers[0],50)
        self.assertEqual(self.send(0,50).pdu,b'\x86\x03')


class MaintenanceStorageTests(unittest.TestCase):
    def test_invalid_lease_never_changes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'policy.json'
            atomic_json(path,default_policy())
            original=path.read_bytes()
            for seconds in (0,901,True):
                with self.assertRaises(ValueError): set_window(path,seconds)
                self.assertEqual(path.read_bytes(),original)

    def test_atomic_snapshot_failure_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'
            atomic_json(path,{'old':1})
            with patch('coldshield.storage.os.replace',side_effect=OSError('fault')):
                with self.assertRaises(OSError): atomic_json(path,{'new':2})
            self.assertEqual(json.loads(path.read_text()),{'old':1})
            self.assertEqual(list(Path(tmp).iterdir()),[path])

    def test_more_than_fifty_events_survive_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'audit.sqlite3'
            audit=AuditStore(path)
            for index in range(65): audit.record(str(index),'decision','BLOCKED','TEST')
            AuditStore(path)
            self.assertEqual(len(read_events(path)),65)


if __name__=='__main__':
    unittest.main()
