"""Regressões da integração real; MQTT e dispositivo permanecem modelos offline."""
import json
from pathlib import Path

import pytest

from central.app import create_app
from central.device_sim import Device
from central.protocol import TOPICS, now
from central.store import Store
from central.transport import Bridge, MemoryBus
from tools.circuit import render_circuit
from tools.evaluate import fingerprint


def system(tmp_path):
    store = Store(tmp_path / "integration.sqlite")
    bus = MemoryBus()
    bridge = Bridge(store, bus)
    device = Device(bus)
    bridge.tick()
    return store, bus, bridge, device


def test_arrival_suspicion_rejection_closes_and_never_reopens(tmp_path, event):
    store, bus, bridge, device = system(tmp_path)
    bus.publish(TOPICS["eventos"], event)
    preliminary = store.pending()[0]
    assert preliminary["estado"] == "SUSPEITA"
    bridge.tick()
    assert device.state == "SUSPEITA" and device.actions == 1
    close = store.decide(event["event_id"], "REJEITAR", "OP")
    assert close["estado"] == "NORMAL"
    bridge.tick()
    assert device.state == "NORMAL" and device.active is None
    assert device.actions == 2 and event["event_id"] in device.closed
    # Tanto a duplicata quanto outro ID deixam o evento encerrado.
    bus.publish(TOPICS["eventos"], event)
    bus.publish(TOPICS["comandos"], preliminary)
    bus.publish(TOPICS["comandos"], dict(preliminary, command_id="new-suspicion"))
    assert device.state == "NORMAL" and device.actions == 2
    assert store.pending() == []
    data = Store(store.path).snapshot()
    assert len(data["events"]) == 1 and len(data["commands"]) == 2
    assert data["events"][0]["situacao"] == "REJEITADO"
    assert data["events"][0]["sinalizacao"] == "CONCLUIDA"
    assert data["decisions"][0]["operator"] == "OP"


def test_fifo_persists_and_only_advances_after_close_applied(tmp_path, event):
    store, bus, bridge, device = system(tmp_path)
    for ident in [event["event_id"], "second", "third"]:
        store.ingest(dict(event, event_id=ident))
    assert len(store.snapshot()["events"]) == 3
    assert len(store.snapshot()["commands"]) == 1
    with pytest.raises(ValueError, match="fila"):
        store.decide("second", "CONFIRMAR", "OP")
    bridge.tick()
    store.decide(event["event_id"], "CONFIRMAR", "OP")
    bridge.tick()
    assert device.state == "CONFIRMADO"
    close = store.decide(event["event_id"], "ENCERRAR", "OP")
    # RECEBIDO não libera a vaga, mesmo após reabrir o SQLite.
    store.acknowledge(dict(close, fase="RECEBIDO"))
    restarted = Store(store.path)
    assert len(restarted.snapshot()["commands"]) == 3
    bridge.store = restarted
    bridge.tick()
    assert device.state == "NORMAL"
    assert restarted.pending()[0]["event_id"] == "second"
    bridge.tick()
    assert device.state == "SUSPEITA" and device.active == "second"
    assert len(restarted.snapshot()["events"]) == 3
    assert next(e for e in restarted.snapshot()["events"]
                if e["event_id"] == "third")["sinalizacao"] == "NA FILA"


def test_queued_rejection_gets_tombstone_before_next_suspicion(tmp_path, event):
    store, bus, bridge, device = system(tmp_path)
    for ident in ["first", "reject-waiting", "third"]:
        store.ingest(dict(event, event_id=ident))
    assert store.decide("reject-waiting", "REJEITAR", "OP") is None
    bridge.tick()
    store.decide("first", "REJEITAR", "OP")
    bridge.tick()
    command = store.pending()[0]
    assert (command["event_id"], command["estado"]) == ("reject-waiting", "NORMAL")
    bridge.tick()
    assert "reject-waiting" in device.closed
    bridge.tick()
    assert device.active == "third" and device.state == "SUSPEITA"
    device.command(dict(command, command_id="late-confirm", estado="CONFIRMADO"))
    assert device.active == "third" and device.state == "SUSPEITA"


def test_fast_decisions_cannot_overtake_unacknowledged_preliminary(tmp_path, event):
    store, bus, bridge, device = system(tmp_path)
    store.ingest(event)
    preliminary = store.pending()[0]
    confirm = store.decide(event["event_id"], "CONFIRMAR", "OP")
    close = store.decide(event["event_id"], "ENCERRAR", "OP")
    assert store.pending() == [preliminary]
    bridge.tick()
    assert device.state == "SUSPEITA" and store.pending() == [confirm]
    bridge.tick()
    assert device.state == "CONFIRMADO" and store.pending() == [close]
    bridge.tick()
    assert device.state == "NORMAL" and store.pending() == []
    states = [payload["estado"] for topic, payload in bus.messages if topic == TOPICS["comandos"]]
    assert states == ["SUSPEITA", "CONFIRMADO", "NORMAL"]


def test_refusal_blocks_outbox_for_inspection(tmp_path, event):
    store = Store(tmp_path / "refused.sqlite")
    store.ingest(event)
    command = store.pending()[0]
    store.decide(event["event_id"], "REJEITAR", "OP")
    store.acknowledge(dict(command, fase="RECUSADO"))
    assert store.pending() == []
    assert store.snapshot()["commands"][1]["phase"] == "PENDENTE"
    assert store.snapshot()["events"][0]["sinalizacao"] == "ATIVA"


def test_migrate_legacy_history_without_losing_audit(tmp_path, event):
    store = Store(tmp_path / "legacy.sqlite")
    store.ingest(event)
    # Reconstitui um banco com as tabelas do esquema anterior e ocorrência confirmada.
    with store.db() as db:
        db.execute("DROP TABLE device_queue")
        db.execute("DELETE FROM commands")
        db.execute("UPDATE events SET state='CONFIRMADO'")
    restarted = Store(store.path)
    assert restarted.pending()[0]["estado"] == "CONFIRMADO"
    assert restarted.snapshot()["events"][0]["sinalizacao"] == "ATIVA"
    assert len(Store(store.path).snapshot()["commands"]) == 1


@pytest.mark.parametrize("closed_phase", ["APLICADO", "ENVIADO"])
def test_legacy_two_commands_two_decisions_migration(tmp_path, event, closed_phase):
    store = Store(tmp_path / "legacy.sqlite")
    store.ingest(event)
    stamp = now()
    with store.db() as db:
        db.execute("DROP TABLE device_queue")
        db.execute("DELETE FROM commands")
        db.execute("UPDATE events SET state='ENCERRADO'")
        for ident, state, phase in [("confirm", "CONFIRMADO", "APLICADO"),
                                    ("close", "NORMAL", closed_phase)]:
            command = dict(event_id=event["event_id"], command_id=ident,
                           estado=state, timestamp=stamp)
            db.execute("INSERT INTO commands VALUES(?,?,?,?,?)",
                       (ident, event["event_id"], json.dumps(command), phase, stamp))
        for action in ["CONFIRMAR", "ENCERRAR"]:
            db.execute("INSERT INTO decisions(event_id,action,operator,timestamp) VALUES(?,?,?,?)",
                       (event["event_id"], action, "OP-LEGACY", stamp))
    restarted = Store(store.path)
    data = restarted.snapshot()
    assert (len(data["events"]), len(data["commands"]), len(data["decisions"])) == (1, 2, 2)
    assert data["events"][0]["sinalizacao"] == ("CONCLUIDA" if closed_phase == "APLICADO" else "ATIVA")
    restarted.ingest(dict(event, event_id="new-event"))
    if closed_phase != "APLICADO":
        assert restarted.pending()[0]["command_id"] == "close"
        restarted.acknowledge(dict(restarted.pending()[0], fase="APLICADO"))
    assert restarted.pending()[0]["event_id"] == "new-event"


def test_old_applied_ack_cannot_replace_new_device_state(tmp_path, event):
    store, bus, bridge, device = system(tmp_path)
    store.ingest(event)
    preliminary = store.pending()[0]
    bridge.tick()
    store.decide(event["event_id"], "CONFIRMAR", "OP")
    bridge.tick()
    assert bridge.device_health["estado"] == "CONFIRMADO"
    bus.publish(TOPICS["ack"], dict(preliminary, fase="APLICADO"))
    assert bridge.device_health["estado"] == "CONFIRMADO"


@pytest.mark.parametrize("age,stale", [(0, False), (7, False), (7.001, True), (39, True)])
def test_contact_timeout_calculation_http_and_page(tmp_path, monkeypatch, age, stale):
    clock = [100.0]
    monkeypatch.setattr("central.transport.time.monotonic", lambda: clock[0])
    store = Store(tmp_path / "contact.sqlite")
    bridge = Bridge(store, MemoryBus())
    bridge.receive("status", dict(estado="NORMAL", online=True, timestamp=now()))
    clock[0] += age
    with create_app(store, bridge).test_client() as client:
        status = client.get("/status.json").json
        health = status["dispositivo"]
        assert health["desatualizado"] is stale
        assert health["estado"] == ("FALHA" if stale else "NORMAL")
        assert health["contato"] == ("SEM CONTATO" if stale else "EM CONTATO")
        assert health["ultimo_status"]["estado"] == "NORMAL"
        page = client.get("/").get_data(as_text=True)
        assert f"ESP32: {health['estado']}" in page
        assert health["contato"] in page
    bridge.receive("status", dict(estado="NORMAL", online=True, timestamp=now()))
    assert bridge.device_health["estado"] == "NORMAL"


def test_lwt_is_offline_without_pretending_live_contact(tmp_path, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("central.transport.time.monotonic", lambda: clock[0])
    bridge = Bridge(Store(tmp_path / "lwt.sqlite"), MemoryBus())
    bridge.receive("status", {"estado": "NORMAL", "online": True}, retained=True)
    assert bridge.device_health["desatualizado"] is True
    bridge.receive("status", {"estado": "NORMAL", "online": True})
    last_contact = bridge.last_contact
    clock[0] += 1
    bridge.receive("status", {"estado": "FALHA", "online": False, "origem": "LWT"})
    assert bridge.last_contact == last_contact and bridge.contact_age == 1
    assert bridge.device_health["estado"] == "FALHA"
    assert bridge.device_health["contato"] == "SEM CONTATO"
    assert bridge.device_health["motivo"] == "LWT/offline"


def test_firmware_display_network_source_contract():
    """Inspeção estática: não representa compilação ou execução C++."""
    source = Path("esp32/sketch.ino").read_text(encoding="utf8")
    display = source.split("void updateDisplay()", 1)[1].split("bool saveLedger", 1)[0]
    assert "activeEvent.substring(0, 5)" in display and 'String("-")' in display
    assert "lastEvent" not in source
    assert "sem heartbeat" in display and "sem MQTT" in display
    network = source.split("void networkTask", 1)[1].split("void setup", 1)[0]
    assert "socketClient.stop();" in network and "mqtt.disconnect()" not in network
    assert 'if (!wifiConnecting &&' in network
    assert source.count('WiFi.begin(') == 1
    assert "WiFi.begin(" not in source.split("void setup", 1)[1]


def test_circuit_uses_diagram_positions_and_keeps_parts_separate():
    root = Path.cwd()
    diagram = json.loads((root / "esp32/diagram.json").read_text(encoding="utf8"))
    # Envelopes ilustrativos conservadores, não footprints medidos do Wokwi.
    sizes = {"esp": (150, 250), "lcd": (300, 150), "rgb": (65, 85),
             "rr": (95, 35), "rg": (95, 35), "rb": (95, 35),
             "bz": (90, 70), "fault": (100, 75)}
    boxes = []
    for part in diagram["parts"]:
        x, y = part["left"], part["top"]
        width, height = sizes[part["id"]]
        for ident, other_x, other_y, other_w, other_h in boxes:
            overlap = (x < other_x + other_w and x + width > other_x and
                       y < other_y + other_h and y + height > other_y)
            assert not overlap, (part["id"], ident)
        boxes.append((part["id"], x, y, width, height))
    svg = render_circuit(root)
    for part in diagram["parts"]:
        assert f'id="{part["id"]}"' in svg
        assert f'x="{part["left"]}" y="{part["top"]}"' in svg
    assert len(diagram["connections"]) == 17


def test_frozen_results_and_report_contract():
    seal = json.loads(Path("data/results/calibration.json").read_text(encoding="utf8"))
    assert fingerprint(Path("data")) == seal["fingerprint"]
    final = json.loads(Path("data/results/final.json").read_text(encoding="utf8"))
    assert sum(row["correct"] for row in final) == 4 and len(final) == 6
    errors = {row["video"]: row for row in final if not row["correct"]}
    assert errors["seq02.mp4"]["false_negative"] is True
    assert errors["seq09.mp4"]["expected"] == "INDETERMINADO"
    assert errors["seq09.mp4"]["obtained"] == "SEM ACIDENTE"
    integration = Path("docs/INTEGRACAO.md").read_text(encoding="utf8")
    assert "33 arquivos de evidência" in integration
    assert "veiculos_envolvidos: 3" in integration
    assert "34% e 46%" in integration
    for state in ["NORMAL", "SUSPEITA", "CONFIRMADO", "FALHA"]:
        assert state in integration
