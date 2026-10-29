"""Zero-dependency pure Python client for macOS usbmuxd.

Directly communicates with `/var/run/usbmuxd` using the binary plist protocol
over UNIX domain socket to discover devices and forward TCP ports. No Node.js,
no npm, no appium-ios-device dependency required.
"""
from __future__ import annotations

import obslog
import os
import plistlib
import select
import signal
import socket
import struct
import sys
import threading
import time
from typing import Optional

USBMUX_SOCKET_PATH = "/var/run/usbmuxd"
PROG_NAME = "dsh-iphone-use"
CLIENT_VERSION = "python-usbmux-1.0"


def _send_plist(sock: socket.socket, payload: dict) -> None:
    data = plistlib.dumps(payload)
    # Header: length (4 bytes), version=1 (4 bytes), request=8 (plist, 4 bytes), tag=1 (4 bytes)
    header = struct.pack("<IIII", len(data) + 16, 1, 8, 1)
    sock.sendall(header + data)


def _recv_plist(sock: socket.socket, timeout: float = 5.0) -> dict:
    sock.settimeout(timeout)
    hdr = b""
    while len(hdr) < 16:
        chunk = sock.recv(16 - len(hdr))
        if not chunk:
            raise ConnectionError("usbmuxd closed connection while reading header")
        hdr += chunk
    length, version, msg_type, tag = struct.unpack("<IIII", hdr)
    body_len = length - 16
    body = b""
    while len(body) < body_len:
        chunk = sock.recv(body_len - len(body))
        if not chunk:
            raise ConnectionError("usbmuxd closed connection while reading body")
        body += chunk
    return plistlib.loads(body)


def list_devices(socket_path: str = USBMUX_SOCKET_PATH) -> list[dict]:
    """Return all currently attached iOS devices discovered via usbmuxd."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(socket_path)
        _send_plist(sock, {
            "MessageType": "ListDevices",
            "ClientVersionString": CLIENT_VERSION,
            "ProgName": PROG_NAME,
        })
        resp = _recv_plist(sock)
        devices = []
        for item in resp.get("DeviceList", []):
            props = item.get("Properties", {})
            devices.append({
                "device_id": item.get("DeviceID"),
                "udid": props.get("SerialNumber"),
                "connection_type": props.get("ConnectionType"),
                "product_id": props.get("ProductID"),
            })
        return devices
    finally:
        sock.close()


def connect_device_port(
    udid: Optional[str],
    device_port: int,
    socket_path: str = USBMUX_SOCKET_PATH,
    timeout: float = 5.0,
) -> socket.socket:
    """Establish a direct raw TCP stream to a device port over usbmuxd.
    
    Returns a connected socket that can be used directly for HTTP/MJPEG communication.
    """
    devices = list_devices(socket_path)
    target_device = None
    if udid:
        for d in devices:
            if d.get("udid") == udid:
                target_device = d
                break
    elif devices:
        target_device = devices[0]

    if not target_device:
        raise ConnectionError(f"Target iOS device {udid or '(any)'} not found in usbmuxd")

    device_id = target_device["device_id"]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(socket_path)
        _send_plist(sock, {
            "MessageType": "Connect",
            "ClientVersionString": CLIENT_VERSION,
            "ProgName": PROG_NAME,
            "DeviceID": device_id,
            "PortNumber": socket.htons(device_port),
        })
        resp = _recv_plist(sock, timeout=timeout)
        if resp.get("Number") != 0:
            error_code = resp.get("Number")
            raise ConnectionError(f"usbmuxd connect failed with error code: {error_code}")
        # Connection succeeded: sock is now a transparent bi-directional byte stream
        sock.settimeout(None)
        return sock
    except Exception:
        sock.close()
        raise


def run_forwarder(udid: str, local_port: int, device_port: int, stop_event: Optional[threading.Event] = None) -> None:
    """Listen on 127.0.0.1:local_port and forward connections to device_port via usbmuxd."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", local_port))
    server.listen(64)
    server.settimeout(0.5)

    def pipe(src: socket.socket, dst: socket.socket, done: threading.Event) -> None:
        try:
            while not done.is_set():
                r, _, _ = select.select([src], [], [], 0.5)
                if not r:
                    continue
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            done.set()
            try: src.close()
            except OSError: pass
            try: dst.close()
            except OSError: pass

    threads: list[threading.Thread] = []

    try:
        while stop_event is None or not stop_event.is_set():
            try:
                client_sock, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                device_sock = connect_device_port(udid, device_port)
            except Exception as exc:
                obslog.log_event("forwarder_connect_failed", device_port=device_port, error=type(exc).__name__)
                client_sock.close()
                continue

            done = threading.Event()
            t1 = threading.Thread(target=pipe, args=(client_sock, device_sock, done), daemon=True)
            t2 = threading.Thread(target=pipe, args=(device_sock, client_sock, done), daemon=True)
            t1.start()
            t2.start()
            threads.append(t1)
            threads.append(t2)
    finally:
        server.close()


def main() -> int:
    if len(sys.argv) < 4:
        print("Usage: python3 usbmux.py <udid> <local_port> <device_port>", file=sys.stderr)
        return 1
    udid = sys.argv[1]
    local_port = int(sys.argv[2])
    device_port = int(sys.argv[3])

    stop_event = threading.Event()

    def handle_signal(sig, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    run_forwarder(udid, local_port, device_port, stop_event)
    return 0


if __name__ == "__main__":
    sys.exit(main())
