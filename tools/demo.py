"""Central interativa inteiramente offline; não estabelece conexão MQTT real."""
import argparse
from pathlib import Path
import threading
import time
from central.app import create_app
from central.device_sim import Device
from central.protocol import TOPICS, now
from central.store import Store
from central.transport import Bridge, MemoryBus
from vision.detector import analyze


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=Path("data/videos/seq04.mp4"))
    args = parser.parse_args()
    store, bus = Store("data/runtime/demo.sqlite"), MemoryBus()
    bridge = Bridge(store, bus)
    device = Device(bus)
    for event in analyze(args.video)["events"]:
        bus.publish(TOPICS["eventos"], event)
    start = time.monotonic()

    def run():
        while True:
            device.tick(time.monotonic()-start)
            bridge.tick()
            status = dict(estado=device.state, event_id=device.active, timestamp=now(),
                          actions=device.actions, origem="MODELO_PYTHON_OFFLINE")
            bus.publish(TOPICS["status"], status)
            time.sleep(2)

    threading.Thread(target=run, daemon=True).start()
    print("DEMONSTRAÇÃO OFFLINE: MQTT em memória e modelo Python, sem ESP32/Wokwi.")
    create_app(store, bridge).run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
