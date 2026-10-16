"""Modelo de protocolo do ESP32; não comprova o firmware ou Wokwi."""
from central.protocol import now, validate, TOPICS


class Device:
    def __init__(self, bus):
        self.bus = bus
        self.desired = "NORMAL"
        self.state = "FALHA"
        self.active = None
        self.seen = {}
        self.closed = set()
        self.actions = 0
        self.last_heartbeat = None
        self.clock = 0.
        bus.subscribe(TOPICS["comandos"], self.command)
        bus.subscribe(TOPICS["heartbeat"], self.heartbeat)

    def heartbeat(self, message):
        if message.get("online") is False:
            return
        self.last_heartbeat = self.clock
        self.tick(self.clock)

    def tick(self, seconds):
        self.clock = seconds
        healthy = (self.bus.online and self.last_heartbeat is not None and
                   seconds - self.last_heartbeat <= 7)
        self.state = self.desired if healthy else "FALHA"
        return self.state

    def command(self, command):
        validate(command, "command")
        ident, event, state = command["command_id"], command["event_id"], command["estado"]

        def ack(phase):
            payload = dict(command_id=ident, event_id=event, estado=state,
                           fase=phase, timestamp=now())
            self.bus.publish(TOPICS["ack"], payload)
        ack("RECEBIDO")
        if self.tick(self.clock) == "FALHA":
            return  # Recebido não equivale a aplicado; aguarda retransmissão após recuperação.
        if ident in self.seen:
            old = self.seen[ident]
            ack(old["fase"] if old["event_id"] == event and old["estado"] == state else "RECUSADO")
            return
        allowed = (state in {"NORMAL", "SUSPEITA", "CONFIRMADO"} and
                   (state == "NORMAL" or event not in self.closed) and
                   self.active in (None, event))
        if allowed:
            if state == "NORMAL":
                self.closed.add(event)
                self.active = None
            else:
                self.active = event
            self.desired = state
            self.actions += 1
            self.seen[ident] = {"fase": "APLICADO", "event_id": event, "estado": state}
            self.tick(self.clock)
            ack("APLICADO")
        else:
            self.seen[ident] = {"fase": "RECUSADO", "event_id": event, "estado": state}
            ack("RECUSADO")
        # Ordem de inserção equivale ao anel do firmware: só os 64 recentes.
        while len(self.seen) > 64:
            del self.seen[next(iter(self.seen))]
