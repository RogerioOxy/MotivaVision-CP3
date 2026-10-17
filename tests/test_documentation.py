"""Regressões documentais: proveniência, cobertura honesta e destinos locais."""
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from tools.report_integration import mandatory_rows, phase_rows

ROOT = Path(__file__).resolve().parents[1]


def test_documentation_evidence_matches_supplied_artifacts():
    rows = mandatory_rows(ROOT)
    assert len(rows) == 8
    assert [row[-1] for row in rows] == ['PARCIAL', 'SIM', 'PARCIAL', 'SIM', 'SIM', 'SIM (injeção)', 'SIM', 'SIM']
    assert '5/6' in rows[0][2] and '1/2' in rows[2][2]
    assert '2 → 2' in rows[6][2]
    phases = phase_rows(ROOT)
    assert len(phases) == 7
    assert phases[0] == ['SUSPEITA', 'fed9f', '18:37:41.970', '18:37:43.402', '18:37:43.407', '1.437']
    history = json.loads((ROOT / 'docs/evidencias/integracao/10_historico.json').read_text(encoding='utf8'))
    assert {key: len(value) for key, value in history.items()} == {'events': 3, 'commands': 7, 'decisions': 4, 'acks': 14}
    integration = (ROOT / 'docs/INTEGRACAO.md').read_text(encoding='utf8')
    assert 'M3 / AMBULANCIA_SIMULADA' in integration
    assert '25 s antes' in integration and 'não foram exercitados' in integration


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.images, self.ids, self.text = [], [], set(), []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.add(attrs['id'])
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'img':
            self.images.append(attrs['src'])

    def handle_data(self, text):
        self.text.append(text)


def test_report_links_images_and_single_link_registry():
    report = ROOT / 'docs/relatorio/relatorio.html'
    source = report.read_text(encoding='utf8')
    refs = References()
    refs.feed(source)
    for url in refs.links + refs.images:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc:
            continue
        if not parsed.path:
            assert unquote(parsed.fragment) in refs.ids, url
        else:
            assert (report.parent / unquote(parsed.path)).exists(), url
    assert len([p for p in refs.images if '/integracao/' in p or p.startswith('recortes/')]) >= 8
    for name in ['01_wokwi_normal', '02_wokwi_suspeita', '03_wokwi_confirmado',
                 '08_wokwi_falha_sem_heartbeat', '09_wokwi_falha_sem_mqtt']:
        assert any(name in path for path in refs.images)
    assert '@page{size:A4' in source and 'class="cover"' in source and 'class="toc"' in source
    assert 'Rogério Deligi Ferreira Filho' in source and 'RM562686' in source
    assert '\ufffd' not in source
    project_url = 'https://wokwi.com/projects/478084264348027905'
    assert refs.links.count(project_url) >= 3  # Capa, roteiro e seção de links.
    cover = source.split('<div class="cover">', 1)[1].split('</div>', 1)[0]
    links_section = source.split('Referências de implementação', 1)[1]
    repository_url = 'https://github.com/RogerioOxy/MotivaVision-CP3'
    for section in [cover, links_section]:
        for url in [repository_url, project_url]:
            assert f'<a href="{url}">{url}</a>' in section
    for name in ['README.md', 'docs/LINKS.md', 'docs/WOKWI.md']:
        assert project_url in (ROOT / name).read_text(encoding='utf8'), name
    instructions = (ROOT / 'docs/WOKWI.md').read_text(encoding='utf8')
    assert '## Recriar o projeto a partir de esp32/' in instructions
    assert all(name in instructions for name in ['sketch.ino', 'diagram.json', 'libraries.txt'])
    files = [ROOT / 'README.md', *list((ROOT / 'docs').rglob('*.md')), report, ROOT / 'tools/build_report.py']
    import re
    for path in files:
        assert not re.search(r'PENDENTE[_A-Z]+', path.read_text(encoding='utf8')), path
