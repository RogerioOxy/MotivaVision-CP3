"""Leitura documental das evidências fornecidas; não executa rede nem o detector."""
import json
from datetime import datetime
from pathlib import Path


def mandatory_rows(root):
    """Resultados calculados dos artefatos, inclusive requisitos parcialmente falhos."""
    folder = root / 'docs/evidencias/integracao'

    def load(name):
        return json.loads((folder / name).read_text(encoding='utf-8-sig'))

    rows = []
    for split in ['dev', 'final']:
        rows.extend(json.loads((root / f'data/results/{split}.json').read_text(encoding='utf8')))
    accidents = [r for r in rows if r['expected'] in {'FRONTAL', 'LATERAL', 'TRASEIRA'}]
    negatives = [r for r in rows if r['expected'] == 'SEM ACIDENTE']
    ambiguous = [r for r in rows if r['expected'] == 'INDETERMINADO']
    emitted = [r for r in rows if r['payloads']]
    history = load('10_historico.json')
    commands = history['commands']
    decisions = history['decisions']
    status = lambda name: load(name)['dispositivo']['ultimo_status']
    confirmed = status('03_status_confirmado.json')
    duplicate = status('04_status_apos_duplicado.json')
    closed = status('05_status_encerrado.json')
    rejected = status('06_status_rejeitado.json')
    offline = load('09_status_1.json')
    recovered = load('09_status_3.json')
    acks = [(json.loads(line.removeprefix('ACK '))) for line in
            (folder / '04_acks_duplicado.txt').read_text(encoding='utf8').splitlines() if line]
    refusal = [json.loads(line.removeprefix('ACK ')) for line in
               (folder / '05_acks_reabrir.txt').read_text(encoding='utf8').splitlines() if line]
    command_ids = {c['id'] for c in commands if c['phase'] == 'APLICADO'}
    audited = (set(d['action'] for d in decisions) >= {'CONFIRMAR', 'REJEITAR', 'ENCERRAR'}
               and all(d['operator'] and d['timestamp'] for d in decisions)
               and len(command_ids) == 7 and rejected['estado'] == 'NORMAL')
    idempotent = (confirmed['actions'] == duplicate['actions'] == 2
                  and sum(a['fase'] == 'APLICADO' for a in acks) == 3
                  and sum(a['fase'] == 'RECEBIDO' for a in acks) == 3
                  and sum(a['fase'] == 'RECUSADO' for a in refusal) == 3
                  and closed['estado'] == 'NORMAL' and closed['event_id'] == '')
    communication = (offline['dispositivo']['estado'] == 'FALHA'
                     and offline['dispositivo']['ultimo_status'].get('origem') == 'LWT'
                     and offline['dispositivo']['contato'] == 'SEM CONTATO'
                     and recovered['dispositivo']['estado'] == 'SUSPEITA'
                     and recovered['dispositivo']['contato'] == 'EM CONTATO')
    chain = (load('02_detector_seq04.json')['events'][0]['event_id'] == confirmed['event_id']
             and confirmed['estado'] == 'CONFIRMADO' and len(command_ids) == 7)
    count = lambda group: f"{sum(r['correct'] for r in group)}/{len(group)}"
    return [
        ('1. Três categorias', 'Reconhecer seis acidentes, dois de cada tipo.',
         f"{count(accidents)}; dev 3/3, final 2/3; seq02 LATERAL → SEM ACIDENTE.",
         'data/results/dev.json; final.json; tests/test_vision.py::test_dev_temporal_accidents',
         'SIM' if all(r['correct'] for r in accidents) else 'PARCIAL'),
        ('2. Tráfego sem acidente', 'Quatro negativos sem ocorrência.',
         f"{count(negatives)}; {sum(r['events'] for r in negatives)} eventos nos negativos.",
         'data/results/dev.json; final.json; 07_detector_seq01.json',
         'SIM' if all(r['correct'] and not r['events'] for r in negatives) else 'NÃO'),
        ('3. Visibilidade prejudicada', 'Explicitar INDETERMINADO e revisão humana.',
         f"{count(ambiguous)}; seq03 0,284/M0; seq09 → SEM ACIDENTE.",
         '07_detector_seq03.json; data/results/final.json',
         'SIM' if all(r['correct'] for r in ambiguous) else 'PARCIAL'),
        ('4. Ocorrência persistente', 'Um event_id por episódio nas sequências.',
         f"{len(emitted)} sequências com evento; contagens: {[r['events'] for r in emitted]}.",
         'data/results/dev.json; final.json; tests/test_vision.py::test_spatiotemporal_deduplication',
         'SIM' if all(r['events'] == 1 and len({p['event_id'] for p in r['payloads']}) == 1 for r in emitted) else 'NÃO'),
        ('5. Decisões humanas', 'Confirmar/rejeitar, identificar operador e aplicar.',
         f"{len(decisions)} decisões; {len(command_ids)} comandos APLICADO; rejeição → NORMAL ({rejected['actions']} atuações).",
         '03_status_confirmado.json; 06_status_rejeitado.json; 10_historico.json',
         'SIM' if audited else 'NÃO'),
        ('6. Comunicação indisponível', 'FALHA e recuperação automática.',
         f"LWT/{offline['dispositivo']['contato']}; idade {offline['idade_contato_s']} s; depois SUSPEITA/EM CONTATO. Heartbeat: foto + diário.",
         '08_wokwi_falha_sem_heartbeat.jpg; 09_status_1.json; 09_status_3.json; log.txt',
         'SIM (injeção)' if communication else 'NÃO'),
        ('7. Comando duplicado', 'ACK repetido sem repetir atuação; encerrado não reabre.',
         f"3 RECEBIDO + 3 APLICADO; atuações {confirmed['actions']} → {duplicate['actions']}; reabertura: 3 RECUSADO, NORMAL.",
         '04_acks_duplicado.txt; 04_status_apos_duplicado.json; 05_acks_reabrir.txt; log.txt',
         'SIM' if idempotent else 'NÃO'),
        ('8. Integração completa', 'Vídeo → MQTT → central → ESP32 → ACK.',
         f"seq04 TRASEIRA → SUSPEITA → CONFIRMADO; {len(history['events'])} eventos, {len(commands)} comandos e {len(history['acks'])} ACKs no fechamento.",
         '02_detector_seq04.json; 02_status_suspeita.json; 03_status_confirmado.json; 10_historico.json',
         'SIM' if chain else 'NÃO'),
    ]


def phase_rows(root):
    history = json.loads((root / 'docs/evidencias/integracao/10_historico.json').read_text(encoding='utf8'))
    rows = []
    for command in history['commands']:
        phases = command['phases']
        sent, received, applied = [datetime.fromisoformat(phases[p]) for p in ['ENVIADO', 'RECEBIDO', 'APLICADO']]
        rows.append([command['estado'], command['event_id'][:5],
                     sent.strftime('%H:%M:%S.%f')[:-3], received.strftime('%H:%M:%S.%f')[:-3],
                     applied.strftime('%H:%M:%S.%f')[:-3],
                     f'{(applied-sent).total_seconds():.3f}'])
    return rows
