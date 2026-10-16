"""Constrói relatório e matriz de rastreabilidade com tabelas derivadas das execuções locais."""
import html
import json
import os
import re
from pathlib import Path

import cv2
import markdown
import numpy as np
from tools.evaluate import fingerprint
from tools.circuit import render_circuit
from tools.crop_wokwi import crop_all
from tools.report_integration import mandatory_rows, phase_rows

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/relatorio'


def read(path):
    return (ROOT / path).read_text(encoding='utf-8-sig')


def load(path):
    return json.loads(read(path))


def wokwi_link():
    """O cadastro único fornece link direto após ser preenchido."""
    match = re.search(r'https://wokwi\.com/projects/[^\s)]+', read('docs/LINKS.md'))
    if match:
        return f'[Projeto Wokwi]({match.group(0)})'
    return 'PENDENTE_' + 'LINK_WOKWI'


def embed(path):
    """Preserva destinos relativos e subordina títulos ao capítulo do relatório."""
    source = read(path)
    source = re.sub(r'^(#{1,4}) ', r'##\1 ', source, flags=re.M)
    def target(match):
        label, url = match.groups()
        if '://' in url or url.startswith('#'):
            return match.group(0)
        file, sep, fragment = url.partition('#')
        relative = Path(os.path.relpath((ROOT / path).parent / file, OUT)).as_posix()
        return f'[{label}]({relative}{sep}{fragment})'
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', target, source)


def ref(path, anchor):
    for number, line in enumerate(read(path).splitlines(), 1):
        if anchor in line:
            return f'{path}:{number}'
    raise ValueError(f'Âncora não encontrada: {path}: {anchor}')


def table(headers, rows):
    def cells(values, tag):
        return ''.join(f'<{tag}>{html.escape(str(value))}</{tag}>' for value in values)
    body = ''.join('<tr>' + cells(row, 'td') + '</tr>' for row in rows)
    return '<table><thead><tr>' + cells(headers, 'th') + '</tr></thead><tbody>' + body + '</tbody></table>'


def test_result(tests, name):
    matches = [t for t in tests['tests'] if name in t['test']]
    if not matches:
        return 'NÃO EXECUTADO'
    return '; '.join(f"{t['test']}: {t['outcome']}" for t in matches)


def traceability(tests):
    mapping = [
        ('Apresentação acadêmica e links', 'tools/build_report.py', 'def main',
         'test_report_links', 'README e documentos com autoria acadêmica; cadastro Wokwi e link do relatório'),
        ('Ferramentas de operação e repetição', 'tools/operador.py', 'class Operator',
         'test_operator_records', 'tools/reenviar_comando.py; test_replay_preserves_payload_and_filters_ack_ids; README: testes 4 e 5'),
        ('Equivalência de resultados e integridade', 'vision/parameters.py', 'PARAMETERS =',
         'test_frozen_results', 'equivalencia.json: 12/12 tipos, escores e regras idênticos; alteração apenas de comentários'),
        ('Recortes de circuito reproduzíveis', 'tools/crop_wokwi.py', 'def crop_all',
         'test_report_links', 'Cinco recortes, originais preservados e estados agrupados no relatório'),
        ('Registro único da suíte', 'tests/conftest.py', 'def pytest_sessionfinish',
         'test_documentation_evidence', 'pytest.json e pytest.txt; matriz detalhada mantida no repositório'),
        ('D1 — preliminar, rejeição e FIFO persistente', 'central/store.py', 'def _schedule',
         'test_arrival_suspicion_rejection_closes', 'test_fifo_persists; test_queued_rejection; test_fast_decisions; modelos offline'),
        ('D2 — layout compacto e esquema sincronizado', 'esp32/diagram.json', '"id": "lcd"',
         'test_circuit_uses_diagram_positions', 'circuito.svg + 01_wokwi_normal.jpg, montagem em execução fornecida'),
        ('D3 — LCD com evento ativo e motivo', 'esp32/sketch.ino', 'void updateDisplay',
         'test_firmware_display_network_source_contract', '01/02/03/08/09_wokwi: LCD ativo e motivos; fotos recebidas'),
        ('D4 — socket abrupto e contato desatualizado', 'central/transport.py', 'def device_health',
         'test_contact_timeout_calculation', 'Limites offline 7/7,001/39 s; 09_status_1/2: LWT e SEM CONTATO; 09_status_3: recuperado'),
        ('D5 — uma conexão Wi-Fi em andamento', 'esp32/sketch.ino', 'bool wifiConnecting',
         'test_firmware_display_network_source_contract', 'Um WiFi.begin; compilação sem erro/aviso indicada no registro do ensaio, sem log integral'),
        ('D6 — relatório, erros congelados e espaços de evidência', 'docs/INTEGRACAO.md', '## Relógios',
         'test_frozen_results_and_report_contract', '4/6 preservado; docs/INTEGRACAO.md e 35 arquivos recebidos; erro do indicador seq04'),
        ('R1 — 12 situações e dev/final', 'tools/generate.py', 'SCENES =',
         'test_manifest_has_distinct_geometry', 'labels.json e dev/final.json; 6 acidentes/4 negativos/2 ambíguos'),
        ('R2 — ambiguidade temporal parcial', 'tools/generate.py', 'def degrade',
         'test_low_visibility_explicit_uncertainty', 'PARCIAL: chuva dev emite dúvida; oclusão final falha (SEM ACIDENTE)'),
        ('R3 — movimento/fundo, mesma cor', 'vision/detector.py', 'class Tracker',
         'test_same_color_and_grayscale', 'test_merged_blob_reuses_two_predicted_ids; teste sintético curto'),
        ('R4 — confiança contínua e limiar dev', 'vision/detector.py', 'def confidence',
         'test_confidence_changes_with_each_evidence_term', 'calibration.json; termos e Q nos payloads; final preservado'),
        ('R5 — indicadores e matriz variável', 'vision/detector.py', 'def indicators',
         'test_lane_geometry_and_involved_count', 'PARCIAL: seq04 contou 3 envolvidos contra 2 reais e acionou M3; avaliador por tipo não mede isso'),
        ('R6 — anel de comandos', 'esp32/sketch.ino', 'seen_head',
         'test_command_ring_continues_after_64', 'Modelo Python: 90 novos comandos e tombstone após expulsão; NVS sem teste de reinício'),
        ('R6 — RGB/LCD/millis', 'esp32/sketch.ino', 'void actuator',
         'test_firmware_artifacts_contract', '01/02/03/08/09_wokwi: estados reais simulados; buzzer informado, sem áudio'),
        ('R7 — fases e status JSON', 'central/app.py', 'def status_json',
         'test_phase_timestamps_status_json_and_screen', 'SQLite persiste três horários; Flask test_client, sem navegador'),
        ('R8 — legibilidade e decisões', 'vision/detector.py', 'class Detector',
         'test_detector_has_no_label', 'Fontes reestruturados, docs/VISAO.md e comentários no sketch; revisão estática'),
        ('R9 — fonte única de parâmetros', 'vision/parameters.py', 'PARAMETERS =',
         'test_dedup_uses_shared_parameters', 'Visão, deduplicador e recomendação usam PARAMETERS'),
        ('Três categorias por trajetória', 'vision/detector.py', 'def category',
         'test_dev_temporal_accidents', 'Dev 3 categorias; lateral final é FN, sem mascarar resultado'),
        ('SEM ACIDENTE sem gatilho', 'vision/detector.py', 'return dict(resultado=',
         'test_dev_no_accident', 'Avaliador confronta os 4 negativos; final contém erros sem gatilho'),
        ('Nomes neutros e rótulos isolados', 'vision/detector.py', 'def analyze',
         'test_video_name_does_not_choose_category', 'teste AST de dependências e mesmo vídeo renomeado'),
        ('Um event_id por episódio', 'vision/detector.py', 'class EpisodeDeduplicator',
         'test_spatiotemporal_deduplication', 'Uma ocorrência em cada vídeo com evento; UUID e JPG com tempo'),
        ('Contrato MQTT JSON', 'central/protocol.py', 'def validate(',
         'test_event_command_ack_schema', 'docs/PROTOCOLO.md; unidades/QoS/retained/segurança'),
        ('Matriz fictícia e regra calculada na central', 'central/protocol.py', 'def recommendation',
         'test_recommendation_matrix', 'test_event_dedup_and_central_recalculates_recommendation'),
        ('Confirmar/rejeitar com operador e horário', 'central/store.py', 'def decide',
         'test_confirmation_rejection_and_audit', 'Decisão e outbox na mesma transação SQLite'),
        ('ENVIADO não é APLICADO', 'central/store.py', 'def acknowledge',
         'test_sent_is_not_applied', 'Correlação de IDs, retransmissão e ACK atrasado não regridem fase'),
        ('Persistência e exportação', 'central/store.py', 'def snapshot',
         'test_persistence_exports_and_web_operator', 'SQLite reaberto, JSON/CSV e formulário local'),
        ('Timeout e recuperação', 'central/device_sim.py', 'def tick',
         'test_timeout_broker_failure_and_recovery_model', '08_wokwi_falha_sem_heartbeat.jpg; 09_status_1/3.json; diário real recebido'),
        ('Duplicata e não reabrir encerrado', 'central/device_sim.py', 'def command',
         'test_duplicate_command_and_closed_event', '04_acks_duplicado.txt; 05_acks_reabrir.txt; contador 2→2; NVS após reinício não testado'),
        ('Integração vídeo→central→modelo→ACK', 'tests/test_central.py', 'def test_full_offline',
         'test_full_offline_video_mqtt_central_device_ack', 'Offline separado de 02/03_status, detector e 10_historico.json: MQTT_REAL/Wokwi fornecidos'),
        ('Circuito e documentação de entrega', 'esp32/diagram.json', 'wokwi-lcd1602',
         'test_firmware_artifacts_contract', 'HTML A4 gerado; endereço Wokwi centralizado em docs/LINKS.md'),
        ('evidências, figuras e oito testes', 'tools/report_integration.py', 'def mandatory_rows',
         'test_documentation_evidence', 'docs/evidencias/integracao; linhas calculadas dos JSON/TXT, sem resultados editados à mão'),
        ('links e recriação Wokwi', 'docs/WOKWI.md', '## Recriar',
         'test_report_links', 'docs/LINKS.md: único marcador do endereço; esp32 preservado'),
        ('rubrica, limitações e indicador', 'docs/INTEGRACAO.md', '## Erros',
         'test_documentation_evidence', 'Cenas sintéticas, final 4/6, contagem 3≠2, M3 e melhoria proposta; sem alterar detector'),
        ('capa, sumário e A4', 'docs/relatorio/relatorio.html', '@page',
         'test_report_links', 'CSS @page A4, capa, capítulos, limites de figuras e cabeçalho repetido; paginação depende de exportação do HTML'),
        ('suíte e preservação', 'tests/test_integration.py', 'def test_frozen_results',
         'test_frozen_results', 'data/results/pytest.txt e pytest.json; congelamento conferido'),
    ]
    rows = [(req, ref(path, anchor), test_result(tests, test), evidence)
            for req, path, anchor, test, evidence in mapping]
    headers = ['Requisito', 'Implementação arquivo:linha', 'Teste e resultado literal', 'Evidência / limite']
    lines = ['# Rastreabilidade dos requisitos', '',
             'Requisito → implementação → teste → evidência. Resultados individuais em `data/results/pytest.json`; saída da suíte em `data/results/pytest.txt`. Ensaios MQTT/Wokwi de 16/10/2026 em `docs/evidencias/integracao/`.', '',
             '| ' + ' | '.join(headers) + ' |', '|---|---|---|']
    lines += ['| ' + ' | '.join(str(v).replace('|', '/') for v in row) + ' |' for row in rows]
    (ROOT / 'docs/RASTREABILIDADE.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
    return table(headers, rows)


def panel(rows, manifest):
    canvas = np.full((840, 960, 3), 235, np.uint8)
    for index, row in enumerate(sorted(rows, key=lambda r: r['video'])):
        cap = cv2.VideoCapture(str(ROOT / 'data/videos' / row['video']))
        item = next(m for m in manifest if m['video'] == row['video'])
        cap.set(cv2.CAP_PROP_POS_MSEC, (item['impact_s'] + .5) * 1000)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise ValueError('Quadro ausente no painel')
        x, y = index % 3 * 320, index // 3 * 210
        canvas[y:y+185, x:x+320] = cv2.resize(frame, (320, 185))
        label = row['video'] + ' ' + row['obtained']
        cv2.putText(canvas, label, (x+4, y+204), cv2.FONT_HERSHEY_SIMPLEX, .38, (20, 20, 20), 1)
    if not cv2.imwrite(str(OUT / 'painel.jpg'), canvas):
        raise OSError('Falha ao gerar painel')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    seal = load('data/results/calibration.json')
    if seal['fingerprint'] != fingerprint(Path('data')):
        raise RuntimeError('Fontes/vídeos diferem do congelamento; relatório recusado')
    tests = load('data/results/pytest.json')
    rows = load('data/results/dev.json') + load('data/results/final.json')
    manifest = load('data/labels.json')
    panel(rows, manifest)
    traceability(tests)
    summaries = []
    for split in ['dev', 'final']:
        group = [r for r in rows if r['split'] == split]
        summaries.append([split, f"{sum(r['correct'] for r in group)}/{len(group)}",
                          sum(r['false_positive'] for r in group), sum(r['false_negative'] for r in group),
                          sum(r['misclassification'] for r in group),
                          sum(r['obtained'] == 'INDETERMINADO' for r in group)])
    results = table(['Vídeo / conjunto', 'Esperado', 'Obtido', 'Score', 'Regra', 'Acertou', 'Eventos'], [
        [r['video'] + ' / ' + r['split'], r['expected'], r['obtained'],
         r['score'] if r['score'] is not None else 'N/A', r['rule'], r['correct'], r['events']]
        for r in sorted(rows, key=lambda r: r['video'])])
    measured = []
    gallery = []
    for row in rows:
        for event in row['payloads']:
            measured.append([row['video'], event['confianca']['termos'], event['confianca']['qualidade_local'],
                             event['indicadores'], event['evidencia']['observacao']])
            path = '../../' + event['evidencia']['quadro']
            gallery.append(f"<figure><img src='{html.escape(path)}'><figcaption>"
                           f"{row['video']} — {event['tipo']} — "
                           f"{event['evidencia']['tempo_video_s']} s</figcaption></figure>")
    scenarios = table(['Vídeo / conjunto', 'Situação', 'Duração s', 'Referência s', 'Atores'], [
        [m['video'] + ' / ' + m['split'], m['scenario'], m['duration_s'], m['impact_s'], m['actors']]
        for m in manifest])
    required = mandatory_rows(ROOT)
    mandatory = table(['Teste obrigatório', 'Esperado', 'Obtido', 'Evidência', 'Passou'], required)
    phases = table(['Comando', 'Evento', 'ENVIADO', 'RECEBIDO', 'APLICADO', 'Δ enviado→aplicado (s)'], phase_rows(ROOT))
    integration_gallery = []
    device_gallery = []
    crops = crop_all()
    captions = {
        '01_wokwi_normal.jpg': 'Boot concluído: NORMAL verde; LCD sem evento ativo.',
        '02_wokwi_suspeita.jpg': 'SUSPEITA amarela aplicada antes da confirmação humana.',
        '03_wokwi_confirmado.jpg': 'CONFIRMADO vermelho; sinal sonoro registrado no ensaio.',
        '08_wokwi_falha_sem_heartbeat.jpg': 'FALHA roxa por ausência de heartbeat; evento ativo preservado.',
        '09_wokwi_falha_sem_mqtt.jpg': 'FALHA por ausência de MQTT durante injeção local.',
        '02_central_suspeita.png': 'Central real: ocorrência e fases da sinalização preliminar.',
        '03_central_confirmado.png': 'Central real após confirmação por OPERADOR-TESTE-01.',
        '09_central_sem_contato.png': 'Central real: FALHA/SEM CONTATO durante a desconexão injetada.',
    }
    for number, (name, caption) in enumerate(captions.items(), 1):
        path = '../evidencias/integracao/' + name
        kind = 'device' if 'wokwi' in name else 'central'
        image_path = crops.get(name, path)
        source = 'simulador Wokwi' if kind == 'device' else 'central operacional'
        figure = (f'<figure class="integration {kind}"><a href="{path}">'
                  f'<img src="{image_path}" alt="{html.escape(caption)}"></a><figcaption>'
                  f'Figura I{number}. {caption} Captura: {source}, 16/10/2026. '
                  f'<a href="{path}">Original</a>.</figcaption></figure>')
        (device_gallery if kind == 'device' else integration_gallery).append(figure)
    integration_gallery.insert(0, '<div class="device-grid">' + ''.join(device_gallery) + '</div>')
    passing = sum(t['outcome'] == 'passed' for t in tests['tests'])
    pytest_table = table(['Teste', 'Obtido', 'Duração s'], [
        [t['test'], t['outcome'], t['duration_s']] for t in tests['tests']])
    circuit = render_circuit(ROOT)
    (OUT / 'circuito.svg').write_text(circuit, encoding='utf8')
    chapters = f'''
<div class="cover" markdown="1">

# Motiva Vision

<p class="eyebrow">FIAP • EDGE COMPUTING • CP3</p>

<p class="subtitle">Detecção de ocorrências e sinalização viária</p>

**Rogério Deligi Ferreira Filho — RM561942**  
**Maria Fernanda Garavelli Dantas — RM562686**  
Turma 2CCPW • FIAP • Prof. Marcelo Fernando Morgantini • 16/10/2026

Protótipo com dados e recursos fictícios; recomendações não constituem protocolo médico.


Repositório: [RogerioOxy/MotivaVision-CP3](https://github.com/RogerioOxy/MotivaVision-CP3).  
Projeto Wokwi: {wokwi_link()}.

Coleta real do simulador: 16/10/2026, 18:37–18:44 (−03:00).  
Avaliação final preservada: **4/6**. Dados inteiramente sintéticos.

</div>

<div class="contents" markdown="1">

<h2>Sumário</h2>

[TOC]

</div>

## 1. Arquitetura e fronteiras da demonstração

Vídeos sintéticos locais alimentam visão clássica. O detector emite um JSON por episódio,
com tipo, índice heurístico, indicadores e referência a JPG com instante. MQTT entrega
à central Flask; SQLite conserva decisões, outbox e ACKs. Um operador fictício confirma
ou rejeita. A dona da fila recebe SUSPEITA preliminar automaticamente; confirmação
libera CONFIRMADO, rejeição e encerramento liberam NORMAL. FIFO avança após APLICADO.
O ESP32 devolve RECEBIDO/APLICADO. Exportações JSON/CSV não dependem da página aberta.

![Arquitetura](arquitetura.svg)

A cadeia offline usa MQTT em memória e modelo Python do dispositivo. Não comprova
Wi-Fi, broker real, circuito ou firmware. Os 33 arquivos de evidência documentam
o ensaio de 16/10/2026 com o firmware no Wokwi, broker público, central e detector.
O protótipo não foi testado em hardware físico.
Não há clip de evidência; há JPG anotado e vídeo completo para reprodução.

## 2. Visão computacional, categorias e confiança

{embed('docs/VISAO.md')}

## 3. Diversidade dos vídeos

A tabela seguinte é produzida diretamente do manifesto do gerador, sem redigir resultados manualmente.

{scenarios}

![Quadros das doze sequências](painel.jpg)

Quadros extraídos em impacto parametrizado +0,5 s (ou instante de referência nos negativos).
O painel não substitui a reprodução temporal de cada vídeo.

## 4. Circuito, estados e execução

![Esquema do circuito](circuito.svg)

{embed('docs/WOKWI.md')}

## 5. Central, protocolo e segurança

A tela mostra tipo, confiança, indicadores, regra, evidência e decisões com identificação/horário.
ENVIADO (aguardando ESP32), RECEBIDO e APLICADO possuem horários separados, duráveis.
A confirmação humana não prova aplicação elétrica. O endpoint /status.json permite coletar
conexão, último contato, estado recebido e contagens. Testes usam Flask test_client;
as capturas mostram a página real em Edge headless. Acessibilidade
não foi avaliada sistematicamente.

{embed('docs/PROTOCOLO.md')}

## 6. Integração real documentada

{embed('docs/INTEGRACAO.md')}

### Horários das fases na central (−03:00)

{phases}

Valores calculados do histórico JSON recebido. IDs completos permanecem no arquivo
original. O intervalo termina no registro do ACK APLICADO na central.

### Figuras da integração

As imagens abaixo registram o ensaio; clique para abrir o original preservado.
Os JSON/TXT e o diário vinculados na seção anterior completam a evidência.
O [histórico completo da central](../evidencias/integracao/10_central_historico.png)
permanece disponível na captura original e nas exportações JSON/CSV.

{''.join(integration_gallery)}

## 7. Resultados reais: dev separado do final

Congelamento: {seal['timestamp']}. Detector SHA-256: `{seal['detector_sha256']}`.
Hashes de fontes, manifesto e vídeos ficam em calibration.json. O relatório recusa
fontes diferentes do congelamento. O diagnóstico dos erros só lê imagens com o detector
inalterado; não é uma nova calibração. Pesos e limiar foram escolhidos antes do final.

{table(['Conjunto', 'Acertos', 'FP', 'FN', 'Erro de tipo', 'INDETERMINADO'], summaries)}

{results}

FP: categoria de acidente prevista em não acidente/ambíguo. FN: acidente esperado sem
categoria de acidente prevista. Erro de tipo conta separadamente. Erro de abstenção
é ambíguo esperado com outra saída; o de seq09 aparece no acerto geral, não em FN.
N/A indica ausência de evento e portanto de escore; não é índice zero inventado.

Termos completos A/C/D/I/M, qualidade local Q, indicadores e motivo estão nos
payloads de `data/results/dev.json` e `final.json`. A seção de algoritmo define
suas unidades; os quadros anotados estão no Anexo A.

### Oito verificações obrigatórias

{mandatory}

### Suíte automatizada

{passing} testes passaram; código de saída = {tests['exitstatus']}.
O registro completo de cada teste está em `data/results/pytest.json`, e a saída
literal em `data/results/pytest.txt`. A suíte usa transporte em memória,
modelo do dispositivo e cliente de teste Flask; não substitui o ensaio Wokwi.
A [matriz de rastreabilidade](../RASTREABILIDADE.md) relaciona requisitos,
implementações, testes e evidências sem repetir aqui a listagem completa.

## 8. Análise de erros, limitações e melhorias

A avaliação final foi 4/6; não se corrigiu o detector para os dois erros.
O caso lateral de seq02 é um falso negativo. Em seq09, oclusão parcial impediu
expressar a incerteza esperada. O diagnóstico final-diagnostics.json registrou
zero candidatos nas duas cenas e queda de visibilidade de rastros. Não se deve
atribuir ausência de evento a um escore que não chegou a existir. O reconhecimento sob oclusão permanece parcial.
Uma hipótese a investigar num novo ciclo é que contato oblíquo no limite da imagem
e contornos encobertos falham antes dos portões temporais. Não foi validada correção.

As quatro situações negativas não geraram ocorrência; isso não estima segurança
em tráfego real. Dev pequeno, física simplificada, fundo uniforme e conhecimento
da câmera limitam validade externa. Sem probabilidade calibrada, sem diagnóstico,
sem dados de vítimas, sem serviço de emergência acionado. Deduplicação de episódio
é local à sessão, e a visão não tem outbox persistente de eventos. URLs de imagens
requerem arquivos locais no computador da central. O broker público permite forjar
mensagens; validação de IDs não autentica origem.

Melhorias para outro conjunto: teste real autorizado e independente; calibração em
perspectiva; compensação de câmera e iluminação; rastreamento durante oclusão longa;
abstenção por perda localizada de trajetória; identidade durável de episódio; outbox
de eventos; broker privado TLS/autenticação/ACL; testes de energia e NVS e medição
fim a fim com Wokwi. Não são capacidades já verificadas.

**Erro adicional de indicador:** seq04 tem quatro veículos em cena, dois envolvidos;
o evento contou três e acionou M3 (ambulância simulada). O acerto do tipo TRASEIRA
não comprova o indicador nem a recomendação. O agrupamento por proximidade e
movimento pode incluir rastro indevido; a causa exata não foi isolada. Avaliar
contagens, participação por ator, obstrução e regra contra gabarito é melhoria
proposta, sem alterar o detector nesta entrega. Ver análise detalhada na integração.

**Limitações dos ensaios:** ausência de log integral de compilação,
versão exata de LiquidCrystal I2C, áudio e frequência física dos atuadores,
reinício/NVS/energia e FIFO simultânea no Wokwi não foram testados.
A coleta documenta o firmware atual no simulador; não demonstra hardware físico.

## 9. Reprodução, referências e links

As instruções completas estão no README. Na raiz, com .venv existente:

```powershell
.venv/Scripts/python -m pytest -q -p no:cacheprovider --tb=short
.venv/Scripts/python -m tools.build_report
.venv/Scripts/python -m tools.demo
```

A execução dev/final conserva os tipos, escores e regras da avaliação congelada.
A correção de acentuação no comentário de parâmetros não altera o algoritmo;
`data/results/equivalencia.json` registra a comparação e os hashes.

Python 3.14.2; OpenCV 5.0.0; NumPy 2.5.4; paho-mqtt 2.1.0; Flask 3.1.3;
pytest 9.1.1. Requirements fixados; Markdown é usado somente neste construtor.
No Wokwi: PubSubClient 2.8, ArduinoJson 7.4.2 e LiquidCrystal I2C (instalação/versão
exata desta última não registrada na coleta). Abrir HTML no Edge e imprimir A4 com fundos,
sem cabeçalhos/rodapés; inspecionar todas as páginas após exportar.

Referências de implementação (links não consultados na execução offline):

- Enunciado CP3-MORGS.pdf, FIAP/Edge Computing: enunciado da atividade de 16/10/2026.
- [OpenCV](https://docs.opencv.org/): processamento de imagem, contornos e vídeo.
- [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/): transporte MQTT Python.
- [Flask](https://flask.palletsprojects.com/), [SQLite/Python](https://docs.python.org/3/library/sqlite3.html), [pytest](https://docs.pytest.org/).
- [PubSubClient](https://pubsubclient.knolleary.net/api), [ArduinoJson v7](https://arduinojson.org/v7/), [Wokwi](https://docs.wokwi.com/).
- [Repositório](https://github.com/RogerioOxy/MotivaVision-CP3), endereço fornecido; disponibilidade não consultada sem rede.
- [Cadastro Wokwi](../LINKS.md#wokwi); [recriação da montagem](../WOKWI.md).

## Anexo A. Quadros anotados gerados da execução

### Registros de execução e rastreabilidade

Os arquivos [pytest.txt](../../data/results/pytest.txt),
[dev-stdout.txt](../../data/results/dev-stdout.txt) e
[final-stdout.txt](../../data/results/final-stdout.txt) preservam as saídas completas.
A [matriz de rastreabilidade](../RASTREABILIDADE.md) contém a relação detalhada
entre requisitos, implementação, testes e evidências.

<div class="evidence-grid">
{''.join(gallery)}
</div>
'''
    rendered = markdown.markdown(chapters, extensions=['tables', 'fenced_code', 'toc', 'md_in_html'], extension_configs={'toc': {'toc_depth': '2-2'}})
    css = """@page{size:A4;margin:16mm 15mm 17mm}*{box-sizing:border-box}
body{font:10pt/1.48 Arial,sans-serif;color:#193447;max-width:1040px;margin:28px auto;padding:0 16px}
h1{font-size:32pt}h2{font-size:18pt;margin-top:22pt;border-bottom:2px solid #1c647c;padding-bottom:5pt}
h3{font-size:13pt;margin-top:18pt}h4{font-size:11pt;margin-top:14pt}
h1,h2,h3,h4{break-after:avoid}p,li{orphans:3;widows:3}
table{border-collapse:collapse;width:100%;font-size:8pt;line-height:1.35;margin:12px 0;table-layout:fixed}
th,td{border:1px solid #b7cbd6;padding:5px;overflow-wrap:anywhere;vertical-align:top}
th{background:#e5eef3}thead{display:table-header-group}tr{break-inside:avoid}
img{display:block;max-width:100%;max-height:150mm;width:auto;height:auto;margin:0 auto;object-fit:contain}
figure{break-inside:avoid;margin:16px 0}figure img{max-height:135mm}
figure.central img{max-height:110mm}figure.device img{max-height:none;width:100%}
.device-grid{display:grid;grid-template-columns:1fr 1fr;gap:4mm;align-items:start}
.device-grid figure{margin:3mm 0}.device-grid figcaption{font-size:8pt}
.device-grid{break-inside:auto}.device-grid figure:last-child{grid-column:1/3;width:50%;justify-self:center}
.evidence-grid{display:grid;grid-template-columns:1fr 1fr;gap:3mm}
.evidence-grid figure{margin:2mm 0}.evidence-grid img{max-height:58mm}
figcaption{font-size:9pt;margin:8px auto;max-width:165mm}a{color:#006c86;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eff4f7;padding:9px;font-size:8pt}
code{overflow-wrap:anywhere}strong{color:#8c2c17}.eyebrow{letter-spacing:2px;font-size:11pt}
.cover{padding:30mm 8mm 15mm;border-top:8px solid #1c647c;min-height:245mm}
.cover h2{border:0;font-size:19pt}.cover p{font-size:12pt}.cover .subtitle{font-size:19pt}.toc ul{padding-left:18px}
@media print{body{margin:0;padding:0;max-width:none}h2{break-before:page}
.cover{break-after:page}.cover h2,.contents h2{break-before:auto}
.contents{break-after:page}figure.central{break-before:auto}
a{color:inherit}th,pre{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""
    page = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            '<title>Motiva Vision — CP3</title><style>' + css + '</style></head><body>'
            + rendered + '</body></html>')
    (OUT / 'relatorio.html').write_text(page, encoding='utf8')
    print(f'RELATÓRIO: {len(rows)} sequências; {passing} testes aprovados; tabelas e recortes gerados.')


if __name__ == '__main__':
    main()
