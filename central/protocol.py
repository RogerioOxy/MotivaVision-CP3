"""Contrato MQTT e matriz fictícia; não constitui protocolo médico."""
import math
import os
from datetime import datetime

from central.config import load_env
from vision.parameters import PARAMETERS

load_env()
TYPES = {"TRASEIRA", "FRONTAL", "LATERAL", "INDETERMINADO"}
STATES = {"NORMAL", "SUSPEITA", "CONFIRMADO", "FALHA"}
PREFIX = os.getenv("MQTT_PREFIX", "motiva/561942").rstrip("/")
TOPICS = {key: f"{PREFIX}/{key}" for key in ("eventos", "comandos", "ack", "status", "heartbeat")}


def now():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def resource(rule, category, reason):
    return dict(regra=rule, recurso=category, justificativa=reason)


def recommendation(event):
    kind, ind = event["tipo"], event["indicadores"]
    uncertain = (kind == "INDETERMINADO" or
                 event["confianca"]["indice"] < PARAMETERS["confidence_threshold"] or
                 event["confianca"]["nivel"] == "INSUFICIENTE")
    if uncertain:
        return resource("M0", "REVISAO_HUMANA",
                        "Evidência insuficiente; revisar sem concluir tipo ou gravidade.")
    count = ind["veiculos_envolvidos"]
    if (kind == "FRONTAL" and isinstance(count, int) and count >= 2 and
            ind.get("veiculo_imobilizado") is True):
        return resource("M1", "AVALIACAO_PRIORITARIA_RESGATE_SIMULADO",
                        "Frontal com imobilização observada: avaliação prioritária fictícia.")
    if kind == "LATERAL" and ind["faixa_possivelmente_obstruida"] == "sim":
        return resource("M2", "AMBULANCIA_SIMULADA",
                        "Lateral com faixa possivelmente obstruída: avaliação humana fictícia.")
    if kind == "TRASEIRA" and isinstance(count, int) and count >= 3:
        return resource("M3", "AMBULANCIA_SIMULADA",
                        "Traseira com três ou mais envolvidos: sugestão fictícia.")
    if kind in {"TRASEIRA", "LATERAL"} and ind.get("veiculo_imobilizado") is True:
        return resource("M4", "EQUIPE_OPERACIONAL",
                        "Traseira/lateral com imobilização: avaliação operacional fictícia.")
    return resource("M5", "REVISAO_HUMANA",
                    "Indicadores não sustentam regra específica; revisar sem inferir gravidade.")


def validate_event(message):
    confidence = message["confianca"]
    if message["tipo"] not in TYPES or not isinstance(confidence, dict):
        raise ValueError("Tipo/confiança inválidos")
    index = confidence.get("indice")
    if (isinstance(index, bool) or not isinstance(index, (int, float)) or
            not math.isfinite(index) or not 0 <= index <= 1):
        raise ValueError("Índice fora de [0,1]")
    if confidence.get("nivel") not in {"ALTA", "INSUFICIENTE"} or not confidence.get("definicao"):
        raise ValueError("Definição de confiança ausente")
    indicators = message["indicadores"]
    if (not isinstance(indicators, dict) or
            indicators.get("veiculos_envolvidos") not in (0, 1, 2, 3, 4, 5, "desconhecido") or
            indicators.get("faixa_possivelmente_obstruida") not in {"sim", "nao", "desconhecido"}):
        raise ValueError("Indicadores inválidos")
    if (not isinstance(message["evidencia"], dict) or
            not message["evidencia"].get("quadro")):
        raise ValueError("Referência de evidência ausente")
    recommendation_value = message["recomendacao"]
    if (not isinstance(recommendation_value, dict) or
            not all(recommendation_value.get(key) for key in ("recurso", "justificativa"))):
        raise ValueError("Recomendação inválida")


def validate(message, kind):
    if not isinstance(message, dict):
        raise ValueError("JSON deve ser objeto")
    required = {
        "event": ("event_id", "timestamp", "camera_id", "local", "tipo", "confianca",
                  "indicadores", "recomendacao", "estado", "evidencia"),
        "command": ("event_id", "command_id", "estado", "timestamp"),
        "ack": ("event_id", "command_id", "fase", "estado", "timestamp"),
    }[kind]
    if any(key not in message for key in required):
        raise ValueError("Campos obrigatórios ausentes")
    for key in ("event_id", "command_id"):
        if key in message:
            value = message[key]
            if not isinstance(value, str) or not 1 <= len(value) <= 64:
                raise ValueError("Identificador inválido")
    try:
        stamp = datetime.fromisoformat(message["timestamp"])
        if stamp.tzinfo is None:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("timestamp deve conter fuso") from None
    if message["estado"] not in STATES:
        raise ValueError("Estado inválido")
    if kind == "event":
        validate_event(message)
    if kind == "ack" and message["fase"] not in {"RECEBIDO", "APLICADO", "RECUSADO"}:
        raise ValueError("Fase inválida")
    return message
