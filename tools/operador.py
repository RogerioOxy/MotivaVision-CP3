"""Consulta a central e registra decisões com identificação do operador."""
import argparse
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request


class Operator:
    def __init__(self, base='http://127.0.0.1:5000'):
        self.base = base.rstrip('/')
        self.client = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(self, path):
        with self.client.open(self.base + path, timeout=10) as response:
            return response.read().decode('utf8')

    def decide(self, event_id, action, operator):
        page = self.get('/')
        token = re.search(r'name="csrf" value="([0-9a-f]+)"', page)
        if token is None:
            raise ValueError('Token do formulário ausente na central')
        body = urllib.parse.urlencode(dict(csrf=token[1], operator=operator, action=action)).encode()
        path = '/decision/' + urllib.parse.quote(event_id, safe='')
        with self.client.open(self.base + path, body, timeout=10) as response:
            return response.read().decode('utf8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:5000')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    commands.add_parser('events')
    decision = commands.add_parser('decide')
    decision.add_argument('event_id')
    decision.add_argument('action', choices=['CONFIRMAR', 'REJEITAR', 'ENCERRAR'])
    decision.add_argument('--operator', default='OPERADOR-TESTE-01')
    args = parser.parse_args()
    client = Operator(args.base)
    if args.command == 'decide':
        print(client.decide(args.event_id, args.action, args.operator))
    else:
        print(json.dumps(json.loads(client.get('/status.json' if args.command == 'status'
                                               else '/export.json')), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
