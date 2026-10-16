# Visão, calibração e limites

O detector recebe pixels BGR e tempo decodificado do vídeo. Não importa o gerador nem abre rótulos; não interpreta nome, semente ou metadados de cenário. `tools/evaluate.py` é o único consumidor dos rótulos na cadeia de decisão. Testes e relatório podem ler o manifesto para verificar diversidade e resultados.

## Cenas e protocolo experimental

São 12 vídeos neutros, 20 fps, 480×320, com duração de 6,6 a 9,4 s: seis colisões (duas de cada categoria), quatro negativos e dois ambíguos. Cada conjunto tem três colisões, dois negativos e um ambíguo. Impactos ocorrem entre 2,4 e 5,0 s, em posições diferentes, com sentidos opostos, automóveis e veículos longos, ângulos laterais de 55°/125° e tráfego não envolvido. Há cenas com quatro/cinco veículos e com cores praticamente iguais. `data/labels.json` registra cada parâmetro para auditoria; a classificação não recebe esses dados.

Negativos: passagem em sentidos opostos; frenagem forte com tráfego em outra faixa; veículo parado no acostamento; ultrapassagem rente sem redução brusca de velocidade. No ambíguo dev, os veículos colidem sob chuva, redução local de iluminação e borrão, permanecendo rastreáveis. No final, um pilar encobre parte dos veículos e a região de possível contato; o restante da via permanece visível. As duas cenas exigem raciocínio temporal, sem apagar globalmente a imagem.

A cinemática modela aproximação, contato geométrico, dissipação exponencial, parada e pequena rotação lateral. Não reproduz deformações, pneus ou dinâmica de um veículo real. A câmera é ortográfica e o tremor é subpixel; não há validação em perspectiva ou câmera móvel.

## Segmentação e rastreamento

A mediana espacial de 71×71 do primeiro quadro estima o fundo. Subtração em tons de cinza com diferença >28 e abertura 3×3 remove ruído e marcas finas. Esse fundo permanece fixo para não absorver veículos parados. Não há bin de matiz, classe por cor ou cor reservada a um ator. Um veículo pode ser cinza. Essa escolha é adequada apenas à via sintética uniforme: objetos grandes, fundo com texturas e iluminação variável podem contaminar a estimativa.

Componentes conectados são associados ao centro previsto pela velocidade recente, com penalidade para mudança de área. Se um componente contém dois centros previstos, uma partição espacial recupera os dois rastros. A confiança de visibilidade cai nessa fusão. Não se afirma identidade perfeita sob oclusão longa; o teste de blob fundido é curto e controlado.

## Evidência temporal e confiança

Candidato: distância entre contornos ≤25 px, aproximação radial >12 px/s e ambos os veículos em movimento (>8 px/s). Contato observado acumula somente quando a distância entre contornos é ≤10 px. Aguarda 1,45 s após início do candidato, exige proximidade por ≥0,20 s e razão de velocidade pós/pré ≤0,55. Sem queda de velocidade, aproximação rente não é colisão. Esses portões abrem a análise; não tornam os termos abaixo binários.

Com `clip(z)=min(1,max(0,z))`, os termos contínuos são:

- A = clip((aproximação − 12)/55), em px/s: margem acima da aproximação mínima.
- C = clip(contato_observado_s/0,80): duração da evidência de contato, não simples overlap.
- D = clip(1 − velocidade_pós/velocidade_pré): intensidade da redução de movimento.
- I = clip(tempo_parado_s/0,65): persistência da imobilização pós-evento.
- M = clip((|cos|−0,65)/0,35) para frontal/traseira; clip((0,65−|cos|)/0,65) para lateral: distância das fronteiras angulares.
- Q = nitidez × contraste × visibilidade. Nitidez = clip(variância do Laplaciano/160); contraste = clip((percentil95−percentil20)/85). A imagem é recortada à união dos veículos mais 12 px. Visibilidade compara a área atual à maior área observada e aplica fator 0,85 na divisão de blob fundido.

**S = (0,20 A + 0,20 C + 0,25 D + 0,15 I + 0,20 M) × (0,30 + 0,70 Q).**

S é um índice heurístico [0,1], não probabilidade de acidente, gravidade ou diagnóstico. Todos os termos são registrados no payload. Cos <−0,65 → FRONTAL; cos >0,65 → TRASEIRA; restante → LATERAL. S <0,60 → INDETERMINADO com medidas e motivo no evento. Não há ocorrência automática só porque a qualidade global caiu.

No dev inicial, janela de 0,95 s e limiar de 0,68 produziram 4/6: a decisão antecedia observação suficiente de parada. A janela foi ampliada para 1,45 s e o limiar ficou em 0,60: dev ambíguo 0,284; menor colisão 0,612. A margem de apenas 0,012 da lateral evidencia sensibilidade. Não foi feita otimização estatística: é calibração exploratória em seis simulações. `calibration.json` guarda parâmetros, instante e hashes dos fontes, manifesto e vídeos. O final só roda se esses bytes continuam iguais. Não houve ajuste após os erros finais.

## Indicadores e calibração da via

CAM-SIM-01 usa coordenadas ortográficas fixas. As quatro faixas são os intervalos verticais [65,120), [120,175), [175,230), [230,285) px; dois sentidos por metade da pista. Fora desses intervalos é acostamento. A geometria é uma calibração da cena, não uma detecção universal de faixas. Não convertemos pixels em metros.

A quantidade envolvida começa com o par que perdeu movimento. Outros rastros entram somente se estavam em movimento antes, estão parados depois e ficaram a menos de 100 px da região. Tráfego distante não é somado. Imobilizado = velocidade <10 px/s; tempo parado é observado no histórico. Uma faixa está **possivelmente** obstruída quando pelo menos 30% da altura da caixa do veículo imobilizado a intersecta. Isso não prova bloqueio integral ou impossibilidade de passagem. Os campos incluem quantidade, faixas, imobilização e duração da parada; não há inferência de vítimas.

Matriz ordenada, fictícia e sem valor de protocolo médico:

| Regra | Tipo + evidência | Recurso sugerido para decisão humana |
|---|---|---|
| M0 | INDETERMINADO ou confiança insuficiente | Revisão humana sem concluir tipo/gravidade |
| M1 | FRONTAL, ≥2 envolvidos e imobilização | Avaliação prioritária / resgate simulado |
| M2 | LATERAL e faixa possivelmente obstruída | Ambulância simulada |
| M3 | TRASEIRA e ≥3 envolvidos | Ambulância simulada |
| M4 | TRASEIRA/LATERAL e imobilização, após regras anteriores | Equipe operacional |
| M5 | Nenhuma combinação sustentada | Revisão humana |

A regra disparada é persistida no evento e recalculada pela central. Os testes contrafactuais variam indicadores mantendo o tipo e demonstram mudança de regra. Há regras diferentes realmente exercidas nos vídeos; a avaliação final não foi modificada para completar a matriz.

## Deduplicação e erros observados

Distância de agrupamento <140 px e intervalo <8 s vêm somente de `vision/parameters.py`. O agrupamento é por sessão, não uma identidade global persistente: um episódio muito longo pode repetir depois da janela e dois incidentes próximos podem ser unidos. Cada vídeo com ocorrência nesta execução emitiu um único event_id.

No final, seq02 (lateral junto ao acostamento/topo) retornou SEM ACIDENTE: falso negativo. Seq09 (contato encoberto) também retornou SEM ACIDENTE, em vez de INDETERMINADO. O diagnóstico posterior, sem alterar fontes congelados, registrou **zero candidatos temporais elegíveis nas duas cenas**; `final-diagnostics.json` mostra veículos visíveis, inclusive visibilidade parcial no topo/atrás do pilar. Hipótese: recorte e contato oblíquo/oculto impedem os portões geométricos e cinemáticos antes de chegar ao escore. Não é correto atribuir a segunda falha a um escore baixo: nenhum escore foi emitido. R2 está parcialmente atendido (chuva dev funciona; oclusão final falha). Reduzir cegamente os portões poderia aumentar falsos positivos e não foi tentado após o final.

Nos negativos e nesses dois erros, score é N/A e regra SEM_EVENTO: não existe payload para pontuar. SEM ACIDENTE significa apenas ausência de gatilho neste algoritmo, e o falso negativo mostra por que isso não garante segurança real. A melhoria futura seria uma classe de dúvida por perda temporal localizada de rastros, calibrada em um novo dev e avaliada em um novo conjunto final independente.


## Erro de indicador constatado na integração

Na seq04 há quatro veículos em cena e dois envolvidos no gabarito, mas o evento
registrou `veiculos_envolvidos: 3`. Isso acionou M3/AMBULANCIA_SIMULADA.
O avaliador por tipo conta TRASEIRA como acerto e não mede esse erro.
O agrupamento pode incorporar um rastro próximo/parado ou fragmentado;
a participação causal de cada rastro não foi demonstrada. A causa exata não
foi isolada. Propõe-se gabarito de participação por ator, erro de contagem,
precisão/recall dos envolvidos, obstrução e regra sugerida. Nenhuma alteração
do detector foi feita após a avaliação final. Evidência: JSON da seq04 e
histórico em `docs/evidencias/integracao/`; detalhes em INTEGRACAO.md.
