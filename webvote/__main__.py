import argparse
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from webvote.server import serve  # noqa: E402


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def main():
    ap = argparse.ArgumentParser(prog='webvote', description='Выбор вариантов имён — веб-сервис')
    ap.add_argument('--data', required=True, help='папка результата «Прослушки» (имена.json, вариант_1…)')
    ap.add_argument('--port', type=int, default=8080)
    ap.add_argument('--host', default='0.0.0.0', help='0.0.0.0 — доступен в локальной сети; 127.0.0.1 — только этот компьютер')
    ap.add_argument('--cert')
    ap.add_argument('--key')
    a = ap.parse_args()
    if not os.path.exists(os.path.join(a.data, 'имена.json')):
        sys.exit('В папке нет «имена.json» — сначала «Синтезировать три варианта» в Прослушке.')
    srv = serve(a.data, a.host, a.port, a.cert, a.key)
    sch = 'https' if a.cert else 'http'
    print(f'Выбор вариантов запущен: {sch}://{lan_ip() if a.host == "0.0.0.0" else a.host}:{a.port}/   (Ctrl+C — остановить)')
    if not a.cert and a.host == '0.0.0.0':
        print('Внимание: без HTTPS пароли идут по сети открытым текстом — только внутренняя сеть / VPN.')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
