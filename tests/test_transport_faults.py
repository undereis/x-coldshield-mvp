"""Communication fault injection on ephemeral loopback-only TCP services."""
from pathlib import Path
import socket
import socketserver
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from coldshield.config import ConfigError, default_policy
from coldshield.gateway import make_gateway
from coldshield.maintenance import set_window
from coldshield.protocol import (Frame, exchange, exception_response, read_frame, write_frame)
from coldshield.server import LabServer
from coldshield.storage import atomic_json, read_events
from test_integration import running


class FaultHandler(socketserver.BaseRequestHandler):
    def handle(self):
        request=read_frame(self.request,.3)
        if self.server.fault=='timeout':
            time.sleep(.15)
            return
        if self.server.fault=='disconnect':
            return
        if self.server.fault=='wrong_transaction':
            reply=Frame(request.transaction_id+1,1,request.pdu)
        elif self.server.fault=='wrong_echo':
            reply=write_frame(0,50,request.transaction_id)
        elif self.server.fault=='exception':
            reply=exception_response(request,4)
        else:
            reply=Frame(request.transaction_id,1,b'\x03\x06\x00')
        self.request.sendall(reply.encode())


class TransportFaultTests(unittest.TestCase):
    def exercise(self,fault,defrost=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            policy=root/'policy.json'
            atomic_json(policy,default_policy())
            set_window(policy,300)
            server=LabServer(0,FaultHandler)
            server.fault=fault
            with running(server) as upstream:
                gateway=make_gateway(0,upstream,policy,root/'runtime',timeout=.05)
                with running(gateway) as port:
                    reply=exchange(port,write_frame(10 if defrost else 0,1 if defrost else -22),timeout=1)
                    events=read_events(root/'runtime'/'audit.sqlite3')
                    return reply,events

    def test_timeout(self):
        reply,events=self.exercise('timeout')
        self.assertEqual(reply.pdu,b'\x86\x0b')
        self.assertEqual(events[0]['reason'],'UPSTREAM_FAILURE')

    def test_disconnect_before_reply(self):
        reply,events=self.exercise('disconnect')
        self.assertEqual(reply.pdu,b'\x86\x0b')
        self.assertEqual(events[0]['decision'],'FAILED')

    def test_mismatched_transaction(self):
        reply,events=self.exercise('wrong_transaction')
        self.assertEqual(reply.pdu,b'\x86\x0b')
        self.assertEqual(events[0]['reason'],'UPSTREAM_FAILURE')

    def test_wrong_write_echo(self):
        reply,events=self.exercise('wrong_echo')
        self.assertEqual(reply.pdu,b'\x86\x0b')
        self.assertEqual(events[0]['decision'],'FAILED')

    def test_valid_device_exception_is_rejected_not_acknowledged(self):
        reply,events=self.exercise('exception')
        self.assertEqual(reply.pdu,b'\x86\x04')
        self.assertEqual(events[0]['decision'],'REJECTED')

    def test_malformed_defrost_response_prevents_start(self):
        reply,events=self.exercise('malformed',defrost=True)
        self.assertEqual(reply.pdu,b'\x86\x0b')
        self.assertEqual(events[0]['reason'],'DEFROST_STATE_UNAVAILABLE')

    def test_before_send_rechecks_policy_after_connect(self):
        # The protocol hook runs after connect but before send, even if the lease
        # was revoked while connection establishment blocked.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            policy=root/'policy.json'
            atomic_json(policy,default_policy())
            set_window(policy,300)
            gateway=make_gateway(0,5020,policy,root/'runtime')
            self.addCleanup(gateway.server_close)
            class FakeSocket:
                def __enter__(self): return self
                def __exit__(self,*args): pass
                def settimeout(self,*args): pass
                def sendall(self,*args): raise AssertionError('Revoked write reached send')
            def connect(*args,**kwargs):
                set_window(policy)
                return FakeSocket()
            with patch('coldshield.protocol.socket.create_connection',side_effect=connect):
                response=gateway.gateway.process(write_frame(0,-22))
            self.assertEqual(response.pdu,b'\x86\x03')
            self.assertEqual(read_events(root/'runtime'/'audit.sqlite3')[0]['reason'],'POLICY_CHANGED_OR_EXPIRED')

    def test_shutdown_retains_owner_lock_until_handler_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            policy=root/'policy.json'
            atomic_json(policy,default_policy())
            set_window(policy,300)
            gateway=make_gateway(0,5020,policy,root/'runtime',timeout=.1)
            serve=threading.Thread(target=gateway.serve_forever,kwargs={'poll_interval':.01})
            serve.start()
            entered=threading.Event()
            release=threading.Event()
            def stalled(*args,**kwargs):
                entered.set()
                release.wait(timeout=2)
                return args[1]
            try:
                with patch('coldshield.gateway.exchange',side_effect=stalled):
                    with socket.create_connection(gateway.server_address) as client:
                        client.sendall(write_frame(0,-22).encode())
                        self.assertTrue(entered.wait(timeout=1))
                        gateway.shutdown()
                        serve.join(timeout=1)
                        closing=threading.Thread(target=gateway.server_close)
                        closing.start()
                        try:
                            with self.assertRaises(BlockingIOError):
                                make_gateway(0,5020,policy,root/'runtime')
                        finally:
                            release.set()
                            closing.join(timeout=2)
                        self.assertFalse(closing.is_alive())
            finally:
                release.set()
                gateway.shutdown()
                gateway.server_close()
                serve.join(timeout=1)
            replacement=make_gateway(0,5020,policy,root/'runtime')
            replacement.server_close()


if __name__=='__main__':
    unittest.main()
