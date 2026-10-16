"""Recorta a montagem das capturas Wokwi, preservando os arquivos originais."""
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['01_wokwi_normal', '02_wokwi_suspeita', '03_wokwi_confirmado',
         '08_wokwi_falha_sem_heartbeat', '09_wokwi_falha_sem_mqtt']


def crop_all():
    output = ROOT / 'docs/relatorio/recortes'
    output.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in NAMES:
        source = cv2.imread(str(ROOT / 'docs/evidencias/integracao' / (name + '.jpg')))
        if source is None:
            raise ValueError(f'Captura ausente: {name}')
        # Todas as capturas têm o mesmo enquadramento: circuito entre as
        # barras superiores do simulador e a área branca do monitor serial.
        gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        # A margem direita do monitor fica livre de texto: ela identifica
        # a divisória sem incluir uma linha serial cortada no recorte.
        white_rows = (gray[:, 340:365] > 235).mean(axis=1)
        bottom = next(y for y in range(450, len(source)) if white_rows[y] > .75)
        crop = source[210:bottom, :355]
        path = output / (name + '.png')
        if not cv2.imwrite(str(path), crop):
            raise OSError(f'Não foi possível salvar {path}')
        paths[name + '.jpg'] = 'recortes/' + path.name
    return paths


if __name__ == '__main__':
    for name, path in crop_all().items():
        print(f'{name} -> {path}')
