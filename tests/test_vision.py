import ast
from pathlib import Path
import cv2
import numpy as np
import pytest
from vision.detector import Tracker, velocity, category, EpisodeDeduplicator, analyze
from vision.detector import Detector, PARAMETERS, confidence, indicators


def test_tracker_velocity_and_identity():
    tracker = Tracker()
    ids = []
    for i in range(15):
        frame = np.zeros((140, 200, 3), np.uint8)
        cv2.rectangle(frame, (10+i*3, 60), (50+i*3, 80), (0, 0, 240), -1)
        tracks = tracker.update(frame, i/20)
        assert len(tracks) == 1
        ids.append(tracks[0]["id"])
    assert len(set(ids)) == 1
    assert velocity(tracks[0], .7)[0] == pytest.approx(60, abs=1)


def test_overlapping_stationary_boxes_are_not_collision():
    detector = Detector()
    frame = np.full((320, 480, 3), 45, np.uint8)
    for y in (65, 195, 255):
        cv2.line(frame, (0, y), (479, y), (135, 135, 135), 2)
    cv2.rectangle(frame, (180, 140), (225, 160), (0, 0, 240), -1)
    cv2.rectangle(frame, (220, 145), (265, 165), (240, 80, 0), -1)
    assert all(detector.step(frame, i/20) is None for i in range(100))


@pytest.mark.parametrize("a,b,expected", [([50, 0], [20, 0], "TRASEIRA"), ([50, 0], [-50, 0], "FRONTAL"), ([50, 0], [0, 50], "LATERAL")])
def test_relative_directions(a, b, expected):
    assert category(np.array(a), np.array(b)) == expected


def test_spatiotemporal_deduplication():
    d = EpisodeDeduplicator()
    assert d.accept(3, [220, 160])
    for t in np.arange(3.05, 6, .05):
        assert not d.accept(t, [221, 161])
    assert d.accept(12, [220, 160])
    assert d.accept(12.1, [450, 20])


@pytest.mark.parametrize("filename,expected", [("seq04.mp4", "TRASEIRA"), ("seq08.mp4", "LATERAL"), ("seq11.mp4", "FRONTAL")])
def test_dev_temporal_accidents(filename, expected, tmp_path):
    result = analyze(Path("data/videos")/filename, tmp_path)
    assert result["resultado"] == expected
    assert len(result["events"]) == 1
    e = result["events"][0]
    assert e["evidencia"]["tempo_video_s"] >= 2.4
    assert Path(e["evidencia"]["quadro"]).is_file()


@pytest.mark.parametrize("filename", ["seq01.mp4", "seq07.mp4"])
def test_dev_no_accident(filename, tmp_path):
    result = analyze(Path("data/videos")/filename, tmp_path)
    assert result["resultado"] == "SEM ACIDENTE" and result["events"] == []


def test_low_visibility_explicit_uncertainty(tmp_path):
    result = analyze(Path("data/videos/seq03.mp4"), tmp_path)
    assert result["resultado"] == "INDETERMINADO"
    assert len(result["events"]) == 1
    event = result["events"][0]
    assert event["indicadores"]["veiculos_envolvidos"] >= 2
    assert event["evidencia"]["tempo_video_s"] > 3.6
    assert "contato parcial ou degradado" in event["evidencia"]["observacao"]


def test_confidence_threshold_causes_indeterminate(monkeypatch, tmp_path):
    monkeypatch.setattr("vision.detector.image_quality", lambda frame: .20)
    result = analyze(Path("data/videos/seq04.mp4"), tmp_path)
    assert result["resultado"] == "INDETERMINADO"
    assert result["events"][0]["confianca"]["indice"] < PARAMETERS["confidence_threshold"]


def test_detector_has_no_label_or_generator_dependency():
    source = Path("vision/detector.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert all(not n.startswith("tools") for n in imports)
    assert "labels.json" not in source and "seed" not in [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
    assert "stem" not in [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)]


def test_video_name_does_not_choose_category(tmp_path):
    # Mesmo conteúdo sob nome que sugere outra classe.
    target = tmp_path/"FRONTAL.mp4"
    target.write_bytes(Path("data/videos/seq04.mp4").read_bytes())
    assert analyze(target, tmp_path/"evidence")["resultado"] == "TRASEIRA"

def test_same_color_and_grayscale_tracks_keep_ids():
    for color in [(140, 140, 140), (15, 25, 220)]:
        tracker = Tracker()
        identities = []
        for i in range(20):
            frame = np.full((150, 220, 3), 40, np.uint8)
            cv2.rectangle(frame, (10 + 2*i, 30), (44 + 2*i, 48), color, -1)
            cv2.rectangle(frame, (165 - i, 90), (199 - i, 108), color, -1)
            tracks = sorted(tracker.update(frame, i / 20), key=lambda t: t['xy'][1])
            assert len(tracks) == 2
            identities.append(tuple(t['id'] for t in tracks))
        assert len(set(identities)) == 1
        assert velocity(tracks[0], .95)[0] == pytest.approx(40, abs=2)
        assert velocity(tracks[1], .95)[0] == pytest.approx(-20, abs=2)


def test_merged_blob_reuses_two_predicted_ids():
    tracker = Tracker()
    ids = None
    for i in range(22):
        frame = np.full((130, 240, 3), 40, np.uint8)
        x = min(20 + i*3, 74)
        cv2.rectangle(frame, (x, 50), (x+36, 70), (170, 170, 170), -1)
        cv2.rectangle(frame, (110, 50), (146, 70), (170, 170, 170), -1)
        tracks = tracker.update(frame, i/20)
        current = {t['id'] for t in tracks}
        ids = current if ids is None else ids
        assert current == ids and len(tracks) == 2


def test_confidence_changes_with_each_evidence_term():
    v1, v2 = np.array([60., 0]), np.array([20., 0])
    baseline = confidence(60, .8, .1, .65, v1, v2, 1)[0]
    alternatives = [
        (25, .8, .1, .65, v1, v2, 1),
        (60, .3, .1, .65, v1, v2, 1),
        (60, .8, .5, .65, v1, v2, 1),
        (60, .8, .1, .15, v1, v2, 1),
        (60, .8, .1, .65, v1, np.array([14., 14.]), 1),
        (60, .8, .1, .65, v1, v2, .4),
    ]
    assert all(confidence(*args)[0] < baseline for args in alternatives)


def test_dedup_uses_shared_parameters(monkeypatch):
    monkeypatch.setitem(PARAMETERS, 'dedup_seconds', 2)
    monkeypatch.setitem(PARAMETERS, 'dedup_radius_px', 20)
    dedup = EpisodeDeduplicator()
    assert dedup.accept(0, [50, 50])
    assert not dedup.accept(1, [55, 50])
    assert dedup.accept(1, [80, 50])
    assert dedup.accept(3, [50, 50])


def test_lane_geometry_and_involved_count_are_observed():
    from collections import deque
    def stopped(ident, y):
        contour = np.array([[[90, y-9]], [[130, y-9]], [[130, y+9]], [[90, y+9]]])
        return dict(id=ident, contour=contour, stopped_since=1.,
                    history=deque([(1.8, np.array([110., y])), (1.9, np.array([110., y])),
                                   (2., np.array([110., y]))]))
    shoulder = indicators([stopped(1, 45), stopped(2, 45)], 2)
    lane = indicators([stopped(1, 90), stopped(2, 90), stopped(3, 90)], 2)
    assert shoulder['faixa_possivelmente_obstruida'] == 'nao'
    assert lane['faixas_obstruidas'] == [1]
    assert lane['veiculos_envolvidos'] == 3
    assert lane['tempo_parado_s'] == 1.


def test_manifest_has_distinct_geometry_and_held_out_parameters():
    import json
    rows = json.loads(Path('data/labels.json').read_text(encoding='utf8'))
    assert len(rows) == 12
    assert len({r['duration_s'] for r in rows}) >= 10
    assert len({tuple(r['impact_xy']) for r in rows}) >= 10
    assert len({r['impact_s'] for r in rows}) >= 10
    assert sum(r['actors'] >= 4 for r in rows) >= 5
    assert sum(r['similar_colors'] for r in rows) >= 4
    assert {r['direction'] for r in rows} == {-1, 1}
    assert len({r['impact_angle_deg'] for r in rows if r['scenario'] == 'lateral'}) == 2
    for split in ['dev', 'final']:
        group = [r for r in rows if r['split'] == split]
        assert len(group) == 6
        assert sum(r['expected'] in {'FRONTAL', 'LATERAL', 'TRASEIRA'} for r in group) == 3
