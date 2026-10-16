"""Ferramentas de reprodução: decisões HTTP e repetição MQTT sem acesso à rede."""
import io
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from central.app import create_app
from central.store import Store
from tools.operador import Operator
from tools import reenviar_comando


def test_operator_records_identified_decision_through_form(tmp_path, event):
    store = Store(tmp_path / 'operator.sqlite')
    store.ingest(event)
    app = create_app(store)
    with app.test_client() as browser:
        class LocalHTTP:
            def open(self, url, data=None, timeout=None):
                path = urlsplit(url).path
                if data is None:
                    response = browser.get(path)
                else:
                    fields = {k: v[0] for k, v in parse_qs(data.decode()).items()}
                    response = browser.post(path, data=fields)
                assert response.status_code == 200
                return io.BytesIO(response.data)
        operator = Operator()
        operator.client = LocalHTTP()
        operator.decide(event['event_id'], 'CONFIRMAR', 'OP-REPRODUCAO')
    record = store.snapshot()['decisions'][0]
    assert record['action'] == 'CONFIRMAR' and record['operator'] == 'OP-REPRODUCAO'
    assert record['timestamp']


def test_replay_preserves_payload_and_filters_ack_ids(monkeypatch, capsys):
    command = dict(command_id='cmd-repeat', event_id='evt-repeat', estado='CONFIRMADO',
                   timestamp='2026-10-16T19:00:00-03:00')
    publications = []
    lifecycle = []

    class Client:
        def connect(self, *args, **kwargs):
            lifecycle.append('connect')
        def subscribe(self, topic, qos):
            self.on_subscribe(self, None, 1, [SimpleNamespace(is_failure=False)], None)
        def loop_start(self):
            self.on_connect(self, None, None, SimpleNamespace(is_failure=False), None)
        def publish(self, topic, payload, qos, retain):
            publications.append((topic, json.loads(payload), qos, retain))
            for event_id in ['another-event', command['event_id']]:
                ack = dict(command, event_id=event_id, fase='APLICADO')
                self.on_message(self, None, SimpleNamespace(payload=json.dumps(ack).encode()))
            return SimpleNamespace(wait_for_publish=lambda timeout: None, is_published=lambda: True)
        def disconnect(self):
            lifecycle.append('disconnect')
        def loop_stop(self):
            lifecycle.append('stop')

    monkeypatch.setattr(reenviar_comando, 'configured_client', lambda role: Client())
    monkeypatch.setattr(reenviar_comando.time, 'sleep', lambda seconds: None)
    acknowledgments = reenviar_comando.replay(command)
    assert len(publications) == 3 and len(acknowledgments) == 3
    assert all(payload == command and qos == 1 and retain is False
               for topic, payload, qos, retain in publications)
    assert lifecycle == ['connect', 'disconnect', 'stop']
    assert capsys.readouterr().out.count('ACK ') == 3


def test_replay_refuses_invalid_command_before_connect(monkeypatch):
    monkeypatch.setattr(reenviar_comando, 'configured_client',
                        lambda role: pytest.fail('Não deve abrir conexão para JSON inválido'))
    with pytest.raises(ValueError):
        reenviar_comando.replay({'command_id': 'incomplete'})
