"""Leitor mínimo de .env: dados literais, sem execução/interpolação."""
import os
from pathlib import Path


def load_env():
    source = Path(__file__).resolve().parents[1]/".env"
    if source.is_file():
        for line in source.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key.replace("_", "").isalnum():
                os.environ.setdefault(key, value)
