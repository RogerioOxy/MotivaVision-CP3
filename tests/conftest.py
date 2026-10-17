import json
from pathlib import Path
import tempfile

import pytest
from central.protocol import now, recommendation

RESULTS = []


@pytest.fixture
def tmp_path():
    """Temporários isolados dentro do projeto."""
    root = Path("tests/test-tmp").resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=root) as folder:
        yield Path(folder)


@pytest.fixture
def event():
    result = dict(
        event_id="evt-test-001", timestamp=now(), camera_id="CAM-TEST",
        local="Rodovia fictícia, km 1", tipo="TRASEIRA", estado="SUSPEITA",
        confianca=dict(indice=.95, nivel="ALTA", definicao="Índice heurístico não probabilístico"),
        indicadores=dict(veiculos_envolvidos=2, faixa_possivelmente_obstruida="sim",
                         veiculo_imobilizado=True, tempo_parado_s=1.0),
        evidencia=dict(quadro="data/evidence/test.jpg", tempo_video_s=3.5,
                       observacao="Evidência de teste"),
    )
    result["recomendacao"] = recommendation(result)
    return result


def pytest_runtest_logreport(report):
    if report.when == "call" or report.failed:
        RESULTS.append(dict(
            test=report.nodeid, outcome=report.outcome, duration_s=round(report.duration, 5),
            evidence=str(report.longrepr) if report.failed else "Asserções executadas pelo pytest",
        ))


def pytest_sessionfinish(session, exitstatus):
    target = Path("data/results")
    target.mkdir(parents=True, exist_ok=True)
    result = dict(exitstatus=int(exitstatus), tests=RESULTS)
    (target / "pytest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
