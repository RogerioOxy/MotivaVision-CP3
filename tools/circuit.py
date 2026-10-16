"""Esquema de relatório com posições e ligações lidas do diagram.json do Wokwi."""
import html
import json
from pathlib import Path


def render_circuit(root):
    diagram = json.loads((root / "esp32/diagram.json").read_text(encoding="utf8"))
    parts = {part["id"]: part for part in diagram["parts"]}
    sizes = {"esp": (130, 230), "lcd": (280, 110), "rgb": (62, 75),
             "rr": (80, 30), "rg": (80, 30), "rb": (80, 30),
             "bz": (80, 65), "fault": (95, 60)}
    labels = {"esp": ["ESP32 DevKit v1", "GPIO 25 / 26 / 27", "14 buzzer · 15 botão",
                       "21 SDA · 22 SCL", "VIN · GND comum"],
              "lcd": ["LCD 16×2 I2C 0x27", "SDA 21 · SCL 22", "VCC VIN · GND"],
              "rgb": ["RGB", "R G B", "COM GND"],
              "rr": ["R · 220 Ω"], "rg": ["G · 220 Ω"], "rb": ["B · 220 Ω"],
              "bz": ["Buzzer", "+14 / −GND"], "fault": ["Botão falha", "15 / GND"]}

    def point(ident, dx, dy):
        part = parts[ident]
        return part["left"] + dx, part["top"] + dy

    wires = []

    def wire(start, end, color, offset=0):
        x1, y1 = start
        x2, y2 = end
        middle = (x1 + x2) / 2 + offset
        wires.append(f'<path d="M{x1},{y1} H{middle} V{y2} H{x2}" '
                     f'fill="none" stroke="{color}" stroke-width="2"/>')

    for index, (resistor, color) in enumerate([("rr", "#bc3030"), ("rg", "#207845"), ("rb", "#285ec2")]):
        wire(point("esp", 130, 45 + index * 38), point(resistor, 0, 15), color)
        wire(point(resistor, 80, 15), point("rgb", 10 + index * 20, 75), color, index * 6)
    wire(point("esp", 100, 0), point("lcd", 0, 55), "#207845", 0)
    wire(point("esp", 85, 0), point("lcd", 0, 75), "#285ec2", -14)
    wire(point("esp", 70, 0), point("lcd", 0, 35), "#bc3030", -28)
    wire(point("esp", 130, 185), point("bz", 0, 25), "#bd6b08")
    wire(point("esp", 130, 210), point("fault", 0, 25), "#803b9d")
    # Terra comum desenhado em barramento externo, fora das peças.
    for ident, offset in [("lcd", 95), ("rgb", 60), ("bz", 50), ("fault", 45)]:
        x, y = point(ident, sizes[ident][0], offset)
        wires.append(f'<path d="M{x},{y} H500 V390 H-30 V250 H0" '
                     'fill="none" stroke="#555" stroke-width="1.5"/>')
    blocks = []
    for ident, part in parts.items():
        x, y = part["left"], part["top"]
        width, height = sizes[ident]
        fill = "#14344b" if ident == "esp" else "#fff"
        ink = "#fff" if ident == "esp" else "#14344b"
        blocks.append(f'<g id="{ident}"><rect x="{x}" y="{y}" width="{width}" '
                      f'height="{height}" rx="6" fill="{fill}" stroke="#14344b"/>')
        for index, label in enumerate(labels[ident]):
            dy = 20 + index * (38 if ident == "esp" else 22)
            blocks.append(f'<text x="{x+7}" y="{y+dy}" fill="{ink}">{html.escape(label)}</text>')
        blocks.append('</g>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="900" height="870" '
            'viewBox="-65 -225 620 650"><rect x="-65" y="-225" width="620" height="650" '
            'fill="#eff4f7"/><g font-family="Arial" font-size="11">'
            '<text x="-30" y="-202" font-size="15">Motiva Vision · posições do diagram.json</text>'
            + ''.join(wires + blocks) +
            '<text x="-30" y="410">Esquema funcional, dimensões ilustrativas · terra comum em cinza</text></g></svg>')
