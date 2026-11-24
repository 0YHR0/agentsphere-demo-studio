import json
import threading
import unittest
from unittest.mock import patch

from studio.relay import ModelRelay
from studio.remote_relay import chunks


class RelayTests(unittest.TestCase):
    def test_sse_tool_calls_have_indices_and_usage_stays_numeric(self):
        body = {'id': 'reply', 'model': 'model', 'choices': [{'index': 0,
            'message': {'role': 'assistant', 'content': '', 'tool_calls': [
                {'id': 'call', 'type': 'function', 'function': {'name': 'read', 'arguments': '{}'}}]},
            'finish_reason': 'tool_calls'}], 'usage': {'completion_tokens': 5}}
        result = list(chunks(body))
        self.assertEqual(0, result[0]['choices'][0]['delta']['tool_calls'][0]['index'])
        self.assertEqual('tool_calls', result[1]['choices'][0]['finish_reason'])
        self.assertEqual(5, result[1]['usage']['completion_tokens'])

    def test_provider_secret_never_written_to_sandbox(self):
        key = 'private-model-fixture'
        writes, sent = [], []
        relay = ModelRelay(None, 'sandbox', '/relay', 'sandbox',
                           {'model_id': 'demo-model', 'model_base_url': 'https://model.example.com',
                            'model_api_key': key}, lambda message: None)
        class Driver:
            def list_files(self, *args, **kwargs):
                return ['a' * 32 + '.json', '../bad.json']
            def read(self, *args, **kwargs):
                return json.dumps({'model': 'untrusted-model', 'messages': [], 'stream': True,
                                   'max_tokens': 90000})
            def write(self, sid, path, data, **kwargs):
                writes.append(data)
                relay.stop.set()
        class Client:
            def __init__(self, **kwargs):
                self.options = kwargs
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def post(self, url, headers, json):
                sent.append((url, headers, json))
                class Response:
                    status_code = 200
                    def json(self):
                        return {'choices': [{'message': {'content': key}, 'finish_reason': 'stop'}]}
                return Response()
        relay.driver = Driver()
        with patch('studio.relay.httpx.Client', Client):
            relay.serve()
        self.assertEqual(1, len(sent))
        self.assertEqual('Bearer ' + key, sent[0][1]['Authorization'])
        self.assertEqual('demo-model', sent[0][2]['model'])
        self.assertEqual(4096, sent[0][2]['max_tokens'])
        self.assertFalse(sent[0][2]['stream'])
        self.assertEqual(1, len(writes))
        self.assertNotIn(key, writes[0])
        self.assertIn('[REDACTED]', writes[0])


if __name__ == '__main__':
    unittest.main()
