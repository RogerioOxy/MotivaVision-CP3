"""Reprodutibilidade do checkout e do congelamento, sem rede ou commits."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tools import evaluate

ROOT = Path(__file__).resolve().parents[1]


def test_windows_checkout_uses_lf_and_preserves_binary_assets(tmp_path):
    shutil.copyfile(ROOT / '.gitattributes', tmp_path / '.gitattributes')
    (tmp_path / 'sample.py').write_bytes(b'first\r\nsecond\r\n')
    binary = b'\x00\xff\r\n\x01\n'
    names = [f'asset.{ext}' for ext in
             ('mp4', 'jpg', 'jpeg', 'png', 'pdf', 'sqlite', 'MP4', 'JPG')]
    for name in names:
        (tmp_path / name).write_bytes(binary)

    def git(*args):
        return subprocess.run(
            ['git', '-c', 'core.autocrlf=true', '-C', str(tmp_path), *args],
            check=True, capture_output=True, text=True,
        ).stdout

    git('init', '--quiet')
    git('add', '--', '.gitattributes', 'sample.py', *names)
    checkout = tmp_path / 'checkout'
    git('checkout-index', '--all', f'--prefix={checkout.as_posix()}/')
    assert (checkout / 'sample.py').read_bytes() == b'first\nsecond\n'
    assert all((checkout / name).read_bytes() == binary for name in names)
    attributes = git('check-attr', 'text', 'diff', 'merge', '--', *names)
    assert all(f'{name}: {attr}: unset' in attributes
               for name in names for attr in ('text', 'diff', 'merge'))


def test_fingerprint_ignores_only_text_crlf_and_detects_real_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(evaluate, 'FROZEN_SOURCES', ['source.py'])
    root = Path('data')
    (root / 'videos').mkdir(parents=True)
    source = Path('source.py')
    manifest = root / 'labels.json'
    video = root / 'videos' / 'clip.mp4'
    source.write_bytes(b'value = 1\n')
    manifest.write_bytes(b'[]\n')
    video.write_bytes(b'\x00\r\n\xff')
    lf = evaluate.fingerprint(root)
    assert lf[video.as_posix()] == hashlib.sha256(video.read_bytes()).hexdigest()
    source.write_bytes(b'value = 1\r\n')
    manifest.write_bytes(b'[]\r\n')
    assert evaluate.fingerprint(root) == lf
    source.write_bytes(b'value = 2\r\n')
    assert evaluate.fingerprint(root)['source.py'] != lf['source.py']
    manifest.write_bytes(b'[1]\r\n')
    assert evaluate.fingerprint(root)['manifest'] != lf['manifest']
    video.write_bytes(b'\x00\n\xff')
    assert evaluate.fingerprint(root)[video.as_posix()] != lf[video.as_posix()]


def test_dev_final_equivalence_after_hash_migration(tmp_path, monkeypatch):
    # Run the actual evaluator against isolated copies; preserve sealed artifacts.
    for name in evaluate.FROZEN_SOURCES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    shutil.copytree(ROOT / 'data/videos', tmp_path / 'data/videos')
    shutil.copyfile(ROOT / 'data/labels.json', tmp_path / 'data/labels.json')
    results = tmp_path / 'data/results'
    results.mkdir()
    shutil.copyfile(ROOT / 'data/results/calibration.json', results / 'calibration.json')
    monkeypatch.chdir(tmp_path)

    def stable(value):
        if isinstance(value, dict):
            return {k: stable(v) for k, v in value.items()
                    if k not in {'event_id', 'timestamp', 'quadro', 'processing_s'}}
        if isinstance(value, list):
            return [stable(v) for v in value]
        return value

    comparisons = []
    for split, correct in [('dev', 6), ('final', 4)]:
        reference = json.loads((ROOT / f'data/results/{split}.json').read_text(encoding='utf-8'))
        obtained = evaluate.evaluate(Path('data'), split)
        assert stable(obtained) == stable(reference)
        assert len(obtained) == 6 and sum(r['correct'] for r in obtained) == correct
        comparisons.extend(dict(video=r['video'], split=split, obtained=r['obtained'],
                                score=r['score'], rule=r['rule'], identical=True)
                           for r in obtained)

    seal = json.loads((results / 'calibration.json').read_text(encoding='utf-8'))
    assert seal['parameters'] == evaluate.PARAMETERS
    assert seal['fingerprint'] == evaluate.fingerprint(Path('data'))
    # Even a full CRLF text checkout must still pass the final freeze guard.
    for name in [*evaluate.FROZEN_SOURCES, 'data/labels.json']:
        path = Path(name)
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
    assert seal['fingerprint'] == evaluate.fingerprint(Path('data'))
    # A real source edit must fail before analysis.
    with Path('vision/parameters.py').open('ab') as file:
        file.write(b'\n# real edit\n')
    with pytest.raises(RuntimeError, match='congelamento'):
        evaluate.evaluate(Path('data'), 'final')
    report = dict(semantics_identical=True, parameters_identical=True,
                  excluded_volatile_fields=['event_id', 'timestamp', 'quadro', 'processing_s'],
                  comparisons=comparisons)
    (tmp_path / 'eol-equivalence.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
