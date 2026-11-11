import json
import threading
import unittest

from desktop_pet.bridge import (BRIDGE_PROTOCOL_VERSION, BridgeError,
                                BridgeHost, handle_system)


class BridgeHostTests(unittest.TestCase):
    def setUp(self):
        self.host = BridgeHost(context={'data_dir': 'D:/data', 'dev_mode': False})

    def invoke(self, method, payload=None):
        return json.loads(self.host.invoke(method, payload or '{}'))

    def register_echo(self):
        def echo(action, args, host):
            if action == 'fail':
                raise BridgeError('标题不能为空')
            if action == 'boom':
                raise RuntimeError('hidden')
            if action != 'ping':
                raise BridgeError(f'未知方法: echo.{action}', code='NOT_FOUND')
            return {'action': action, 'args': args}
        self.host.register_module('echo', echo)

    def test_unknown_module_and_action(self):
        resp = self.invoke('nope.add')
        self.assertFalse(resp['ok'])
        self.assertEqual(resp['error']['code'], 'NOT_FOUND')

        self.register_echo()
        resp = self.invoke('echo.missing')
        self.assertFalse(resp['ok'])
        self.assertEqual(resp['error']['code'], 'NOT_FOUND')
        self.assertIn('echo.missing', resp['error']['message'])

    def test_invalid_method_name(self):
        for method in ('tasks', 'a.b.c', '', 'tasks.add.extra'):
            resp = self.invoke(method)
            self.assertFalse(resp['ok'], method)
            self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')

    def test_non_object_payload(self):
        self.register_echo()
        resp = self.invoke('echo.ping', '[1,2]')
        self.assertFalse(resp['ok'])
        self.assertEqual(resp['error']['code'], 'VALIDATION_ERROR')

    def test_success_envelope_passes_data(self):
        self.register_echo()
        resp = self.invoke('echo.ping', '{"x": 1}')
        self.assertTrue(resp['ok'])
        self.assertEqual(resp['data'], {'action': 'ping', 'args': {'x': 1}})

    def test_bridge_error_maps_code_and_message(self):
        self.register_echo()
        resp = self.invoke('echo.fail')
        self.assertFalse(resp['ok'])
        self.assertEqual(resp['error'], {'code': 'VALIDATION_ERROR', 'message': '标题不能为空'})

    def test_unexpected_exception_becomes_internal(self):
        self.register_echo()
        resp = self.invoke('echo.boom')
        self.assertFalse(resp['ok'])
        self.assertEqual(resp['error']['code'], 'INTERNAL')
        self.assertNotIn('hidden', json.dumps(resp))

    def test_system_info(self):
        resp = self.invoke('system.info')
        self.assertTrue(resp['ok'])
        data = resp['data']
        self.assertEqual(data['bridgeVersion'], BRIDGE_PROTOCOL_VERSION)
        self.assertEqual(data['dataDir'], 'D:/data')
        self.assertFalse(data['devMode'])
        self.assertIn('appVersion', data)

    def test_system_unknown_action(self):
        resp = self.invoke('system.nope')
        self.assertFalse(resp['ok'])
        self.assertEqual(resp['error']['code'], 'NOT_FOUND')

    def test_job_lifecycle(self):
        job_id, cancel_event = self.host.create_job()
        self.host.cancel(job_id)
        self.assertTrue(cancel_event.is_set())
        self.host.finish_job(job_id)

        self.host.cancel('missing-id')  # no-op, must not raise
        self.assertEqual(self.host._jobs, {})

    def test_emit_event_and_result(self):
        self.invoke('system.info')  # handshake, so events flow instead of buffering
        received = []
        self.host.event.connect(lambda name, payload: received.append((name, json.loads(payload))))
        self.host.emit_event('assistant.chunk', {'text': '你好'})
        self.assertEqual(received, [('assistant.chunk', {'text': '你好'})])

        job_id, _ = self.host.create_job()
        self.host.emit_result(job_id, ok=True, message='done', added=3)
        self.assertEqual(received[-1], ('job.result', {'jobId': job_id, 'ok': True, 'message': 'done', 'added': 3}))
        self.assertEqual(self.host._jobs, {})

    def test_handle_system_raises_not_found_directly(self):
        with self.assertRaises(BridgeError) as ctx:
            handle_system('x', {}, self.host)
        self.assertEqual(ctx.exception.code, 'NOT_FOUND')

    def test_events_buffered_until_handshake(self):
        received = []
        self.host.event.connect(lambda name, payload: received.append((name, payload)))
        self.host.emit_event('app.launched', {'version': '1.0'})
        self.assertEqual(received, [])
        resp = self.invoke('system.info')
        self.assertTrue(resp['ok'])
        self.assertEqual(received, [('app.launched', '{"version": "1.0"}')])
        self.host.emit_event('assistant.chunk', {'text': '你好'})
        self.assertEqual(received[-1], ('assistant.chunk', '{"text": "你好"}'))

    def test_handshake_replays_in_order(self):
        received = []
        self.host.event.connect(lambda name, payload: received.append(name))
        for i in range(3):
            self.host.emit_event('tick', {'i': i})
        self.invoke('system.info')
        self.assertEqual(received, ['tick', 'tick', 'tick'])
        self.host.emit_event('after', {})
        self.assertEqual(received[-1], 'after')


if __name__ == '__main__':
    unittest.main()
