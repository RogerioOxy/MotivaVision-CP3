# Motiva Vision — CP3 Edge Computing

FIAP • 2CCPW • Prof. Marcelo Fernando Morgantini • 16/10/2026

- Rogério Deligi Ferreira Filho — RM561942 (responsável pela entrega)
- Maria Fernanda Garavelli Dantas — RM562686

Protótipo acadêmico: vídeo sintético → visão temporal → MQTT → central com decisão humana → ESP32 → ACK. Recursos fictícios, sem diagnóstico e sem serviço real. A ocorrência ativa envia SUSPEITA amarela antes da decisão; CONFIRMAR libera vermelho/buzzer, REJEITAR ou ENCERRAR envia NORMAL.

Os **33 arquivos de evidência de integração** registram o ensaio de
16/10/2026, 18:37–18:44 (−03:00), com firmware ESP32,
Wokwi, HiveMQ público, central real e detector `--publish`. Foram observados
NORMAL, SUSPEITA preliminar, CONFIRMADO, rejeição/encerramento, duplicata sem
nova atuação, FALHA por heartbeat e por corte TCP com LWT, e recuperação.
Fechamento: **3 eventos, 7 comandos, 4 decisões, 14 ACKs únicos**.
[Diário e evidências](docs/INTEGRACAO.md). O registro inclui capturas,
JSON, CSV e confirmações MQTT; não inclui o log integral de compilação.

Detector, sequências e resultados permanecem congelados: dev **6/6**, final
**4/6**. Seq02 lateral é falso negativo; seq09 ocluída perdeu a abstenção.
Seq04 contou **3 envolvidos contra 2 do gabarito**, acionando M3 indevidamente;
o avaliador por tipo não mede esse indicador. Dados sintéticos, broker público
sem autenticação e simulação a **34%–46%** limitam a validade dos resultados.
Análise e melhorias propostas: [integração](docs/INTEGRACAO.md) e [visão](docs/VISAO.md).

Resultados gerados em `data/results/`: `dev.md`, `final.md`, JSON/CSV,
`calibration.json` e `pytest.txt`. Tabelas não são editadas à mão.
[Relatório HTML A4](docs/relatorio/relatorio.html), com figuras locais embutidas,
sumário e oito testes obrigatórios calculados dos artefatos. [Rastreabilidade](docs/RASTREABILIDADE.md).
Repositório: https://github.com/RogerioOxy/MotivaVision-CP3.
O **único local para preencher o link compartilhável do Wokwi** é
[docs/LINKS.md, seção Wokwi](docs/LINKS.md#wokwi).
Há [instruções para recriar o projeto a partir de esp32/](docs/WOKWI.md).

## Estrutura

```text
vision/              detector.py e parameters.py (calibração única)
central/             Flask, SQLite, MQTT e modelo Python do dispositivo
esp32/               sketch.ino, diagram.json e libraries.txt
tools/               generate, evaluate, demo e construtor documental do relatório
tests/               testes sem rede; temporários em data/results/test-tmp/
data/videos/         seq01.mp4–seq12.mp4
data/labels.json     parâmetros e rótulos separados da visão
data/evidence/       JPGs com instante e marcação da região
data/results/        execuções, congelamento e diagnóstico dos erros
docs/                VISAO, PROTOCOLO, WOKWI, LINKS, RASTREABILIDADE, evidências e relatório HTML
```

## Ambiente

Python 3.14.2; opencv-python 5.0.0; numpy 2.5.4; paho-mqtt 2.1.0; Flask 3.1.3; pytest 9.1.1. `requirements.txt` fixa as dependências diretas. O renderizador Markdown instalado só é necessário ao relatório. Não há modelo treinado ou download durante os testes.

Neste PC use `.venv/Scripts/python`, preservando `.venv/`. Em outra máquina, com rede, crie um ambiente e instale `requirements.txt`. Configuração opcional: `.env.example` → `.env`; variáveis do processo prevalecem. Não colocar credenciais reais em arquivos públicos. A execução dos testes não requer instalação nem acesso à rede.

O `.gitattributes` força LF no checkout dos textos, mesmo com `core.autocrlf=true`; vídeos, imagens, PDF e SQLite são binários, e os hashes de fontes/manifesto normalizam CRLF para LF (migração registrada em `calibration.json`).

## Reproduzir offline

Na raiz, em PowerShell:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python -m tools.generate
.venv/Scripts/python -m tools.evaluate --split dev --freeze
.venv/Scripts/python -m tools.evaluate --split final
.venv/Scripts/python -m pytest -q -p no:cacheprovider --tb=short
.venv/Scripts/python -m tools.build_report
```

O gerador reescreve os 12 vídeos. O congelamento guarda hashes de fontes, parâmetros, manifesto e vídeos. A avaliação final recusa alterações posteriores. Para uma nova pesquisa, use um novo conjunto final; repetir o mesmo final após ajustar o detector não é uma validação independente. UUIDs e horários de novas execuções mudam; classes e escores são determinísticos no mesmo ambiente.

A fixture `tmp_path` cria e remove pastas isoladas em `data/results/test-tmp/`.
Não utilize `--basetemp` relativo ou dentro do repositório.

Os testes cobrem: três categorias dev, negativos dev, chuva com dúvida temporal, nomes neutros, mesma cor/cinza, blob fundido, evidências contínuas, geometria de faixa, parâmetros compartilhados, matriz variável, contratos JSON, decisão humana, persistência/exportação, timeout e recuperação do modelo, 90 comandos novos após o anel lotar, duplicata recente e tombstone, fases e JSON de estado, integração offline completa. Os quatro negativos e os seis acidentes também são confrontados pelo avaliador, independentemente de passarem nos testes dev. Testes não usam rótulos finais para ajustar o detector.

Para apenas reconstruir o relatório, execute pytest e build_report.
A geração e o avaliador reescrevem os resultados; preserve os arquivos de referência
antes de iniciar outro experimento. O conjunto final existente não deve orientar ajustes.

## Central e MQTT

```powershell
.venv/Scripts/python -m tools.demo
# demonstração local sem broker: abrir http://127.0.0.1:5000

.venv/Scripts/python -m central.app
# com rede, broker e Wokwi disponíveis:
.venv/Scripts/python -m vision.detector data/videos/seq04.mp4 --publish
```

`tools.demo` usa SQLite separado em `data/runtime/demo.sqlite`, MQTT em memória e modelo Python. `central.app` usa `data/central.sqlite` e MQTT real configurável. Não executar os dois na mesma porta. Identifique o operador com código fictício. A primeira ocorrência gera SUSPEITA; confirmar gera CONFIRMADO; rejeitar e encerrar geram NORMAL. FIFO avança após NORMAL/APLICADO. Rejeição em fila aguarda sua vez para registrar encerramento no ESP32, mantendo decisão na tela. Histórico anterior é migrado preservando decisões e comandos.

A central diferencia ENVIADO (cliente MQTT aceitou), RECEBIDO e APLICADO, com horário local de cada fase. Nenhum ACK prova integridade física do LED. SUSPEITA é automática. Um comando fica em voo; RECUSADO bloqueia a fila para inspeção. `/status.json` fornece conexão, último contato/idade, estado efetivo calculado e contagens. Silêncio >7 s reais mostra SEM CONTATO/FALHA; `dispositivo.ultimo_status` preserva o payload original. JSON/CSV preservam histórico; atualizar não perde dados.

A central é local e sem autenticação de usuário: bind padrão 127.0.0.1. Broker público permite que qualquer pessoa publique nos tópicos; validação e IDs não autenticam origem. Apenas dados fictícios e referência de JPG, nunca imagem no MQTT. Produção exigiria broker privado com TLS/autenticação e ACL por tópico. Leia `docs/PROTOCOLO.md`.

## ESP32 e relatório

Importe os três arquivos de `esp32/` no Wokwi; siga `docs/WOKWI.md`. GPIO25/26/27 = RGB com resistores; 14 = buzzer; 15 = botão; 21/22 = SDA/SCL LCD 16×2 0x27. NORMAL verde, SUSPEITA amarelo lento, CONFIRMADO vermelho+buzzer, FALHA roxo rápido. Loop usa millis/micros; rede em tarefa separada com backoff. LCD mostra evento ativo ou “-”, fase e motivo na FALHA. Botão fecha TCP sem DISCONNECT. Medir latências pelos horários da central, pois o relógio do ESP32 acompanha a simulação.

Comandos vistos ocupam anel de 64 entradas em NVS; eventos encerrados permanecem em lista separada sem expulsão. Não há parada deliberada ao 65º comando. Memória física é finita: falha de gravação causa FALHA, sem apagar tombstones. IDs muito antigos expulsos do anel de eventos ainda ativos podem voltar a atuar; encerrados não reabrem enquanto NVS é preservada. NVS e energia precisam de teste real.

Reconstrua o relatório após pytest, usando os resultados congelados do avaliador. Abra o HTML no Edge e imprima A4, com fundos e sem cabeçalhos/rodapés. Inspecione a paginação após exportar o PDF. As figuras e tabelas de integração já usam a coleta real recebida.
O relatório usa caminhos relativos: mantenha `docs/` e `data/` juntos na cópia.
Os utilitários `tools/operador.py` e `tools/reenviar_comando.py` apoiam os ensaios descritos abaixo.
FIFO simultânea, reinício/NVS, energia e anel >64 no firmware não foram
exercitados nesta coleta Wokwi. A compilação sem erro e o buzzer são relatos
fornecidos, sem log integral de compilação/áudio no pacote.

## Reproduzir os testes 4 e 5 do ensaio de integração

Estes números correspondem à sequência de `docs/INTEGRACAO.md`:
4 = duplicata; 5 = encerramento e tentativa de reabertura. Requerem rede,
central MQTT ativa e o ESP32 no Wokwi conectado ao mesmo prefixo.
Os utilitários aceitam a configuração MQTT da central em `.env`.

Prepare uma ocorrência e confirme-a:

```powershell
.venv/Scripts/python -m vision.detector data/videos/seq04.mp4 --publish
.venv/Scripts/python -m tools.operador events
# Copie o event_id exibido para a variável abaixo:
$eventoTeste = 'EVENT_ID_EXIBIDO'
.venv/Scripts/python -m tools.operador decide $eventoTeste CONFIRMAR --operator OPERADOR-TESTE-01
.venv/Scripts/python -m tools.operador status
```

Espere `CONFIRMADO` no ESP32 e fase `APLICADO` na central. No teste 4,
salve exatamente o payload já aplicado, incluindo seu `command_id`:

```powershell
New-Item -ItemType Directory -Force data/runtime/reproducao | Out-Null
$historicoTeste = (.venv/Scripts/python -m tools.operador events | ConvertFrom-Json)
$comandoTeste = $historicoTeste.commands | Where-Object {
    $_.event_id -eq $eventoTeste -and $_.estado -eq 'CONFIRMADO' -and $_.phase -eq 'APLICADO'
} | Select-Object -Last 1
if (-not $comandoTeste) { throw 'Espere a aplicação de CONFIRMADO antes de continuar' }
$comandoTeste.payload | Set-Content -Encoding utf8 data/runtime/reproducao/comando.json
.venv/Scripts/python -m tools.operador status
.venv/Scripts/python -m tools.reenviar_comando data/runtime/reproducao/comando.json --count 3
.venv/Scripts/python -m tools.operador status
```

Compare `dispositivo.ultimo_status.actions` antes/depois: deve permanecer igual.
Cada reenvio deve devolver RECEBIDO e APLICADO com os mesmos IDs. O utilitário
imprime apenas ACKs correspondentes ao comando enviado.

No teste 5, encerre, espere NORMAL/APLICADO e tente confirmar novamente o mesmo
evento com um `command_id` novo:

```powershell
.venv/Scripts/python -m tools.operador decide $eventoTeste ENCERRAR --operator OPERADOR-TESTE-01
.venv/Scripts/python -m tools.operador status
# Continue somente após NORMAL, sem event_id ativo:
$reaberturaTeste = Get-Content -Raw data/runtime/reproducao/comando.json | ConvertFrom-Json
$reaberturaTeste.command_id = [guid]::NewGuid().ToString()
$reaberturaTeste.timestamp = [DateTimeOffset]::Now.ToString('o')
$reaberturaTeste | ConvertTo-Json | Set-Content -Encoding utf8 data/runtime/reproducao/reabertura.json
.venv/Scripts/python -m tools.reenviar_comando data/runtime/reproducao/reabertura.json --count 3
.venv/Scripts/python -m tools.operador status
```

Esperado: três ACKs RECUSADO, estado NORMAL, evento ativo vazio e nenhuma atuação
adicional após o encerramento. Guarde status, ACKs e exportações em um diretório
novo, preservando as evidências de 16/10/2026.
