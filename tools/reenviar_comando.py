"""Republica um comando JSON e coleta os ACKs para ensaios de idempotência."""
import argparse
import json
import os
from pathlib import Path
import threading
import time
from central.protocol import TOPICS, validate
from central.transport import configured_client


def replay(command, count=3, interval=1.0, wait=5.0):
    validate(command, 'command')
    ready = threading.Event()
    errors = []
    acknowledgments = []
    client = configured_client('reenvio')

    def connected(connection, userdata, flags, reason, properties):
        if reason.is_failure:
            errors.append(str(reason))
            ready.set()
        else:
            connection.subscribe(TOPICS['ack'], qos=1)

    def subscribed(connection, userdata, mid, reasons, properties):
        if any(reason.is_failure for reason in reasons):
            errors.append('Assinatura de ACK recusada')
        ready.set()

    def message(connection, userdata, packet):
        ack = json.loads(packet.payload.decode('utf8'))
        if (ack.get('command_id'), ack.get('event_id')) == (command['command_id'], command['event_id']):
            acknowledgments.append(ack)

    client.on_connect, client.on_subscribe, client.on_message = connected, subscribed, message
    client.connect(os.getenv('MQTT_HOST', 'broker.hivemq.com'),
                   int(os.getenv('MQTT_PORT', '1883')), keepalive=15)
    client.loop_start()
    try:
        if not ready.wait(10):
            raise TimeoutError('Sem confirmação da assinatura MQTT')
        if errors:
            raise RuntimeError('; '.join(errors))
        payload = json.dumps(command, ensure_ascii=False)
        for index in range(count):
            result = client.publish(TOPICS['comandos'], payload, qos=1, retain=False)
            result.wait_for_publish(timeout=10)
            if not result.is_published():
                raise TimeoutError('Publicação sem confirmação do broker')
            if index + 1 < count:
                time.sleep(interval)
        time.sleep(wait)
    finally:
        client.disconnect()
        client.loop_stop()
    for ack in acknowledgments:
        print('ACK', json.dumps(ack, ensure_ascii=False))
    return acknowledgments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arquivo', type=Path, help='Arquivo contendo um único comando JSON')
    parser.add_argument('--count', type=int, default=3)
    args = parser.parse_args()
    if args.count < 1:
        parser.error('--count deve ser positivo')
    replay(json.loads(args.arquivo.read_text(encoding='utf-8-sig')), args.count)


if __name__ == '__main__':
    main()
