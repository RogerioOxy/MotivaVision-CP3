# Integração Wokwi — ensaio de 16/10/2026

## Procedência e condições

O ensaio foi realizado em **16/10/2026, 18:37–18:44 (−03:00)**:
ESP32 DevKit v1 no Wokwi, Wi-Fi Wokwi-GUEST, broker real
`broker.hivemq.com:1883`, central `python -m central.app` com banco novo e
detector com `--publish`. O registro indica compilação sem erro e sem aviso de Wi-Fi
no início, com PubSubClient 2.8, ArduinoJson 7.4.2 e LiquidCrystal I2C
(versão desta última não registrada). Firmware atual, SHA-256 normalizado LF:
`9519de2e242eac577670bf138a4dc4c70cb512824511c7c42d43c9e146804c8c`.

Os **33 arquivos de evidência** estão em [evidencias/integracao/](evidencias/integracao/).
O [diário cronológico](evidencias/integracao/log.txt) registra comandos de coleta.
JSON/TXT preservam resultados e ACKs; fotos mostram o simulador em execução.
As capturas mostram a montagem ampliada do Wokwi e telas da central.
Compilação, ausência de aviso serial e buzzer constam do registro do ensaio;
não há log integral de compilação, áudio ou vídeo contínuo entre as evidências.

## Sequência observada

1. **Boot:** FALHA → NORMAL após Wi-Fi/MQTT/heartbeat, verde,
   LCD `NORMAL - / INICIO`, zero atuações.
   [Foto NORMAL](evidencias/integracao/01_wokwi_normal.jpg) e
   [status inicial](evidencias/integracao/01_status_normal.json).
2. **Preliminar:** seq04 publicou TRASEIRA, confiança 0,727, M3.
   Evento `fed9f35e-9e8d-428b-928d-26bcbd7ed0b5`, SUSPEITA automática aplicada
   antes da decisão: amarelo, LCD `SUSPEITA fed9f / APLICADO`.
   [Detector](evidencias/integracao/02_detector_seq04.json),
   [status](evidencias/integracao/02_status_suspeita.json),
   [central](evidencias/integracao/02_central_suspeita.png) e
   [Wokwi](evidencias/integracao/02_wokwi_suspeita.jpg).
3. **Confirmação:** OPERADOR-TESTE-01 confirmou; CONFIRMADO aplicado,
   vermelho e buzzer relatado, LCD `CONFIRMADO fed9f / APLICADO`, atuações 2.
   [Status](evidencias/integracao/03_status_confirmado.json),
   [central](evidencias/integracao/03_central_confirmado.png) e
   [Wokwi](evidencias/integracao/03_wokwi_confirmado.jpg).
4. **Duplicata:** mesmo command_id reenviado três vezes → três RECEBIDO e
   três APLICADO; contador mantido em 2.
   [ACKs](evidencias/integracao/04_acks_duplicado.txt),
   [status posterior](evidencias/integracao/04_status_apos_duplicado.json) e diário.
5. **Encerramento:** ENCERRAR → NORMAL, sem evento ativo, atuações 3.
   Novo command_id tentando CONFIRMAR o encerrado → três RECUSADO;
   continuou NORMAL e contador 3, conforme diário.
   [Status](evidencias/integracao/05_status_encerrado.json) e
   [ACKs](evidencias/integracao/05_acks_reabrir.txt).
6. **Rejeição:** seq11 FRONTAL em SUSPEITA; REJEITAR → NORMAL,
   atuações 5 e evento REJEITADO.
   [Detector](evidencias/integracao/06_detector_seq11.json),
   [status](evidencias/integracao/06_status_rejeitado.json) e histórico final.
7. **Negativo e dúvida:** seq01 SEM ACIDENTE, zero eventos; seq03
   INDETERMINADO, 0,284, REVISAO_HUMANA/M0, com SUSPEITA preliminar.
   [seq01](evidencias/integracao/07_detector_seq01.json),
   [seq03](evidencias/integracao/07_detector_seq03.json) e histórico.
8. **Heartbeat:** central parada às 18:41:25; ESP32 FALHA, roxo,
   LCD `FALHA 4b1ae / AP sem heartbeat`. Central religada às 18:41:55:
   diário registra 3 eventos, 6 comandos e 3 decisões preservados,
   com recuperação automática para SUSPEITA do evento ativo.
   [Foto](evidencias/integracao/08_wokwi_falha_sem_heartbeat.jpg) e diário.
9. **Indisponibilidade injetada:** botão fecha TCP local sem MQTT DISCONNECT;
   serial INJECAO_FALHA relatado; LCD `FALHA 4b1ae / AP sem MQTT`.
   A central recebeu `origem: LWT` e exibiu FALHA/SEM CONTATO
   (idades 24,2 e 29,6 s). Status 3–8 mostram SUSPEITA/EM CONTATO após reconexão.
   [Foto](evidencias/integracao/09_wokwi_falha_sem_mqtt.jpg),
   [central](evidencias/integracao/09_central_sem_contato.png),
   [LWT](evidencias/integracao/09_status_1.json),
   [segunda leitura](evidencias/integracao/09_status_2.json),
   [recuperação](evidencias/integracao/09_status_3.json).
   O broker público não foi derrubado: a falha foi injetada no cliente ESP32.
10. **Fechamento:** INDETERMINADO revisado e REJEITADO → NORMAL, atuações 7.
    Exportações: 3 eventos, 7 comandos, 4 decisões e 14 ACKs únicos.
    [JSON](evidencias/integracao/10_historico.json),
    [CSV](evidencias/integracao/10_historico.csv),
    [central](evidencias/integracao/10_central_historico.png),
    [status](evidencias/integracao/10_status_final.json).
    ACKs repetidos e tentativa externa de reabertura estão nos TXT próprios;
    não são novas aplicações nem novos comandos criados pela central.

## Relógios e latências

A simulação rodou entre **34% e 46%** da velocidade real. `millis()` e relógio
ESP32 acompanham essa simulação; heartbeat de 7 s e injeção de 15 s são tempos
do simulador. O timeout de contato da central usa 7 s reais.
Mesmo `clock_sync: true` não torna timestamps do ESP32 comparáveis aos do PC.
Latências são diferenças entre fases ENVIADO, RECEBIDO e APLICADO registradas
**na central**, calculadas do histórico final, sem usar uptime ou tempo do vídeo.

SUSPEITA de seq04: ENVIADO 18:37:41.970 → RECEBIDO 18:37:43.402 → APLICADO
18:37:43.407 (−03:00): 1,432 s até recebimento, 1,437 s até aplicação e
0,005 s entre ACKs. Não medem o percurso completo desde o vídeo nem o instante
elétrico. Fotos estáticas não provam frequência do pisca ou continuidade.

Horários do diário indicam quando cada comando de coleta rodou. O botão foi
pressionado aproximadamente 25 s antes da linha `BOTAO INJECAO`, conforme o registro de coleta. A idade inicial de 24,2 s não é latência contada dessa linha.
Não há medição exata do tempo de reação ao botão.

## Erros preservados e melhorias

- **seq02, LATERAL → SEM ACIDENTE:** falso negativo, zero candidatos temporais
  no diagnóstico congelado. Causa provável: contato oblíquo perto da borda e
  perda/fusão de contornos interrompem trajetórias antes dos portões temporais.
  Proposta: manter hipóteses nas bordas e fusões, testar novas laterais independentes.
- **seq09, INDETERMINADO → SEM ACIDENTE:** erro de abstenção, também sem candidato.
  Falta de observação sob oclusão virou ausência de gatilho. Proposta: modelar
  região oculta e perda de rastros após aproximação, pedir revisão humana e
  medir falsos alarmes em negativos com oclusão. Nenhum escore foi emitido.
- **seq04, indicador incorreto:** gabarito: quatro veículos em cena e dois
  envolvidos; evento: `veiculos_envolvidos: 3`. O valor disparou
  **M3 / AMBULANCIA_SIMULADA**. TRASEIRA correta não valida a recomendação.
  Causa provável: inclusão de rastro próximo e imobilizado ou fragmentação/
  associação de rastros; o agrupamento usa proximidade e redução de movimento,
  sem provar participação causal. A identidade do rastro indevido não foi
  reconstruída. Proposta: rotular envolvidos por ator; avaliar erro absoluto
  da contagem, precisão/recall da participação, obstrução e regra recomendada
  contra gabarito. O avaliador atual mede tipo/abstenção e não detecta este erro.

Detector e final **4/6** preservados; são hipóteses explicativas e propostas,
sem correção implementada ou validada.

## Cobertura e limites

Decisões, duplicata, encerramento, heartbeat e LWT têm evidências do simulador
com transporte MQTT_REAL. Fila FIFO simultânea, reinício preservando NVS,
expulsão do anel após 64 comandos, falha de gravação e perda de energia
**não foram exercitados nesta coleta Wokwi**; testes Python e inspeção estática
mantêm sua cobertura limitada. Sem hardware físico ou tráfego real.

As ferramentas [operador.py](../tools/operador.py) e
[reenviar_comando.py](../tools/reenviar_comando.py) permitem reproduzir
as decisões e os ensaios de duplicata. Instruções detalhadas no README. Endereço salvo: [cadastro de links](LINKS.md#wokwi).
