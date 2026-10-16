"""MQTT real é opcional; o transporte em memória atende os testes offline."""
import json
import os
import threading
import time
import uuid
import paho.mqtt.client as mqtt
from central.protocol import TOPICS, now

CONTACT_TIMEOUT = 7.0


def configured_client(role):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"mv-{role}-{uuid.uuid4().hex[:10]}")
    if os.getenv("MQTT_USERNAME"):
        client.username_pw_set(os.environ["MQTT_USERNAME"], os.getenv("MQTT_PASSWORD"))
    client.reconnect_delay_set(1, 20)
    return client


class MemoryBus:
    def __init__(self):
        self.handlers = {}
        self.messages = []
        self.online = True

    def subscribe(self, topic, callback):
        self.handlers.setdefault(topic, []).append(callback)

    def publish(self, topic, payload, qos=1, retain=False):
        if not self.online:
            return False
        payload = json.loads(json.dumps(payload))
        self.messages.append((topic, payload))
        for callback in self.handlers.get(topic, []):
            callback(payload)
        return True


class Bridge:
    def __init__(self, store, bus=None):
        self.store, self.bus = store, bus
        self.mode = "MEMORIA_OFFLINE" if bus else "MQTT_REAL"
        self.connected = False
        self.last_contact = None
        self.last_seen_monotonic = None
        self.device_status = {"estado": "DESCONHECIDO"}
        self.last_error = None
        self.stop_event = threading.Event()
        self.client = None
        if bus:
            for name in ("eventos", "ack", "status"):
                bus.subscribe(TOPICS[name], lambda payload, n=name: self.receive(n, payload))
            self.connected = True

    @property
    def contact_age(self):
        return round(time.monotonic()-self.last_seen_monotonic, 1) if self.last_seen_monotonic is not None else None

    @property
    def device_health(self):
        """Estado observado agora, sem sobrescrever o último payload recebido."""
        age = (time.monotonic() - self.last_seen_monotonic
               if self.last_seen_monotonic is not None else None)
        stale = age is None or age > CONTACT_TIMEOUT
        offline = self.device_status.get("online") is False
        failed = stale or offline or not self.connected
        return dict(
            estado="FALHA" if failed else self.device_status.get("estado", "DESCONHECIDO"),
            contato="SEM CONTATO" if failed else "EM CONTATO",
            desatualizado=stale, timeout_s=CONTACT_TIMEOUT,
            motivo=("sem contato recente" if stale else "LWT/offline" if offline else
                    "transporte desconectado" if not self.connected else ""),
            ultimo_status=self.device_status.copy(),
        )

    def receive(self, name, payload, retained=False):
        try:
            if not isinstance(payload, dict):
                raise ValueError("Payload MQTT deve ser objeto JSON")
            if name == "eventos":
                self.store.ingest(payload)
            elif name == "ack":
                newly_applied = self.store.acknowledge(payload)
                self.last_contact = now()
                self.last_seen_monotonic = time.monotonic()
                if newly_applied:
                    self.device_status = dict(estado=payload["estado"], online=True,
                                              event_id=payload["event_id"] if payload["estado"] != "NORMAL" else "")
            elif name == "status":
                self.device_status = payload
                # Um status retido pode ser antigo: não é prova de contato atual.
                if not retained and payload.get("online") is not False:
                    self.last_contact = now()
                    self.last_seen_monotonic = time.monotonic()
        except (ValueError, KeyError, TypeError) as error:
            self.last_error = str(error)

    def publish(self, name, payload, retain=False):
        if self.bus:
            return self.bus.publish(TOPICS[name], payload, qos=1, retain=retain)
        if not self.connected:
            return False
        info = self.client.publish(TOPICS[name], json.dumps(payload), qos=1, retain=retain)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def tick(self):
        self.publish("heartbeat", {"timestamp": now(), "origem": "central"})
        for command in self.store.pending():
            sent_at = now()
            if self.publish("comandos", command):
                self.store.mark_sent(command["command_id"], sent_at)

    def start(self):
        self.client = configured_client("central")
        self.client.will_set(TOPICS["heartbeat"], json.dumps({"online": False}), qos=1, retain=False)

        def connect(client, userdata, flags, reason, properties):
            self.connected = reason == 0
            if self.connected:
                for name in ("eventos", "ack", "status"):
                    client.subscribe(TOPICS[name], qos=1)

        def message(client, userdata, msg):
            if len(msg.payload) > 16384:
                self.last_error = "Payload excede 16 KiB"
                return
            try:
                self.receive(msg.topic.rsplit("/", 1)[-1], json.loads(msg.payload), msg.retain)
            except (ValueError, UnicodeDecodeError) as error:
                self.last_error = str(error)

        self.client.on_connect = connect
        self.client.on_message = message
        self.client.on_disconnect = lambda *args: setattr(self, "connected", False)
        self.client.connect_async(os.getenv("MQTT_HOST", "broker.hivemq.com"), int(os.getenv("MQTT_PORT", "1883")), 15)
        self.client.loop_start()

        def run():
            while not self.stop_event.is_set():
                try:
                    self.tick()
                except Exception as error:
                    self.last_error = str(error)
                self.stop_event.wait(2)
        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        self.stop_event.set()
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()


def publish_events(events):
    client = configured_client("vision")
    client.connect(os.getenv("MQTT_HOST", "broker.hivemq.com"), int(os.getenv("MQTT_PORT", "1883")), 15)
    client.loop_start()
    try:
        for event in events:
            info = client.publish(TOPICS["eventos"], json.dumps(event, ensure_ascii=False), qos=1, retain=False)
            info.wait_for_publish(timeout=10)
            if not info.is_published():
                raise TimeoutError("Evento sem confirmação de publicação pelo broker")
    finally:
        client.disconnect()
        client.loop_stop()
