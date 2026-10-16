# Protocolo Motiva Vision, versão 2

Somente simulação acadêmica com dados fictícios. Broker padrão `broker.hivemq.com:1883`, MQTT 3.1.1, sem TLS nesse endpoint público. Prefixo padrão `motiva/561942/`; alterável no Python por `MQTT_PREFIX` e no firmware pela constante `PREFIX`. Tópicos não são canais privados. Não enviar nomes de pessoas, localizações reais, credenciais ou imagens. No laboratório, identificar operador por código fictício.

| Sufixo | Origem → destino | QoS publicação | Assinatura | Retained |
|---|---|---:|---:|---|
| eventos | visão → central | 1 | 1 | não |
| comandos | central → ESP32 | 1 | 1 | não |
| ack | ESP32 → central | 0 (limite de PubSubClient 2.8) | 1 | não |
| status | ESP32 → central | 0; LWT 1 | 1 | sim |
| heartbeat | central → ESP32 | 1 | 1 | não |

QoS efetivo é o mínimo entre publicador e assinatura. QoS 1 pode duplicar mensagens; não significa atuação exatamente uma vez. ACKs do ESP32 podem se perder: a central reenvia comandos com o mesmo ID a cada dois segundos, e o ESP32 reenvia os dois ACKs sem atuar de novo. A visão aguarda PUBACK do broker, sem afirmar entrega à aplicação central. Eventos não retidos exigem central já assinando. A visão não possui outbox persistente; reiniciar a análise é uma nova sessão.

## Evento

Todos os campos abaixo são obrigatórios e validados em `central/protocol.py`. `SEM ACIDENTE` é resultado de análise sem evento e não é publicado no tópico de ocorrências.

| Campo | Tipo, unidade e valores |
|---|---|
| event_id | string de 1–64 caracteres; UUID no detector; um por episódio na sessão |
| timestamp | ISO 8601 com fuso; instante da detecção no computador, não data real da gravação |
| camera_id | string fictícia; padrão CAM-SIM-01 |
| local | texto fictício, sem geolocalização real |
| tipo | TRASEIRA, FRONTAL, LATERAL, INDETERMINADO |
| confianca.indice | número finito entre 0 e 1, índice heurístico sem calibração probabilística |
| confianca.nivel | ALTA quando índice ≥0,60 (limiar em vision/parameters.py); INSUFICIENTE abaixo |
| confianca.definicao | explicação textual do índice |
| indicadores.veiculos_envolvidos | inteiro de 0 a 5 ou string desconhecido |
| indicadores.faixa_possivelmente_obstruida | sim, nao, desconhecido; hipótese geométrica, não inspeção real da pista |
| recomendacao.regra / recurso / justificativa | strings; a central recalcula pela matriz, ignorando a recomendação recebida |
| estado | SUSPEITA na emissão; estado do evento é controlado separadamente pela central |
| evidencia.quadro | referência a JPG local, nunca conteúdo binário/base64 |
| evidencia.tempo_video_s / frame | segundos desde início e índice de quadro a partir de zero |
| evidencia.observacao | medidas temporais ou justificativa de incerteza |

As imagens precisam estar no mesmo computador da central em `data/evidence/`. O protocolo não transfere arquivos entre máquinas. O detector mede obstrução pela interseção das caixas de veículos
imobilizados com faixas calibradas (limites y=65,120,175,230,285 px).
Interseção de pelo menos 30% da altura marca a faixa; não prova bloqueio integral.
Os indicadores adicionais são `faixas_obstruidas` (lista de 1–4),
`veiculo_imobilizado` (booleano) e `tempo_parado_s` (segundos não negativos).
A quantidade considera o par temporal e rastros próximos que perderam movimento,
sem somar todo o tráfego. `confianca.termos` registra A/C/D/I/M contínuos;
`qualidade_local` é Q [0,1]. Fórmula e matriz M0–M5: docs/VISAO.md.
Nenhuma recomendação é protocolo médico.

## Comando, ACK e estado

Comando JSON: `event_id`, `command_id` (strings 1–64), `timestamp` ISO com fuso, `estado` NORMAL, SUSPEITA ou CONFIRMADO. FALHA é estado autônomo do dispositivo; a central não o comanda. O validador compartilhado admite os quatro estados na representação; o receptor recusa FALHA como comando de atuação.

ACK repete `event_id`, `command_id`, `estado`, `timestamp` e acrescenta `fase`: RECEBIDO (parse e identificação), APLICADO (alvo aplicado pelo controlador) ou RECUSADO (transição/registro não permitido). `clock_sync` indica se o ESP32 obteve horário NTP. Antes de NTP, o timestamp do dispositivo usa época não sincronizada, com fuso +00:00; a central registra separadamente o horário local de recepção. O relógio do vídeo é sempre `tempo_video_s`, separado dos relógios dos computadores.

A central persiste o comando como PENDENTE na mesma transação da decisão. Aceitação pelo cliente MQTT marca ENVIADO; esse estado não é confirmação do broker nem do atuador. O ACK RECEBIDO avança a fase; apenas APLICADO correspondente ao estado solicitado conclui. ACK desconhecido, event_id incompatível e estado aplicado incompatível são recusados. Repetições são idempotentes e ACK atrasado não regride APLICADO. RECUSADO termina retransmissões automáticas e exige inspeção do operador.

O recebimento de uma ocorrência cria uma entrada FIFO persistente em SQLite.
A primeira ocupa o sinalizador e gera SUSPEITA automaticamente. Todas aparecem
na tela; somente a dona da sinalização pode ser confirmada. CONFIRMAR envia
CONFIRMADO; REJEITAR envia NORMAL e registra REJEITADO; ENCERRAR após confirmação
envia NORMAL e registra ENCERRADO. Operador e horário ficam no histórico.
O formulário repetido não cria outro comando. A próxima entrada só ocupa o ESP32
após NORMAL/APLICADO da anterior, nunca apenas ENVIADO ou RECEBIDO.

Uma ocorrência em espera pode ser rejeitada imediatamente na central, mas seu
NORMAL aguarda a vaga: quando promovida, recebe só NORMAL, que registra o evento
encerrado no dispositivo sem acender a preliminar. A fila então avança após o ACK.
Assim nenhuma ocorrência some da tela, nem uma rejeição reabre depois.
A fila e a outbox sobrevivem ao reinício. A migração de histórico anterior conserva
comandos/decisões existentes e prioriza ocorrência confirmada sobre suspeitas antigas.
Um único comando fica em voo: SUSPEITA deve receber APLICADO antes de enviar
CONFIRMADO ou NORMAL posteriores, inclusive quando o operador decide rapidamente.
RECUSADO bloqueia a outbox para inspeção; não há avanço automático ou reset de histórico.

ESTADOS: NORMAL = verde; SUSPEITA = amarelo intermitente preliminar antes da decisão;
CONFIRMADO = vermelho + pulso sonoro; FALHA = roxo a cada 150 ms (amarelo: 400 ms).
MQTT perdido ou heartbeat >7 s do simulador leva a FALHA; recuperar exige MQTT e
heartbeat novo, restaurando o alvo anterior. Não encerra silenciosamente.
O LCD usa o evento ativo, ou “-” se vazio, nunca o evento do último ACK.
Na FALHA, a segunda linha abrevia a fase (AP/RC/NG/IN) e mostra sem MQTT,
sem heartbeat ou NVS. Fora da FALHA, mostra a fase completa.

## Deduplicação e persistência

- Evento na visão: agrupamento por distância <140 pixels e intervalo <8 segundos, na mesma sessão. Os vídeos duram 6,6–9,4 s, com uma região principal de ocorrência. Em produção, acidente longo ou nova sessão exige persistência/identidade mais sofisticada; a janela atual pode unir eventos próximos ou emitir outro após oito segundos.
- Evento na central: chave primária event_id, mensagem repetida não sobrescreve decisão humana.
- Comando: ID único criado uma vez por decisão, guardado na outbox SQLite. Repetições preservam os IDs.
- Firmware: anel NVS de 64 command_ids recentes; ao lotar substitui o mais
  antigo e continua recebendo. ID recente só devolve ACK sem repetir ação.
  Eventos encerrados ficam numa lista separada, nunca expulsa pelo anel. Não há
  limite deliberado de 32 eventos; NVS é finita e falha de gravação causa FALHA
  sem esquecer tombstones. A restauração limita o blob a 24 KiB: exceder exige
  manutenção supervisionada. Não apagar a memória durante a demonstração.
  Um command_id antigo expulso pode repetir atuação em evento ainda ativo;
  a garantia é dos 64 recentes. Event_id encerrado recusa reabertura por qualquer ID.
- Modelo Python: mesma janela de 64 recentes e tombstones separados, só em memória.
  Não emula flash, energia, capacidade física ou eletrônica.

Status a cada dois segundos do simulador, retido, com LWT FALHA/offline.
O botão fecha o socket TCP sem MQTT DISCONNECT por 15 s do simulador, permitindo
ao broker emitir LWT; não derruba o broker público. Status retido e LWT não
renovam o último contato vivo. A central mede idade com relógio monotônico real:
ausência de contato, idade >7 s, offline/LWT ou transporte desconectado mostram
SEM CONTATO/FALHA tanto na página quanto no JSON. Novo contato vivo recupera o
estado observado. Heartbeat da central a cada dois segundos reais, não retido.
Client_ids têm sufixo aleatório; o ESP32 inclui parte do ID do chip.
Broker/prefixo devem coincidir. Latências usam horários da central: INTEGRACAO.md.

## Escopo de segurança

`.env` é ignorado no Git, `.env.example` contém apenas padrões públicos e vazios. Usuário/senha do MQTT podem ser configurados no cliente Python, mas o endpoint público em 1883 não protege esses valores em trânsito. Não usar credenciais privadas nele. Não há autenticação de origem no broker público: qualquer cliente pode forjar tráfego no prefixo. Isso impede uso operacional real; isolar prefixo e usar somente simulação. A página local usa escape HTML e token de formulário, mas não possui autenticação de usuários. Não publicar a central na internet.


## Fases persistentes e estado HTTP

`command_phases` conserva o primeiro horário local de ENVIADO, RECEBIDO e APLICADO
por command_id, inclusive após reiniciar. O ACK original mantém também o timestamp
do dispositivo. ENVIADO é aceitação pelo cliente MQTT, não PUBACK nem atuação.
A tela mostra cada etapa como pendente até haver registro.

`GET /status.json` retorna `transporte`, `conectado`, `ultimo_contato`,
`idade_contato_s`, `dispositivo`, `erro` e `contagens` de eventos/comandos/decisões/ACKs.
`dispositivo` contém estado efetivo calculado, `contato`, `desatualizado`,
`timeout_s`, `motivo` e `ultimo_status` (payload original, que pode estar antigo).
Assim `dispositivo.estado=FALHA` pode coexistir com `ultimo_status.estado=NORMAL`.
É evidência do que a central observou, não autenticação do dispositivo.

No broker público **qualquer pessoa pode publicar nos nossos tópicos**, inclusive
forjar comandos e ACKs com IDs conhecidos. Validação de esquema, correlação de IDs,
deduplicação e ausência de imagens reduzem erros e exposição, mas não autenticam origem.
Em produção: broker privado com TLS, autenticação de cada cliente e ACL por tópico.
