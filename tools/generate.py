"""Simulações determinísticas; somente o avaliador consome os rótulos."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

FPS, SIZE = 20, (480, 320)
# Tipo, conjunto, duração, impacto, ponto, sentido, ângulo, tamanho, tráfego extra.
SCENES = [
    ("normal", "dev", 6.8, 2.0, (240, 100), 1, 0, (40, 20), 3),
    ("lateral", "final", 8.6, 4.5, (310, 49), -1, 125, (66, 25), 2),
    ("rain", "dev", 7.4, 3.6, (275, 155), 1, 68, (43, 21), 2),
    ("rear", "dev", 7.2, 2.4, (300, 96), 1, 0, (42, 20), 1),
    ("braking", "final", 8.8, 3.1, (280, 145), 1, 0, (64, 24), 2),
    ("front", "final", 6.6, 2.8, (335, 116), 1, 180, (62, 24), 1),
    ("parked", "dev", 8.0, 3.0, (340, 300), -1, 0, (70, 25), 3),
    ("lateral", "dev", 7.8, 3.2, (210, 155), 1, 55, (44, 21), 1),
    ("occlusion", "final", 9.4, 5.0, (210, 210), -1, 180, (48, 22), 2),
    ("rear", "final", 8.2, 3.7, (190, 258), -1, 180, (68, 24), 1),
    ("front", "dev", 9.0, 4.1, (260, 205), -1, 0, (40, 20), 2),
    ("near", "final", 7.6, 3.4, (245, 140), 1, 0, (46, 21), 3),
]
LABELS = {"rear": "TRASEIRA", "front": "FRONTAL", "lateral": "LATERAL",
          "rain": "INDETERMINADO", "occlusion": "INDETERMINADO"}


def rectangle(center, size, angle):
    return cv2.boxPoints((tuple(map(float, center)), tuple(map(float, size)), float(angle)))


def contact_offset(size_a, size_b, angle, axis):
    """Encontra toque geométrico dos retângulos, sem interpenetração inicial."""
    low, high = 0., 130.
    a = rectangle((0, 0), size_a, 0)
    for _ in range(25):
        middle = (low + high) / 2
        overlap, _ = cv2.intersectConvexConvex(a, rectangle(axis * middle, size_b, angle))
        if overlap > 0:
            low = middle
        else:
            high = middle
    return axis * (high + 1.5)


def vehicles(spec):
    kind, split, duration, impact, center, direction, angle, size, extra = spec
    point = np.array(center, dtype=float)
    first_v = np.array([direction * (62 if split == "dev" else 73), 0.])
    second_size = (38., 19.) if split == "dev" else (46., 22.)
    if kind in {"front", "occlusion"}:
        second_v = np.array([-direction * 48., 0.])
        offset = np.array([direction * ((size[0] + second_size[0]) / 2 + 1.5), 0.])
    elif kind in {"lateral", "rain"}:
        radians = np.deg2rad(angle)
        second_v = np.array([np.cos(radians), np.sin(radians)]) * 47
        offset = contact_offset(size, second_size, angle, -second_v / 47)
    else:
        second_v = np.array([direction * 27., 0.])
        offset = np.array([direction * ((size[0] + second_size[0]) / 2 + 1.5), 0.])
    items = [dict(end=point, v=first_v, size=size, angle=0., stop=impact),
             dict(end=point + offset, v=second_v, size=second_size,
                  angle=float(angle), stop=impact)]
    if kind == "rear" and split == "dev":
        items.append(dict(end=point - np.array([43.5, 0]), v=np.array([85., 0]),
                          size=(42, 20), angle=0., stop=impact + .25))
    if kind == "normal":
        items[0].update(end=np.array([20., 92.]), v=np.array([58., 0]), stop=None)
        items[1].update(end=np.array([440., 255.]), v=np.array([-43., 0]), stop=None)
    elif kind == "braking":
        items[0].update(end=np.array([280., 145.]))
        items[1].update(end=np.array([30., 95.]), v=np.array([42., 0]), stop=None)
    elif kind == "parked":
        items[0].update(end=point, v=np.zeros(2), stop=None)
        items[1].update(end=np.array([440., 205.]), v=np.array([-46., 0]), stop=None)
    elif kind == "near":
        # Laterais separadas por 6 px: ultrapassagem sem contato ou frenagem.
        items[0].update(end=np.array([15., 132.]), v=np.array([60., 0]), stop=None)
        items[1].update(end=np.array([120., 159.]), v=np.array([26., 0]), stop=None)
    occupied = [center[1]]
    for j in range(extra):
        lanes = [92, 146, 204, 260]
        y = max(lanes, key=lambda y: min(abs(y - p) for p in occupied))
        occupied.append(y)
        sign = 1 if y < 175 else -1
        items.append(dict(end=np.array([-45. if sign == 1 else 525., float(y)]),
                          v=np.array([sign * (32 + j * 7), 0.]),
                          size=(36 + j * 9, 18 + j * 2), angle=0., stop=None))
    return items


def position(item, t):
    if item["stop"] is None:
        return item["end"] + item["v"] * t
    dt = t - item["stop"]
    if dt <= 0:
        return item["end"] + item["v"] * dt
    # Dissipação aproximada após contato; não simula deformação mecânica.
    return item["end"] + item["v"] * .045 * (1 - np.exp(-dt / .12))


def degrade(frame, kind, t, impact, point, rng):
    if kind == "rain" and impact - .65 < t < impact + 1.7:
        x, y = point
        x1, x2 = max(0, x - 100), min(480, x + 100)
        y1, y2 = max(0, y - 70), min(320, y + 70)
        region = frame[y1:y2, x1:x2]
        region[:] = cv2.GaussianBlur(region, (19, 19), 6) * .58 + 22
        for _ in range(14):
            rx, ry = int(rng.integers(x1, x2)), int(rng.integers(y1, y2))
            cv2.line(frame, (rx, ry), (rx - 3, ry + 9), (95, 95, 95), 1)
    if kind == "occlusion":
        x, y = point
        # Pilar fixo cobre apenas parte dos veículos e o possível contato.
        cv2.rectangle(frame, (x - 33, y - 28), (x + 3, y + 28), (68, 68, 68), -1)
        cv2.line(frame, (x - 33, y - 28), (x + 3, y + 28), (78, 78, 78), 2)
    return frame


def generate(root=Path("data")):
    videos = root / "videos"
    videos.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, spec in enumerate(SCENES, 1):
        kind, split, duration, impact, point, direction, angle, size, extra = spec
        seed = 561942 + index * 79
        rng = np.random.default_rng(seed)
        actors = vehicles(spec)
        colors = [(105 + j * 3, 164 + j * 2, 202 + j * 2) for j in range(len(actors))]
        if index % 3 == 0:
            colors = [(180, 145, 120), (105, 175, 215)] * 3
        name = f"seq{index:02}.mp4"
        writer = cv2.VideoWriter(str(videos / name), cv2.VideoWriter_fourcc(*"mp4v"), FPS, SIZE)
        if not writer.isOpened():
            raise RuntimeError("Codec mp4v indisponível")
        try:
            for frame_index in range(round(duration * FPS)):
                t = frame_index / FPS
                frame = np.full((SIZE[1], SIZE[0], 3), 45, np.uint8)
                for y in (65, 120, 175, 230, 285):
                    for x in range(0, 480, 55):
                        cv2.line(frame, (x, y), (x + 28, y), (125, 125, 125), 2)
                for j, item in enumerate(actors):
                    rotation = item["angle"]
                    if kind in {"lateral", "rain"} and j == 1:
                        rotation += np.clip(t - impact, 0, .6) * 16
                    box = rectangle(position(item, t), item["size"], rotation).astype(np.int32)
                    cv2.fillConvexPoly(frame, box, colors[j])
                    cv2.circle(frame, tuple(position(item, t).astype(int)), 3, (95, 115, 125), -1)
                frame = degrade(frame, kind, t, impact, point, rng)
                shift = .35 * np.sin(frame_index * .23)
                frame = cv2.warpAffine(frame, np.float32([[1, 0, shift], [0, 1, 0]]),
                                       SIZE, borderMode=cv2.BORDER_REFLECT)
                noise = rng.normal(0, 1.1 if split == "dev" else 1.8, frame.shape)
                writer.write(np.clip(frame.astype(float) + noise, 0, 255).astype(np.uint8))
        finally:
            writer.release()
        manifest.append(dict(video=name, split=split, expected=LABELS.get(kind, "SEM ACIDENTE"),
                             scenario=kind, seed=seed, duration_s=duration, impact_s=impact,
                             impact_xy=point, direction=direction, impact_angle_deg=angle,
                             actors=len(actors), vehicle_sizes_px=[a["size"] for a in actors],
                             similar_colors=index % 3 != 0))
    (root / "labels.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print("GERADOR: 12 vídeos distintos, 6,6–9,4 s, 20 fps, 480x320; 6 dev / 6 final.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data"))
    generate(parser.parse_args().root)
