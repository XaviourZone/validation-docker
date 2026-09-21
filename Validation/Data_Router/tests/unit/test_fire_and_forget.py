import unittest

from Validation.Data_Router.app.queue.item import QueueItem, RoutingEnvelope
from Validation.Data_Router.app.transport.tcp_client import ParserTCPClient


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.recv_called = False

    def settimeout(self, value):
        return None

    def sendall(self, payload):
        self.sent.append(payload)

    def shutdown(self, how):
        return None

    def close(self):
        return None


class TestParserTCPFireAndForget(unittest.TestCase):
    def test_send_returns_without_waiting_for_ack(self):
        client = ParserTCPClient(
            name="SAIS",
            host="127.0.0.1",
            port=10001,
            framing="ndjson",
            timeout=5,
            keep_alive=False,
        )
        fake = FakeSocket()
        client._sock = fake

        envelope = RoutingEnvelope(
            message_id="msg-1",
            source="SAIS_GLOBAL",
            input_type="FILE",
            received_at="2026-09-21T00:00:00+00:00",
            payload="!AIVDM,test*00",
            filename="test.csv",
        )
        item = QueueItem(
            envelope=envelope,
            parser_destination="SAIS",
            destination_host="127.0.0.1",
            destination_port=10001,
        )

        result = client.deliver(item)

        self.assertTrue(result.success)
        self.assertEqual(result.status, "SENT")
        self.assertEqual(len(fake.sent), 1)
        self.assertIn(b"msg-1", fake.sent[0])
        self.assertFalse(fake.recv_called)


if __name__ == "__main__":
    unittest.main()
