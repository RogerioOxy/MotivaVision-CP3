# ESP32 no Wokwi

Firmware executado no simulador em 16/10/2026, 18:37–18:44 (−03:00).
O registro do ensaio indica compilação sem erros e início sem aviso de Wi-Fi;
o log integral de compilação não foi preservado.
Resultados e limites: [INTEGRACAO.md](INTEGRACAO.md). O endereço compartilhável
fica no [cadastro de links, seção Wokwi](LINKS.md#wokwi).

## Recriar o projeto a partir de esp32/

1. No Wokwi, crie um projeto Arduino **ESP32 DevKit v1**.
2. Substitua `sketch.ino`, `diagram.json` e `libraries.txt` pelos três arquivos
   homônimos de `esp32/`. Preserve a montagem do JSON.
3. Use PubSubClient **2.8**, ArduinoJson **7.4.2** e LiquidCrystal I2C.
   A versão exata da última não consta da coleta; registre-a na repetição.
4. Confira Wi-Fi `Wokwi-GUEST`, sem senha, broker `broker.hivemq.com:1883`,
   prefixo `motiva/561942/` igual ao da central.
5. Com rede, inicie `.venv/Scripts/python -m central.app`, compile e inicie
   a simulação. Abra `http://127.0.0.1:5000` e espere NORMAL após heartbeat.
6. Salve na conta do responsável, copie o link compartilhável para o cadastro.

## Ligações

| Pino ESP32 | Componente | Ligação complementar |
|---|---|---|
| GPIO25 | resistor 220 Ω → canal R do RGB | cátodo comum → GND |
| GPIO26 | resistor 220 Ω → canal G do RGB | mesmo GND |
| GPIO27 | resistor 220 Ω → canal B do RGB | mesmo GND |
| GPIO14 | positivo do buzzer piezo | negativo → GND |
| GPIO15 | botão de injeção | outro contato → GND; INPUT_PULLUP |
| GPIO21 | LCD SDA | LCD I2C 0x27, 16×2 |
| GPIO22 | LCD SCL | VCC → VIN/5 V virtual; GND comum |

DevKit alimentado pelo simulador. Não conectar GPIO a 5 V. Buzzer piezo virtual;
carga real maior exigiria estágio de acionamento. SVG segue `diagram.json`:
LCD acima (−180, 180), ESP32 à esquerda (20, 0), resistores em coluna,
RGB à direita (40, 340), buzzer (210, 330), botão (300, 210), posições (top, left).
Fotos mostram a montagem em execução; o SVG é ilustrativo.

## Estados, fila e memória

NORMAL verde; SUSPEITA amarelo preliminar a cada 400 ms; CONFIRMADO vermelho
com buzzer (1 kHz, 150 ms/1,2 s); FALHA roxo a cada 150 ms, tempos do simulador.
LCD mostra estado e cinco caracteres do evento **ativo**, ou traço; segunda
linha: fase e motivo `sem MQTT`, `sem heartbeat` ou `NVS` em FALHA.
Laço usa millis/micros; rede síncrona em tarefa FreeRTOS com backoff.
Uma tarefa inicia Wi-Fi e não repete begin durante tentativa em andamento.

Só um evento sinaliza por vez; todos ficam na central em FIFO persistente.
A dona da fila recebe SUSPEITA automática. CONFIRMAR gera CONFIRMADO;
REJEITAR/ENCERRAR gera NORMAL. A próxima vaga depende de NORMAL/APLICADO.
Rejeição em fila fica registrada e recebe NORMAL quando promovida.
RECUSADO bloqueia avanço para inspeção. Simultaneidade tem testes offline;
não foi exercitada no Wokwi nesta coleta.

Anel de 64 command_ids em NVS; eventos encerrados em lista separada sem expulsão
deliberada. IDs antigos expulsos podem voltar a atuar em evento ainda ativo;
encerrado não reabre enquanto tombstones persistirem. Memória é finita e falha
de gravação causa FALHA. Reinício/NVS/energia e mais de 64 comandos no firmware
continuam sem teste real nesta coleta; o modelo Python não os comprova.

## Repetir os oito testes do enunciado

1. **Categorias:** confrontar seis acidentes das 12 sequências com o gabarito
   separado; dev reconheceu três categorias, lateral final falha.
2. **Negativos:** passagem normal, frenagem, parada no acostamento e aproximação
   rente devem ter zero evento. Na integração seq01 foi publicada sem ocorrência.
3. **Visibilidade:** seq03 deve emitir INDETERMINADO/revisão; seq09 é erro conhecido.
4. **Persistência da ocorrência:** conferir um event_id por episódio e contagens
   do avaliador; executar teste de deduplicação espaço-temporal.
5. **Decisões:** publicar seq04 com `--publish`, esperar SUSPEITA amarela,
   identificar operador fictício e CONFIRMAR. ENCERRAR; publicar seq11 e REJEITAR.
   Conferir NORMAL e histórico. Status 02/03/05/06 e diário documentam a coleta.
6. **Comunicação:** GPIO15 fecha TCP sem DISCONNECT por 15 s do simulador;
   conferir LWT/FALHA/SEM CONTATO e recuperação. Separadamente parar central
   por mais de 7 s do simulador, conferir FALHA por heartbeat e recuperação
   após reinício. Não derrubar o broker público.
7. **Duplicata:** reenviar o mesmo command_id três vezes; ACKs repetidos,
   contador inalterado. Após ENCERRAR, tentar CONFIRMAR mesmo event_id com ID
   de comando novo: RECUSADO sem reabrir.
8. **Cadeia completa:** preservar detector, event_id, command_id, horários
   ENVIADO/RECEBIDO/APLICADO da central e foto do ESP32. Exportar JSON/CSV/status.

Tabelas do relatório são calculadas dos arquivos de evidência e avaliações congeladas.
Latências usam horários da central; simulação rodou a 34%–46%.
Fotos não medem frequências ou tempo real. Para novos ensaios, preserve a coleta
original e guarde arquivos em diretório separado.
