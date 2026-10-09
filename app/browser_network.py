"""HTTPS egress proxy: resolve once, reject private addresses, connect numeric IP.

Chromium never resolves the destination itself. Redirects and subresources pass
through the same guard, including CONNECT tunnels. No request/cookie logging.
"""
import ipaddress
import select
import socket
import socketserver
import threading
from urllib.parse import urlsplit


def public_addresses(host):
    if not host or host.lower().endswith(('.internal', '.localhost', '.local')):
        raise ValueError('Destino privado bloqueado')
    addresses = sorted({r[4][0] for r in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError('Destino privado bloqueado')
    return addresses


def public_url(value):
    url = urlsplit(str(value))
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.port not in (None, 443):
        raise ValueError('Solo URLs HTTPS públicas, sin credenciales ni puertos especiales')
    public_addresses(url.hostname)
    return str(value)


class Tunnel(socketserver.StreamRequestHandler):
    def handle(self):
        upstream = None
        try:
            self.connection.settimeout(15)
            first = self.rfile.readline(4096).decode('ascii').strip().split()
            if len(first) != 3 or first[0] != 'CONNECT':
                raise ValueError('HTTPS requerido')
            host, port = first[1].rsplit(':', 1)
            if port != '443':
                raise ValueError('Puerto bloqueado')
            for _ in range(100):
                line = self.rfile.readline(8192)
                if line in (b'\r\n', b'\n', b''):
                    break
            else:
                raise ValueError('Cabeceras demasiado grandes')
            addresses = public_addresses(host.strip('[]'))
            # Numeric IP prevents a second DNS resolution / rebinding.
            upstream = socket.create_connection((addresses[0], 443), timeout=15)
            self.connection.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            transferred = 0
            while True:
                ready, _, _ = select.select([self.connection, upstream], [], [], 30)
                if not ready:
                    break
                for origin in ready:
                    data = origin.recv(65536)
                    if not data:
                        return
                    transferred += len(data)
                    if transferred > 32 * 1024 * 1024:
                        return
                    (upstream if origin is self.connection else self.connection).sendall(data)
        except (OSError, ValueError, UnicodeError):
            try:
                self.connection.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
            except OSError:
                pass
        finally:
            if upstream:
                upstream.close()


class Proxy(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_proxy():
    server = Proxy(('127.0.0.1', 0), Tunnel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
