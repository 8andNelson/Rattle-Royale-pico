"""Wi-Fi and a small keep-alive HTTP(S) client for the game server.

A TLS handshake takes the Pico W about a second, so the client keeps one
connection open and sends every poll on it. Any failure closes the socket and
the next poll opens a fresh one.
"""

import json
import socket
import time

import network

try:
    import ssl
except ImportError:
    ssl = None


def start_wifi(ssid, password):
    """Start joining Wi-Fi without waiting. Returns the interface."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(ssid, password)
    return wlan


def wait_for_wifi(wlan, timeout_ms=15000):
    start = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), start) > timeout_ms:
            raise RuntimeError("Wi-Fi did not connect. Status " + str(wlan.status()))
        time.sleep_ms(200)
    return wlan.ifconfig()[0]


class Link:
    def __init__(self, url, token, timeout_s=3):
        scheme, _, rest = url.partition("://")
        host, _, prefix = rest.partition("/")
        self._secure = scheme == "https"
        self._host, _, port = host.partition(":")
        self._port = int(port) if port else (443 if self._secure else 80)
        self._prefix = "/" + prefix.strip("/") if prefix.strip("/") else ""
        self._token = token
        self._timeout = timeout_s
        self._sock = None

    def post(self, path, body):
        """Send JSON, return the JSON reply. Raises OSError or ValueError."""
        data = json.dumps(body).encode()
        head = (
            "POST {}{} HTTP/1.1\r\n"
            "Host: {}\r\n"
            "Authorization: Bearer {}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: {}\r\n"
            "User-Agent: rattle-robot\r\n"
            "ngrok-skip-browser-warning: 1\r\n"
            "Connection: keep-alive\r\n\r\n"
        ).format(self._prefix, path, self._host, self._token, len(data))
        if self._sock is None:
            self._open()
        try:
            self._sock.write(head.encode() + data)
            status, keep, reply = self._read_reply()
        except Exception:
            self.close()
            raise
        if not keep:
            self.close()
        if status != 200:
            raise ValueError("Server answered " + str(status) + ": " + reply[:80].decode())
        return json.loads(reply)

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _open(self):
        address = socket.getaddrinfo(self._host, self._port, 0, socket.SOCK_STREAM)[0][-1]
        sock = socket.socket()
        sock.settimeout(self._timeout)
        try:
            sock.connect(address)
            if self._secure:
                sock = wrap_tls(sock, self._host)
        except Exception:
            sock.close()
            raise
        self._sock = sock

    def _read_reply(self):
        line = self._sock.readline()
        if not line:
            raise OSError("The server closed the connection.")
        status = int(line.split(b" ")[1].decode())
        length = None
        chunked = False
        keep = True
        while True:
            line = self._sock.readline()
            if not line:
                raise OSError("The server closed the connection.")
            if line in (b"\r\n", b"\n"):
                break
            name, _, value = line.partition(b":")
            name = name.strip().lower()
            value = value.strip().lower()
            if name == b"content-length":
                length = int(value.decode())
            elif name == b"transfer-encoding" and value == b"chunked":
                chunked = True
            elif name == b"connection" and value == b"close":
                keep = False
        if chunked:
            return status, keep, self._read_chunked()
        if length is None:
            raise OSError("The reply had no length.")
        return status, keep, self._read_exact(length)

    def _read_chunked(self):
        body = b""
        while True:
            size = int(self._sock.readline().split(b";")[0].strip().decode(), 16)
            if size == 0:
                self._sock.readline()
                return body
            body += self._read_exact(size)
            self._sock.readline()

    def _read_exact(self, length):
        body = b""
        while len(body) < length:
            part = self._sock.read(length - len(body))
            if not part:
                raise OSError("The reply was cut off.")
            body += part
        return body


def wrap_tls(sock, host):
    # The certificate is not checked. The token still travels inside TLS.
    if hasattr(ssl, "SSLContext"):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.verify_mode = ssl.CERT_NONE
        return context.wrap_socket(sock, server_hostname=host)
    return ssl.wrap_socket(sock, server_hostname=host)
