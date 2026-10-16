"""Avaliação offline; único consumidor de labels.json na cadeia de decisão."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import time

from central.protocol import now
from vision.detector import analyze, PARAMETERS

FROZEN_SOURCES = ['vision/detector.py', 'vision/parameters.py', 'central/protocol.py',
                  'tools/generate.py', 'tools/evaluate.py']


def sha256(path, *, text=False):
    content = Path(path).read_bytes()
    if text:
        content = content.replace(b'\r\n', b'\n')
    return hashlib.sha256(content).hexdigest()


def detector_hash():
    return sha256('vision/detector.py', text=True)


def fingerprint(root):
    sources = {name: sha256(name, text=True) for name in FROZEN_SOURCES}
    sources['manifest'] = sha256(root / 'labels.json', text=True)
    sources.update({p.as_posix(): sha256(p) for p in sorted((root / 'videos').glob('*.mp4'))})
    return sources


def evaluate(root, split, freeze=False):
    output = root / 'results'
    output.mkdir(parents=True, exist_ok=True)
    seal_path = output / 'calibration.json'
    current_fingerprint = fingerprint(root)
    if split == 'final':
        seal = json.loads(seal_path.read_text(encoding='utf-8'))
        if seal['fingerprint'] != current_fingerprint or seal['parameters'] != PARAMETERS:
            raise RuntimeError('Fontes, vídeos ou parâmetros alterados após congelamento')
    manifest = json.loads((root / 'labels.json').read_text(encoding='utf-8'))
    rows, console = [], []
    for item in manifest:
        if item['split'] != split:
            continue
        start = time.perf_counter()
        result = analyze(root / 'videos' / item['video'], root / 'evidence')
        elapsed = time.perf_counter() - start
        expected, obtained = item['expected'], result['resultado']
        accident = {'TRASEIRA', 'FRONTAL', 'LATERAL'}
        events = result['events']
        row = dict(
            video=item['video'], split=split, scenario=item['scenario'],
            expected=expected, obtained=obtained, correct=obtained == expected,
            events=len(events),
            score=events[0]['confianca']['indice'] if events else None,
            rule=events[0]['recomendacao']['regra'] if events else 'SEM_EVENTO',
            false_positive=obtained in accident and expected not in accident,
            false_negative=expected in accident and obtained not in accident,
            misclassification=expected in accident and obtained in accident and obtained != expected,
            processing_s=round(elapsed, 3), video_s=result['duration_s'],
            evidence=[e['evidencia'] for e in events], payloads=events,
        )
        rows.append(row)
        score = f"{row['score']:.3f}" if row['score'] is not None else 'N/A'
        line = (f"{split:5} {item['video']} esperado={expected:13} obtido={obtained:13} "
                f"eventos={row['events']} score={score} regra={row['rule']} "
                f"{'ACERTOU' if row['correct'] else 'ERROU'}")
        console.append(line)
        print(line)
    (output / f'{split}.json').write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
    columns = [key for key in rows[0] if key != 'payloads']
    with (output / f'{split}.csv').open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.DictWriter(file, columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    lines = ['| Vídeo | Esperado | Obtido | Acertou | Score | Regra | Eventos |',
             '|---|---|---|---|---:|---|---:|']
    for row in rows:
        lines.append(f"| {row['video']} | {row['expected']} | {row['obtained']} | "
                     f"{row['correct']} | {row['score']} | {row['rule']} | {row['events']} |")
    (output / f'{split}.md').write_text('\n'.join(lines), encoding='utf-8')
    summary = (f"RESUMO {split}: {sum(r['correct'] for r in rows)}/{len(rows)} corretos; "
               f"FP={sum(r['false_positive'] for r in rows)}; "
               f"FN={sum(r['false_negative'] for r in rows)}; "
               f"erros_tipo={sum(r['misclassification'] for r in rows)}; "
               f"INDETERMINADO={sum(r['obtained']=='INDETERMINADO' for r in rows)}")
    print(summary)
    console.append(summary)
    if freeze and split == 'dev':
        seal = dict(detector_sha256=detector_hash(), fingerprint=current_fingerprint,
                    hash_policy='SHA-256: fontes e manifesto com CRLF convertido em LF; vídeos em bytes crus.',
                    parameters=PARAMETERS, timestamp=now(),
                    basis='Somente seis dev: Q fraca 0,284; menor colisão 0,612. Limiar 0,60.',
                    development='Janela 0,95→1,45 s; limiar inicial 0,68→0,60; nenhum final consultado.')
        seal_path.write_text(json.dumps(seal, indent=2, ensure_ascii=False), encoding='utf-8')
        message = f'CONGELADO detector_sha256={detector_hash()}'
        print(message)
        console.append(message)
    (output / f'{split}-stdout.txt').write_text('\n'.join(console) + '\n', encoding='utf-8')
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('data'))
    parser.add_argument('--split', choices=('dev', 'final'), required=True)
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    evaluate(args.root, args.split, args.freeze)
