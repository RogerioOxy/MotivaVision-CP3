import copy
import json
from pathlib import Path
import pytest
from central.protocol import now, validate, recommendation, TOPICS
from central.store import Store
from central.transport import MemoryBus, Bridge
from central.device_sim import Device
from central.app import create_app
from vision.detector import analyze


def setup_system(tmp_path):
    store = Store(tmp_path/"central.sqlite")
    bus = MemoryBus()
    bridge = Bridge(store, bus)
    device = Device(bus)
    bridge.tick()
    return store, bus, bridge, device


@pytest.mark.parametrize("kind,blocked,expected", [
    ("TRASEIRA", "nao", "EQUIPE_OPERACIONAL"),
    ("FRONTAL", "sim", "AVALIACAO_PRIORITARIA_RESGATE_SIMULADO"),
    ("LATERAL", "sim", "AMBULANCIA_SIMULADA"),
    ("INDETERMINADO", "desconhecido", "REVISAO_HUMANA"),
])
def test_recommendation_matrix(event, kind, blocked, expected):
    event["tipo"] = kind
    event["indicadores"]["faixa_possivelmente_obstruida"] = blocked
    assert recommendation(event)["recurso"] == expected


def test_low_confidence_and_unknown_count(event):
    event["confianca"]["indice"] = .5
    assert recommendation(event)["recurso"] == "REVISAO_HUMANA"
    event["tipo"] = "FRONTAL"
    event["confianca"]["indice"] = .9
    event["indicadores"]["veiculos_envolvidos"] = "desconhecido"
    assert recommendation(event)["recurso"] == "REVISAO_HUMANA"


def test_event_command_ack_schema(event):
    validate(event, "event")
    command = {"event_id": event["event_id"], "command_id": "cmd-1", "timestamp": now(), "estado": "CONFIRMADO"}
    validate(command, "command")
    validate(dict(command, fase="APLICADO"), "ack")
    invalid_messages = [dict(event, timestamp="2026-10-16T12:00:00"),
                        dict(event, tipo="CAPOTAMENTO"),
                        dict(event, confianca={"indice": float("nan")}),
                        {"event_id": "missing"}]
    for bad in invalid_messages:
        with pytest.raises(ValueError):
            validate(bad, "event")
    with pytest.raises(ValueError):
        validate(dict(command, fase="talvez"), "ack")


def test_event_dedup_and_central_recalculates_recommendation(tmp_path, event):
    store = Store(tmp_path/"db.sqlite")
    event["recomendacao"] = {"recurso": "FORJADO", "justificativa": "não confiar"}
    assert store.ingest(event)
    assert not store.ingest(event)
    assert len(store.snapshot()["events"]) == 1
    assert store.snapshot()["events"][0]["recomendacao"]["recurso"] == "EQUIPE_OPERACIONAL"


def test_confirmation_rejection_and_audit(tmp_path, event):
    store, bus, bridge, device = setup_system(tmp_path)
    store.ingest(event)
    command = store.decide(event["event_id"], "CONFIRMAR", "OPERADOR-SIM-1")
    assert command
    assert store.decide(event["event_id"], "CONFIRMAR", "OPERADOR-SIM-1") is None
    bridge.tick()  # SUSPEITA
    bridge.tick()  # CONFIRMADO, ap?s ACK da preliminar
    assert store.snapshot()["commands"][1]["phase"] == "APLICADO"
    assert device.state == "CONFIRMADO"
    other = dict(event, event_id="evt-reject")
    store.ingest(other)
    assert store.decide("evt-reject", "REJEITAR", "OPERADOR-SIM-2") is None
    audit = store.snapshot()
    assert len(audit["decisions"]) == 2
    assert all(d["timestamp"] and d["operator"] for d in audit["decisions"])
    assert len(audit["commands"]) == 2
    with pytest.raises(ValueError):
        store.decide("evt-reject", "CONFIRMAR", "OPERADOR-SIM-2")


def test_duplicate_command_and_closed_event_do_not_actuate(tmp_path, event):
    store, bus, bridge, device = setup_system(tmp_path)
    store.ingest(event)
    command = store.decide(event["event_id"], "CONFIRMAR", "OP")
    bridge.tick()
    bridge.tick()
    for _ in range(3):
        bus.publish(TOPICS["comandos"], command)
    assert device.actions == 2
    close = store.decide(event["event_id"], "ENCERRAR", "OP")
    bridge.tick()
    assert device.state == "NORMAL" and device.actions == 3
    bus.publish(TOPICS["comandos"], command)
    # Um ID novo também não reabre o event_id encerrado.
    bus.publish(TOPICS["comandos"], dict(command, command_id="new-id"))
    assert device.state == "NORMAL" and device.actions == 3
    assert close["event_id"] in device.closed


def test_timeout_broker_failure_and_recovery_model(tmp_path):
    store, bus, bridge, device = setup_system(tmp_path)
    assert device.state == "NORMAL"
    bus.online = False
    assert device.tick(1) == "FALHA"
    bus.online = True
    assert device.tick(9) == "FALHA"  # sem heartbeat, mesmo com conexão.
    bridge.tick()
    assert device.state == "NORMAL"
    assert device.tick(17) == "FALHA"  # central parada.
    bridge.tick()
    assert device.state == "NORMAL"


def test_sent_is_not_applied_and_outbox_survives_restart(tmp_path, event):
    store = Store(tmp_path/"db.sqlite")
    bus = MemoryBus()
    bridge = Bridge(store, bus)
    store.ingest(event)
    command = store.pending()[0]  # preliminar tamb?m ? outbox dur?vel
    bridge.tick()  # sem dispositivo para responder.
    assert store.snapshot()["commands"][0]["phase"] == "ENVIADO"
    reopened = Store(tmp_path/"db.sqlite")
    assert reopened.pending() == [command]
    applied = dict(command, fase="APLICADO")
    reopened.acknowledge(applied)
    reopened.acknowledge(dict(command, fase="RECEBIDO"))
    reopened.acknowledge(applied)
    assert reopened.snapshot()["commands"][0]["phase"] == "APLICADO"
    assert len(reopened.snapshot()["acks"]) == 2
    with pytest.raises(ValueError):
        reopened.acknowledge(dict(applied, event_id="unrelated"))
    with pytest.raises(ValueError):
        reopened.acknowledge(dict(applied, estado="NORMAL"))


def test_only_one_active_and_wait_for_close_ack(tmp_path, event):
    store, bus, bridge, device = setup_system(tmp_path)
    store.ingest(event)
    store.ingest(dict(event, event_id="second"))
    store.decide(event["event_id"], "CONFIRMAR", "OP")
    with pytest.raises(ValueError):
        store.decide("second", "CONFIRMAR", "OP")
    bridge.tick()
    store.decide(event["event_id"], "ENCERRAR", "OP")
    with pytest.raises(ValueError):
        store.decide("second", "CONFIRMAR", "OP")
    bridge.tick()  # CONFIRMADO
    bridge.tick()  # NORMAL; promove a segunda suspeita
    assert store.decide("second", "CONFIRMAR", "OP")


def test_persistence_exports_and_web_operator(tmp_path, event):
    store = Store(tmp_path/"db.sqlite")
    store.ingest(event)
    app = create_app(store, Bridge(store, MemoryBus()))
    with app.test_client() as client:
        assert client.get("/").status_code == 200
        assert client.post(f"/decision/{event['event_id']}", data={"action": "REJEITAR", "operator": "OP"}).status_code == 403
        with client.session_transaction() as sess:
            csrf = sess["csrf"]
        assert client.post(f"/decision/{event['event_id']}", data={"action": "REJEITAR", "operator": "OP", "csrf": csrf}).status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/export.json").json["decisions"][0]["operator"] == "OP"
        assert "REJEITADO" in client.get("/export.csv").get_data(as_text=True)
    assert Store(tmp_path/"db.sqlite").snapshot()["events"][0]["situacao"] == "REJEITADO"


def test_retained_status_is_not_live_contact(tmp_path):
    store, bus, bridge, device = setup_system(tmp_path)
    bridge.receive("status", {"estado": "NORMAL", "timestamp": now()}, retained=True)
    assert bridge.last_contact is None
    bridge.receive("status", {"estado": "NORMAL", "timestamp": now()})
    assert bridge.contact_age is not None


def test_invalid_mqtt_json_is_reported(tmp_path):
    store, bus, bridge, device = setup_system(tmp_path)
    bridge.receive("status", ["não é objeto"])
    assert bridge.last_error == "Payload MQTT deve ser objeto JSON"


def test_receive_during_failure_waits_for_heartbeat(tmp_path, event):
    store, bus, bridge, device = setup_system(tmp_path)
    store.ingest(event)
    command = store.decide(event["event_id"], "CONFIRMAR", "OP")
    device.tick(10)
    bus.publish(TOPICS["comandos"], command)
    assert device.actions == 0 and device.state == "FALHA"
    assert store.snapshot()["commands"][1]["phase"] == "RECEBIDO"
    bridge.tick()
    bridge.tick()
    assert device.actions == 2 and device.state == "CONFIRMADO"


def test_full_offline_video_mqtt_central_device_ack(tmp_path):
    store, bus, bridge, device = setup_system(tmp_path)
    result = analyze(Path("data/videos/seq04.mp4"), tmp_path / "evidence")
    event = result["events"][0]
    bus.publish(TOPICS["eventos"], event)
    bridge.tick()
    assert device.state == "SUSPEITA"  # Sinalização preliminar antes da decisão.
    store.decide(event["event_id"], "CONFIRMAR", "OPERADOR-SIM")
    bridge.tick()
    data = store.snapshot()
    assert all(c["phase"] == "APLICADO" for c in data["commands"])
    assert {a["phase"] for a in data["acks"]} == {"RECEBIDO", "APLICADO"}
    assert device.state == "CONFIRMADO"
    evidence = {"scope": "MQTT em memória e modelo Python; não é Wokwi", "event": event, "history": data, "device_actions": device.actions}
    Path("data/results/integration_offline.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

def test_command_ring_continues_after_64_and_preserves_closed(tmp_path, event):
    store, bus, bridge, device = setup_system(tmp_path)
    original = dict(event_id='closed-forever', command_id='first',
                    estado='CONFIRMADO', timestamp=now())
    device.command(original)
    device.command(dict(original, command_id='close', estado='NORMAL'))
    for i in range(90):
        device.command(dict(original, event_id='active', command_id=f'new-{i}'))
    assert len(device.seen) == 64
    assert device.actions == 92
    count = device.actions
    device.command(dict(original, event_id='active', command_id='new-89'))
    assert device.actions == count
    device.command(dict(original, event_id='active', command_id='close-active', estado='NORMAL'))
    device.command(original)  # original já saiu do anel, tombstone continua.
    assert device.state == 'NORMAL' and device.actions == count + 1
    assert 'closed-forever' in device.closed


def test_phase_timestamps_status_json_and_screen(tmp_path, event):
    store, bus, bridge, device = setup_system(tmp_path)
    store.ingest(event)
    command = store.decide(event['event_id'], 'CONFIRMAR', 'OP')
    bridge.tick()
    bridge.tick()
    phases = store.snapshot()['commands'][1]['phases']
    assert set(phases) == {'ENVIADO', 'RECEBIDO', 'APLICADO'}
    assert phases['ENVIADO'] <= phases['RECEBIDO'] <= phases['APLICADO']
    restarted = Store(store.path)
    assert restarted.snapshot()['commands'][1]['phases'] == phases
    bus.publish(TOPICS['status'], dict(estado=device.state, timestamp=now(),
                                     origem='MODELO_PYTHON_OFFLINE'))
    with create_app(restarted, bridge).test_client() as client:
        status = client.get('/status.json').json
        assert status['conectado'] is True and status['contagens']['events'] == 1
        assert status['dispositivo']['estado'] == 'CONFIRMADO'
        assert status['ultimo_contato'] is not None
        page = client.get('/').get_data(as_text=True)
        for phrase in ['comando ENVIADO (aguardando ESP32)', 'RECEBIDO pelo ESP32',
                       'APLICADO pelo ESP32', 'Regra M4', 'CONFIRMADA']:
            assert phrase in page
        assert all(value in page for value in phases.values())
        Path('data/results/central-status.json').write_text(
            json.dumps(status, indent=2, ensure_ascii=False), encoding='utf8')
        Path('data/results/central-screen.html').write_text(page, encoding='utf8')


def test_rules_combine_type_and_variable_indicator(event):
    event['tipo'] = 'LATERAL'
    assert recommendation(event)['regra'] == 'M2'
    event['indicadores']['faixa_possivelmente_obstruida'] = 'nao'
    assert recommendation(event)['regra'] == 'M4'
    event['tipo'] = 'TRASEIRA'
    event['indicadores']['veiculos_envolvidos'] = 3
    assert recommendation(event)['regra'] == 'M3'
    event['indicadores']['veiculos_envolvidos'] = 2
    assert recommendation(event)['regra'] == 'M4'
    event['indicadores']['veiculo_imobilizado'] = False
    assert recommendation(event)['regra'] == 'M5'

def test_firmware_artifacts_contract():
    diagram = json.loads(Path('esp32/diagram.json').read_text(encoding='utf8'))
    lcd = next(p for p in diagram['parts'] if p['type'] == 'wokwi-lcd1602')
    assert lcd['attrs']['pins'] == 'i2c'
    pairs = {(c[0], c[1]) for c in diagram['connections']}
    assert ('esp:D21', 'lcd:SDA') in pairs
    assert ('esp:D22', 'lcd:SCL') in pairs
    assert 'LiquidCrystal I2C' in Path('esp32/libraries.txt').read_text(encoding='utf8')
    source = Path('esp32/sketch.ino').read_text(encoding='utf8')
    assert 'delay(' not in source
    assert 'seen_head' in source and 'seen.size() < 64' in source
    assert 'closed.size() < 32' not in source
