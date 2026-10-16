"""Interface local; sem autenticação, executar somente em loopback."""
import os
from pathlib import Path
import secrets
from flask import Flask, jsonify, render_template_string, request, session, send_from_directory
from central.store import Store
from central.transport import Bridge

PAGE = """<!doctype html>
<html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<title>Motiva Vision • Central</title>
<style>
body{font:16px system-ui;background:#eef2f5;color:#172b39;margin:0}
header{background:#102b3e;color:white;padding:24px}
main{max-width:1100px;margin:24px auto;padding:0 16px}
article{background:white;padding:22px;margin:18px 0;border-left:5px solid #e9aa22}
img{width:320px;max-width:100%}button,input{font:inherit;padding:8px;margin:4px}
button{cursor:pointer}small{display:block}a{color:#006c86}
.status{padding:14px;background:#dce9f0}.preliminar{background:#fff0b8;padding:8px}
.confirmada{background:#f9d4d4;padding:8px}
</style>
<header><h1>Motiva Vision</h1>Central de demonstração • recursos fictícios</header>
<main><div class="status">
Transporte: {{bridge.mode}} • {{'CONECTADO' if bridge.connected else 'DESCONECTADO'}}
• ESP32: {{health.estado}} • {{health.contato}}<br>
Último contato: {{bridge.last_contact or 'nenhum'}} • idade: {{bridge.contact_age}} s
(mais de {{health.timeout_s}} s = desatualizado) • {{health.motivo}}<br>{{bridge.last_error or ''}}</div>
<p><a href="/status.json">Estado JSON</a> • <a href="/export.json">Histórico JSON</a>
• <a href="/export.csv">Histórico CSV</a> • <a href="/">Atualizar</a>
<label><input id="auto" type="checkbox" checked>Atualizar a cada 5 s</label></p>
<p>Recomendação fictícia: não é protocolo médico e não aciona serviço real.
SUSPEITA é preliminar; CONFIRMADO depende da decisão humana e do ACK do ESP32.</p>
{% for e in data.events %}
<article><h2>{{e.tipo}} • {{e.situacao}}</h2>
<small>{{e.event_id}} • {{e.timestamp}}</small>
<p>{{e.local}} • câmera {{e.camera_id}}</p>
<p>Confiança: {{e.confianca.indice}} • {{e.confianca.nivel}}.
{{e.confianca.definicao}}</p><p>{{e.indicadores}}</p>
<p><strong>Regra {{e.recomendacao.regra}}: {{e.recomendacao.recurso}}</strong><br>
{{e.recomendacao.justificativa}}</p>
{% if e.situacao == 'SUSPEITA' %}
<p class="preliminar">Ocorrência PRELIMINAR • {{e.sinalizacao}}.
{% if e.sinalizacao == 'ATIVA' %}SUSPEITA solicitada: amarelo piscando;
execução depende de APLICADO.{% else %}Aguarda sua vez na fila FIFO, visível nesta tela.{% endif %}</p>
{% elif e.situacao == 'CONFIRMADO' %}
<p class="confirmada">Confirmação HUMANA registrada. A aplicação no ESP32
é demonstrada somente pela fase APLICADO abaixo.</p>{% endif %}
<img src="/evidence/{{e.evidencia.quadro.split('/')[-1]}}" alt="Quadro anotado">
<p>Instante: {{e.evidencia.tempo_video_s}} s. {{e.evidencia.observacao}}</p>
<form method="post" action="/decision/{{e.event_id}}">
<input type="hidden" name="csrf" value="{{csrf}}">
<input name="operator" placeholder="Identificação fictícia do operador" required maxlength="80">
{% if e.situacao == 'SUSPEITA' %}
<button name="action" value="CONFIRMAR" {% if e.sinalizacao != 'ATIVA' %}disabled{% endif %}>Confirmar</button>
<button name="action" value="REJEITAR">Rejeitar</button>
{% elif e.situacao == 'CONFIRMADO' %}
<button name="action" value="ENCERRAR">Encerrar e voltar a NORMAL</button>{% endif %}
</form>
<small>Sinalização: {{e.sinalizacao}}. A fila avança somente após NORMAL/APLICADO.
Rejeição em fila aguarda NORMAL para registrar o encerramento no ESP32.</small>
{% for d in data.decisions if d.event_id == e.event_id %}
<p>{{d.action}} por {{d.operator}} em {{d.timestamp}}</p>{% endfor %}
{% for c in data.commands if c.event_id == e.event_id %}
<div><strong>Comando {{c.id}} • {{c.estado}}</strong>
{% if c.estado == 'SUSPEITA' %}<p class="preliminar">Sinalização só PRELIMINAR: amarelo piscando.</p>
{% elif c.estado == 'CONFIRMADO' %}<p class="confirmada">Alvo de sinalização CONFIRMADA:
vermelho + buzzer. Execução depende da fase APLICADO.</p>
{% endif %}
<ul><li>comando ENVIADO (aguardando ESP32): {{c.phases.get('ENVIADO', 'pendente')}}
{% if c.phase in ['RECEBIDO','APLICADO'] %} • envio já reconhecido{% endif %}</li>
<li>RECEBIDO pelo ESP32: {{c.phases.get('RECEBIDO', 'pendente')}}</li>
<li>APLICADO pelo ESP32: {{c.phases.get('APLICADO', 'pendente')}}</li></ul>
<p>Última fase: {{c.phase}} em {{c.updated}}. Horários acima são da central;
o timestamp original do dispositivo permanece no histórico de ACKs.</p></div>
{% endfor %}</article>
{% else %}<p>Nenhuma ocorrência recebida.</p>{% endfor %}
</main><script>
setInterval(()=>{
  if(document.getElementById('auto').checked &&
     !document.activeElement.matches('input,button')) location.reload();
},5000);
</script></html>"""


def create_app(store=None, bridge=None):
    app = Flask(__name__)
    app.secret_key = secrets.token_bytes(32)
    store = store or Store()
    bridge = bridge or Bridge(store)
    app.config.update(STORE=store, BRIDGE=bridge, MAX_CONTENT_LENGTH=16384)

    @app.get("/")
    def index():
        session.setdefault("csrf", secrets.token_hex(24))
        return render_template_string(PAGE, data=store.snapshot(), bridge=bridge,
                                      health=bridge.device_health, csrf=session["csrf"])

    @app.post("/decision/<event_id>")
    def decision(event_id):
        if not session.get("csrf") or not secrets.compare_digest(request.form.get("csrf", ""), session["csrf"]):
            return "Sessão inválida; atualize a página.", 403
        try:
            store.decide(event_id, request.form.get("action"), request.form.get("operator", ""))
        except ValueError as error:
            return str(error), 409
        return "Decisão registrada. <a href='/'>Voltar à central</a>"

    @app.get("/export.json")
    def export_json():
        return jsonify(store.snapshot())

    @app.get("/status.json")
    def status_json():
        data = store.snapshot()
        return jsonify(
            transporte=bridge.mode, conectado=bridge.connected,
            ultimo_contato=bridge.last_contact, idade_contato_s=bridge.contact_age,
            dispositivo=bridge.device_health, erro=bridge.last_error,
            contagens={key: len(value) for key, value in data.items()},
        )

    @app.get("/export.csv")
    def export_csv():
        return app.response_class(
            store.export_csv(), mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=historico.csv"},
        )

    @app.get("/evidence/<path:name>")
    def evidence(name):
        return send_from_directory(Path("data/evidence").resolve(), name)

    return app


if __name__ == "__main__":
    app = create_app()
    app.config["BRIDGE"].start()
    app.run(host=os.getenv("CENTRAL_HOST", "127.0.0.1"), port=int(os.getenv("CENTRAL_PORT", "5000")), debug=False)
