"""Visão clássica: recebe apenas pixels e o tempo decodificado do vídeo.

Fundo espacial robusto + associação cinemática. Nenhum acesso a rótulos,
nomes interpretados, sementes ou parâmetros do gerador.
"""
import argparse
from collections import deque
import itertools
import json
from pathlib import Path
import uuid

import cv2
import numpy as np
from central.protocol import now, recommendation, validate

from vision.parameters import PARAMETERS


def unit(value):
    return float(np.clip(value, 0, 1))


class EpisodeDeduplicator:
    def __init__(self):
        self.entries = []

    def accept(self, t, xy):
        for stamp, point in self.entries:
            if (t - stamp < PARAMETERS["dedup_seconds"] and
                    np.linalg.norm(np.array(xy) - point) < PARAMETERS["dedup_radius_px"]):
                return False
        self.entries.append((t, np.array(xy)))
        return True


def velocity(track, t, window=None):
    window = PARAMETERS["history_seconds"] if window is None else window
    history = [v for v in track["history"] if t - window <= v[0] <= t]
    if len(history) < 3 or history[-1][0] - history[0][0] < .12:
        return np.zeros(2)
    return (history[-1][1] - history[0][1]) / (history[-1][0] - history[0][0])


class Tracker:
    def __init__(self):
        self.tracks = {}
        self.next_id = 1
        self.background = None

    def foreground(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.background is None:
            # Mediana espacial remove objetos menores que 71 px e marcas finas.
            # Mantida fixa: veículos imobilizados não são absorvidos pelo fundo.
            self.background = cv2.medianBlur(gray, 71).astype(np.float32)
        difference = cv2.absdiff(gray, self.background.astype(np.uint8))
        mask = (difference > PARAMETERS["foreground_delta"]).astype(np.uint8) * 255
        return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    def detections(self, mask, t):
        count, labels, stats, centers = cv2.connectedComponentsWithStats(mask)
        detections = []
        for label in range(1, count):
            x, y, w, h, area = stats[label]
            if not 115 < area < 6500 or min(w, h) < 9:
                continue
            pixels = np.column_stack(np.where(labels == label)[::-1]).astype(float)
            predictions = []
            for track in self.tracks.values():
                if t - track["t"] > .3:
                    continue
                predicted = track["xy"] + velocity(track, track["t"], .25) * (t - track["t"])
                if x - 7 < predicted[0] < x + w + 7 and y - 7 < predicted[1] < y + h + 7:
                    predictions.append((track, predicted))
            # Blobs fundidos são repartidos por centros previstos, sem usar cor.
            if len(predictions) >= 2 and area > 1.35 * max(p[0]["area"] for p in predictions):
                distances = np.stack([np.linalg.norm(pixels - p, axis=1) for _, p in predictions])
                assignments = distances.argmin(axis=0)
                for j, (track, _) in enumerate(predictions):
                    part = pixels[assignments == j]
                    if len(part) > 90:
                        detections.append((part, track["id"], .85))
            else:
                detections.append((pixels, None, 1.))
        return detections

    def update(self, frame, t):
        detections = self.detections(self.foreground(frame), t)
        used, visible = set(), []
        for pixels, forced_id, reliability in detections:
            xy = pixels.mean(axis=0)
            area = len(pixels)
            choices = []
            for ident, track in self.tracks.items():
                if ident in used or t - track["t"] > .35:
                    continue
                predicted = track["xy"] + velocity(track, track["t"], .25) * (t - track["t"])
                distance = np.linalg.norm(xy - predicted)
                size_cost = 10 * abs(np.log(area / track["area"]))
                choices.append((distance + size_cost, ident))
            cost, ident = min(choices, default=(999, None))
            if forced_id in self.tracks and forced_id not in used:
                ident, cost = forced_id, 0
            if cost > 38:
                ident = self.next_id
                self.next_id += 1
                self.tracks[ident] = dict(id=ident, history=deque(maxlen=100),
                                          area=area, reference_area=area, stopped_since=None)
            track = self.tracks[ident]
            contour = cv2.convexHull(pixels.astype(np.int32).reshape(-1, 1, 2))
            track.update(xy=xy, contour=contour, t=t, area=area,
                         visibility=unit(area / track["reference_area"]) * reliability)
            track["reference_area"] = max(track["reference_area"], area)
            track["history"].append((t, xy.copy()))
            if np.linalg.norm(velocity(track, t, .25)) < 10:
                if track["stopped_since"] is None:
                    track["stopped_since"] = t
            else:
                track["stopped_since"] = None
            used.add(ident)
            visible.append(track)
        return visible


def image_quality(frame):
    """Qualidade da região do evento, nunca um portão global de ocorrência."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    sharpness = unit(cv2.Laplacian(gray, cv2.CV_64F).var() / 160)
    contrast = unit((float(np.percentile(gray, 95)) - float(np.percentile(gray, 20))) / 85)
    return sharpness * contrast


def category(v1, v2):
    cosine = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9))
    return "FRONTAL" if cosine < -.65 else "TRASEIRA" if cosine > .65 else "LATERAL"


def confidence(approach, contact_s, ratio, stopped_s, v1, v2, quality):
    cosine = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9))
    margin = (abs(cosine) - .65) / .35 if abs(cosine) > .65 else (.65 - abs(cosine)) / .65
    # Cada termo é contínuo: os portões não o tornam uma constante.
    terms = dict(approach=unit((approach - PARAMETERS["min_approach_px_s"]) / 55),
                 contact=unit(contact_s / .8), deceleration=unit(1 - ratio),
                 immobility=unit(stopped_s / .65), category_margin=unit(margin))
    temporal = sum(PARAMETERS["weights"][key] * value for key, value in terms.items())
    score = temporal * (.30 + .70 * quality)
    return round(score, 3), terms


def contour_gap(a, b):
    points_a = a["contour"].reshape(-1, 2)
    points_b = b["contour"].reshape(-1, 2)
    return float(np.linalg.norm(points_a[:, None] - points_b[None, :], axis=2).min())


def indicators(tracks, t):
    """Calibração ortográfica fixa de CAM-SIM-01; pixels, sem escala métrica."""
    blocked, stopped = [], []
    for track in tracks:
        if track["stopped_since"] is not None:
            stopped.append(max(0., t - track["stopped_since"]))
        x, y, w, h = cv2.boundingRect(track["contour"])
        for index, (top, bottom) in enumerate(PARAMETERS["lane_bounds_px"], 1):
            intersection = max(0, min(y + h, bottom) - max(y, top))
            if intersection / h >= .30 and np.linalg.norm(velocity(track, t, .25)) < 10:
                blocked.append(index)
    return dict(veiculos_envolvidos=len(tracks),
                faixa_possivelmente_obstruida="sim" if blocked else "nao",
                faixas_obstruidas=sorted(set(blocked)), veiculo_imobilizado=bool(stopped),
                tempo_parado_s=round(max(stopped, default=0.), 2))


class Detector:
    def __init__(self):
        self.tracker = Tracker()
        self.pending = {}
        self.dedup = EpisodeDeduplicator()

    def candidate_result(self, candidate, tracks, frame, t):
        pair = [self.tracker.tracks[k] for k in candidate["ids"]]
        if any(t - track["t"] > .3 for track in pair):
            return None
        post = max(np.linalg.norm(velocity(track, t, .25)) for track in pair)
        pre = max(np.linalg.norm(candidate["v1"]), np.linalg.norm(candidate["v2"]))
        ratio = post / max(pre, 1)
        if ratio > PARAMETERS["post_speed_ratio"] or candidate["close_s"] < .20:
            return None
        involved = list(pair)
        for track in tracks:
            if track["id"] in candidate["ids"]:
                continue
            old = velocity(track, candidate["t"], .55)
            if (np.linalg.norm(track["xy"] - candidate["xy"]) < 100 and
                    np.linalg.norm(old) > 18 and np.linalg.norm(velocity(track, t, .25)) < 10):
                involved.append(track)
        point = np.mean([a["xy"] for a in involved], axis=0)
        points = np.concatenate([a["contour"] for a in involved])
        x, y, w, h = cv2.boundingRect(points)
        region = frame[max(0, y - 12):min(frame.shape[0], y + h + 12),
                       max(0, x - 12):min(frame.shape[1], x + w + 12)]
        visibility = min(a["visibility"] for a in pair)
        quality = image_quality(region) * visibility
        ind = indicators(involved, t)
        score, terms = confidence(candidate["approach"], candidate["contact_s"], ratio,
                                  ind["tempo_parado_s"], candidate["v1"], candidate["v2"], quality)
        if not self.dedup.accept(t, point):
            return None
        accepted = score >= PARAMETERS["confidence_threshold"]
        reason = (f"Aproximação={candidate['approach']:.1f} px/s; contato observado="
                  f"{candidate['contact_s']:.2f} s; proximidade={candidate['close_s']:.2f} s; "
                  f"razão pós/pré={ratio:.3f}; visibilidade={visibility:.2f}; Q local={quality:.2f}. ")
        if not accepted:
            reason += "Evidência temporal/local insuficiente: contato parcial ou degradado; revisão humana."
        return dict(tipo=category(candidate["v1"], candidate["v2"]) if accepted else "INDETERMINADO",
                    score=score, quality=round(quality, 3), xy=point, reason=reason,
                    indicadores=ind, terms=terms)

    def step(self, frame, t):
        tracks = self.tracker.update(frame, t)
        for a, b in itertools.combinations(tracks, 2):
            key = tuple(sorted((a["id"], b["id"])))
            gap = contour_gap(a, b)
            va, vb = velocity(a, t), velocity(b, t)
            delta = b["xy"] - a["xy"]
            approach = float(np.dot(va - vb, delta) / (np.linalg.norm(delta) + 1e-9))
            if (key not in self.pending and gap <= PARAMETERS["candidate_gap_px"] and
                    approach > PARAMETERS["min_approach_px_s"] and
                    min(np.linalg.norm(va), np.linalg.norm(vb)) > 8):
                self.pending[key] = dict(t=t, ids=key, v1=va, v2=vb, approach=approach,
                                         xy=(a["xy"] + b["xy"]) / 2, contact_s=0., close_s=0., last=t)
            candidate = self.pending.get(key)
            if candidate:
                dt = min(.1, t - candidate["last"])
                candidate["last"] = t
                if gap <= PARAMETERS["contact_gap_px"]:
                    candidate["contact_s"] += dt
                if gap <= PARAMETERS["candidate_gap_px"]:
                    candidate["close_s"] += dt
        for key, candidate in list(self.pending.items()):
            age = t - candidate["t"]
            if age >= PARAMETERS["post_contact_seconds"]:
                result = self.candidate_result(candidate, tracks, frame, t)
                if result:
                    return result
            if age > 2.:
                del self.pending[key]
        return None


def analyze(video, output=Path("data/evidence"), camera_id="CAM-SIM-01"):
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"Vídeo não pôde ser aberto: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not 1 <= fps <= 240:
        cap.release()
        raise ValueError("FPS inválido")
    detector, events, index = Detector(), [], 0
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = index / fps
            result = detector.step(frame, t)
            if result:
                ident = str(uuid.uuid4())
                target = output / f"{ident}.jpg"
                cv2.putText(frame, f"{result['tipo']} t={t:.2f}s score={result['score']:.2f}",
                            (8, 25), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
                cv2.circle(frame, tuple(int(x) for x in result["xy"]), 55, (0, 255, 255), 2)
                if not cv2.imwrite(str(target), frame):
                    raise OSError("Falha ao salvar evidência")
                event = dict(event_id=ident, timestamp=now(), camera_id=camera_id,
                             local="Rodovia fictícia MV, km 42", tipo=result["tipo"],
                             confianca=dict(indice=result["score"],
                                            nivel="ALTA" if result["tipo"] != "INDETERMINADO" else "INSUFICIENTE",
                                            definicao="Índice heurístico temporal/local; não é probabilidade.",
                                            termos=result["terms"], qualidade_local=result["quality"]),
                             indicadores=result["indicadores"], estado="SUSPEITA",
                             evidencia=dict(quadro=target.as_posix(), tempo_video_s=round(t, 2),
                                            frame=index, observacao=result["reason"]))
                event["recomendacao"] = recommendation(event)
                validate(event, "event")
                events.append(event)
            index += 1
    finally:
        cap.release()
    if index == 0:
        raise ValueError("Vídeo sem quadros")
    return dict(resultado=events[0]["tipo"] if events else "SEM ACIDENTE",
                events=events, frames=index, duration_s=index / fps)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    result = analyze(args.video)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.publish:
        from central.transport import publish_events
        publish_events(result["events"])
