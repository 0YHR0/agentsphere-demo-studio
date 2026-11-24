import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
from studio.probes import build_extensions
from studio.liveness import compatible, build_options


class ProbeTests(unittest.TestCase):
    def test_minimal_http_preserves_server_default_inheritance(self):
        payload = {'invoke': {'protocol': 'HTTP', 'port': 18080}, 'livenessProbe': {
            'probeHandler': {'httpGet': {'path': '/health'}}, 'probeConfig': {'enabled': True}}}
        result = build_extensions(json.dumps(payload))
        self.assertEqual(payload, result)
        self.assertNotIn('port', result['livenessProbe']['probeHandler']['httpGet'])

    def test_http_and_exec_are_exclusive_and_handler_is_required_when_enabled(self):
        for probe in [{'probeConfig': {'enabled': True}},
                      {'probeHandler': {'httpGet': {'path': '/health'}, 'exec': {'command': ['true']}}},
                      {'probeHandler': {'httpGet': {'path': 'health'}}, 'probeConfig': {'enabled': True}}]:
            with self.assertRaises(ValueError):
                build_extensions(json.dumps({'livenessProbe': probe}))
        self.assertEqual({'livenessProbe': {'probeConfig': {'enabled': False}}},
                         build_extensions('{"livenessProbe":{"probeConfig":{"enabled":false}}}'))

    def test_exec_limits_count_and_utf8_bytes(self):
        for args in [[], ['a'] * 21, ['x' * 4097], ['é' * 2049]]:
            with self.assertRaises(ValueError):
                build_extensions(json.dumps({'livenessProbe': {'probeHandler': {'exec': {'command': args}}}}))
        self.assertTrue(build_extensions('{"livenessProbe":{"probeHandler":{"exec":{"command":["/bin/sh","-lc","test -f /tmp/ready"]}},"probeConfig":{"enabled":true}}}'))

    def test_invalid_shapes_and_negative_config_do_not_escape_as_attribute_error(self):
        for obj in [[], {'livenessProbe': []}, {'livenessProbe': {'probeHandler': []}},
                    {'livenessProbe': {'probeConfig': {'failureThreshold': -1}}},
                    {'livenessProbe': {'probeConfig': {'periodMilliseconds': 999}}},
                    {'livenessProbe': {'probeConfig': {'enabled': 'true'}}}]:
            with self.assertRaises(ValueError):
                build_extensions(json.dumps(obj))

    def test_provider_extensions_survive_official_generated_sdk_serialization(self):
        from e2b.api.client.models import TemplateBuildStartV2
        from studio.sdk import environment
        self.assertFalse(environment()['errors'])
        payload = build_options('example.invalid/private-image:fixed')
        result = TemplateBuildStartV2.from_dict(payload).to_dict()
        self.assertEqual(payload, result)
        self.assertTrue(compatible(result))
        result['startCmd'] = 'start-real-business'
        self.assertFalse(compatible(result))


class LivenessOutcomeTests(unittest.TestCase):
    def setup_scene(self):
        return SimpleNamespace(
            config=SimpleNamespace(data={'liveness_python': '/usr/bin/python3'}),
            state={'liveness_test': {'sandbox_id': 'owned-test', 'build_detail': {}},
                   'sandboxes': [{'sandbox_id': 'owned-test'}]},
            stop=SimpleNamespace(wait=lambda _: False), log=Mock(), save=Mock())

    def test_marked_error_is_not_reported_as_service_restart(self):
        from studio.liveness import verify
        engine, driver = self.setup_scene(), Mock()
        healthy = {'service': {'health': {'status': 200}, 'identity': {'boot_id': 'first'}},
                   'sandbox': {'state': 'running', 'detailedState': 'Running'}}
        failed = {'connection_error': 'Session not found',
                  'sandbox': {'state': 'paused', 'detailedState': 'Error', 'errorMessage': 'sandbox abnormal deleted'}}
        with patch('studio.liveness.sample', side_effect=[healthy, failed]), patch(
                'studio.liveness.time.monotonic', side_effect=[0, 21, 22, 23, 203]):
            result = verify(engine, driver)
        self.assertEqual('marked_error', result['outcome'])
        self.assertIsNone(result['service_restarted_s'])
        self.assertEqual(1, result['detected_error_s'])
        self.assertEqual('Error', engine.state['sandboxes'][0]['detailed_state'])

    def test_connection_loss_alone_cannot_pass_and_evidence_is_retained(self):
        from studio.liveness import verify
        engine, driver = self.setup_scene(), Mock()
        healthy = {'service': {'health': {'status': 200}, 'identity': {'boot_id': 'first'}},
                   'sandbox': {'state': 'running', 'detailedState': 'Running'}}
        lost = {'connection_error': 'Session not found', 'sandbox': {'state': 'running', 'detailedState': 'Running'}}
        with patch('studio.liveness.sample', side_effect=[healthy, lost]), patch(
                'studio.liveness.time.monotonic', side_effect=[0, 21, 22, 23, 203]):
            with self.assertRaisesRegex(RuntimeError, '不得报告验证通过'):
                verify(engine, driver)
        self.assertEqual('Session not found', engine.state['liveness_test']['last_observations'][-1]['connection_error'])

    def test_unhealthy_baseline_never_injects_fault(self):
        from studio.liveness import verify
        engine, driver = self.setup_scene(), Mock()
        with patch('studio.liveness.sample', return_value={'service': {'health': {'status': 503}}}):
            with self.assertRaisesRegex(RuntimeError, '未注入故障'):
                verify(engine, driver)
        driver.command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
