"""SQLite: decisões e fases de transporte persistem sem depender da página."""
import csv
import io
import json
from pathlib import Path
import sqlite3
import uuid
from contextlib import contextmanager

from central.protocol import now, recommendation, validate

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
    id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(
    id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, action TEXT NOT NULL,
    operator TEXT NOT NULL, timestamp TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS commands(
    id TEXT PRIMARY KEY, event_id TEXT NOT NULL, payload TEXT NOT NULL,
    phase TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS acknowledgments(
    id INTEGER PRIMARY KEY, command_id TEXT NOT NULL, phase TEXT NOT NULL,
    payload TEXT NOT NULL, UNIQUE(command_id,phase));
CREATE TABLE IF NOT EXISTS command_phases(
    command_id TEXT NOT NULL, phase TEXT NOT NULL, timestamp TEXT NOT NULL,
    UNIQUE(command_id,phase));
CREATE TABLE IF NOT EXISTS device_queue(
    event_id TEXT PRIMARY KEY, active INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0);
"""


class Store:
    def __init__(self, path="data/central.sqlite"):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript(SCHEMA)
            # Migração de históricos do esquema anterior: preservar o dono confirmado
            # e encerramentos ainda sem ACK antes de sinalizar suspeitas antigas.
            db.execute("""INSERT OR IGNORE INTO device_queue(event_id)
                SELECT id FROM events WHERE state IN ('SUSPEITA','CONFIRMADO')
                OR id IN (SELECT event_id FROM commands
                    WHERE json_extract(payload,'$.estado')='NORMAL' AND phase!='APLICADO')
                ORDER BY (id IN (SELECT event_id FROM commands
                    WHERE json_extract(payload,'$.estado')='NORMAL' AND phase!='APLICADO')) DESC,
                    (state='CONFIRMADO') DESC, rowid""")
            self._schedule(db)

    def _command(self, db, event_id, state):
        stamp = now()
        command = dict(command_id=str(uuid.uuid4()), event_id=event_id,
                       timestamp=stamp, estado=state)
        validate(command, "command")
        db.execute("INSERT INTO commands VALUES(?,?,?,?,?)",
                   (command["command_id"], event_id, json.dumps(command), "PENDENTE", stamp))
        return command

    def _schedule(self, db):
        """Um dono até NORMAL/APLICADO; FIFO durável, inclusive rejeições na fila."""
        if db.execute("SELECT 1 FROM device_queue WHERE active=1 AND done=0").fetchone():
            return
        row = db.execute("""SELECT q.event_id,e.state FROM device_queue q
            JOIN events e ON e.id=q.event_id WHERE q.done=0 ORDER BY q.rowid LIMIT 1""").fetchone()
        if row is None:
            return
        event_id = row["event_id"]
        db.execute("UPDATE device_queue SET active=1 WHERE event_id=?", (event_id,))
        if not db.execute("SELECT 1 FROM commands WHERE event_id=?", (event_id,)).fetchone():
            state = {"SUSPEITA": "SUSPEITA", "CONFIRMADO": "CONFIRMADO"}.get(row["state"], "NORMAL")
            self._command(db, event_id, state)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def ingest(self, event):
        validate(event, "event")
        event = json.loads(json.dumps(event))
        event["recomendacao"] = recommendation(event)
        with self.db() as db:
            cur = db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?)",
                             (event["event_id"], json.dumps(event, ensure_ascii=False), "SUSPEITA"))
            if cur.rowcount == 1:
                db.execute("INSERT INTO device_queue(event_id) VALUES(?)", (event["event_id"],))
                self._schedule(db)
            return cur.rowcount == 1

    def decide(self, event_id, action, operator):
        if (action not in {"CONFIRMAR", "REJEITAR", "ENCERRAR"} or
                not isinstance(operator, str) or not 1 <= len(operator.strip()) <= 80):
            raise ValueError("Ação e identificação do operador são obrigatórias")
        with self.db() as db:
            row = db.execute("SELECT state FROM events WHERE id=?", (event_id,)).fetchone()
            if row is None:
                raise ValueError("Ocorrência inexistente")
            targets = {"CONFIRMAR": "CONFIRMADO", "REJEITAR": "REJEITADO", "ENCERRAR": "ENCERRADO"}
            target = targets[action]
            if row["state"] == target:
                return None  # Formulário repetido não cria outro comando.
            source = "CONFIRMADO" if action == "ENCERRAR" else "SUSPEITA"
            if row["state"] != source:
                raise ValueError("Transição não permitida")
            if action == "CONFIRMAR":
                owner = db.execute("SELECT active FROM device_queue WHERE event_id=?", (event_id,)).fetchone()
                if not owner or not owner["active"]:
                    raise ValueError("Ocorrência na fila; aguardar NORMAL/APLICADO da anterior")
            stamp = now()
            db.execute("UPDATE events SET state=? WHERE id=?", (target, event_id))
            db.execute("""INSERT INTO decisions(event_id,action,operator,timestamp)
                          VALUES(?,?,?,?)""", (event_id, action, operator.strip(), stamp))
            owner = db.execute("SELECT active FROM device_queue WHERE event_id=?", (event_id,)).fetchone()
            if action == "REJEITAR" and not owner["active"]:
                # Ao chegar sua vez, NORMAL grava o tombstone mesmo sem preliminar.
                return None
            return self._command(db, event_id, "CONFIRMADO" if action == "CONFIRMAR" else "NORMAL")

    def acknowledge(self, ack):
        validate(ack, "ack")
        with self.db() as db:
            row = db.execute("SELECT * FROM commands WHERE id=? AND event_id=?",
                             (ack["command_id"], ack["event_id"])).fetchone()
            if row is None:
                raise ValueError("ACK sem comando correspondente")
            command = json.loads(row["payload"])
            if ack["fase"] == "APLICADO" and command["estado"] != ack["estado"]:
                raise ValueError("ACK não corresponde ao estado comandado")
            db.execute("""INSERT OR IGNORE INTO acknowledgments(command_id,phase,payload)
                          VALUES(?,?,?)""", (ack["command_id"], ack["fase"], json.dumps(ack)))
            db.execute("INSERT OR IGNORE INTO command_phases VALUES(?,?,?)",
                       (ack["command_id"], ack["fase"], now()))
            rank = {"PENDENTE": 0, "ENVIADO": 1, "RECEBIDO": 2, "RECUSADO": 3, "APLICADO": 4}
            if rank[ack["fase"]] > rank[row["phase"]]:
                db.execute("UPDATE commands SET phase=?,updated=? WHERE id=?",
                           (ack["fase"], now(), ack["command_id"]))
            if ack["fase"] == "APLICADO" and command["estado"] == "NORMAL":
                db.execute("UPDATE device_queue SET done=1,active=0 WHERE event_id=?",
                           (ack["event_id"],))
                self._schedule(db)
            return ack["fase"] == "APLICADO" and row["phase"] != "APLICADO"

    def mark_sent(self, ident, sent_at=None):
        with self.db() as db:
            stamp = sent_at or now()
            db.execute("INSERT OR IGNORE INTO command_phases VALUES(?,?,?)",
                       (ident, "ENVIADO", stamp))
            db.execute("""UPDATE commands SET phase='ENVIADO',updated=?
                          WHERE id=? AND phase='PENDENTE'""", (stamp, ident))

    def pending(self):
        with self.db() as db:
            # Só um comando em voo. RECUSADO bloqueia a fila para inspeção;
            # não permite ultrapassar uma transição que não foi aplicada.
            rows = db.execute("""SELECT payload FROM commands WHERE phase!='APLICADO'
                                 ORDER BY rowid LIMIT 1""")
            result = [json.loads(row[0]) for row in rows]
            if result:
                phase = db.execute("SELECT phase FROM commands WHERE id=?",
                                   (result[0]["command_id"],)).fetchone()[0]
                if phase == "RECUSADO":
                    return []
            return result

    def snapshot(self):
        with self.db() as db:
            events = [dict(json.loads(row["payload"]), situacao=row["state"])
                      for row in db.execute("SELECT * FROM events ORDER BY rowid DESC")]
            queue = {row["event_id"]: row for row in db.execute("SELECT * FROM device_queue")}
            for event in events:
                slot = queue.get(event["event_id"])
                event["sinalizacao"] = ("CONCLUIDA" if not slot or slot["done"] else
                                         "ATIVA" if slot["active"] else "NA FILA")
            commands = [dict(row) for row in db.execute("SELECT * FROM commands")]
            for command in commands:
                command["estado"] = json.loads(command["payload"])["estado"]
                phases = db.execute("SELECT phase,timestamp FROM command_phases WHERE command_id=?",
                                    (command["id"],))
                command["phases"] = {row["phase"]: row["timestamp"] for row in phases}
            return dict(events=events, commands=commands,
                        decisions=[dict(row) for row in db.execute("SELECT * FROM decisions")],
                        acks=[dict(row) for row in db.execute("SELECT * FROM acknowledgments")])

    def export_csv(self):
        result = io.StringIO(newline="")
        writer = csv.writer(result)
        writer.writerow(("event_id", "tipo", "confianca", "local", "situacao",
                         "evidencia", "decisoes", "comandos"))
        data = self.snapshot()
        for event in data["events"]:
            decisions = [d for d in data["decisions"] if d["event_id"] == event["event_id"]]
            commands = [c for c in data["commands"] if c["event_id"] == event["event_id"]]
            writer.writerow((event["event_id"], event["tipo"], event["confianca"]["indice"],
                             event["local"], event["situacao"], event["evidencia"]["quadro"],
                             json.dumps(decisions, ensure_ascii=False),
                             json.dumps(commands, ensure_ascii=False)))
        return result.getvalue()
