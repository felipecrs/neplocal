"""MITM proxy for capturing NEP microinverter traffic.

See README.md for setup instructions.

Usage::

    python -m neplocal.proxy [--port 80] [--log-dir ./captures] [--dns 1.1.1.1]
"""

from __future__ import annotations

import json
import socket
import struct
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from .protocol import CLOUD_HOST, TelemetryFrame, decode_frame


def get_lan_ip() -> str:
    """Discover this machine's LAN IP by connecting to an external address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 53))
        return s.getsockname()[0]
    finally:
        s.close()


def dns_resolve(hostname: str, server: str = "1.1.1.1") -> str:
    """Resolve *hostname* via a raw UDP DNS query to *server*."""
    query_id = 0xABCD
    flags = 0x0100  # standard query, recursion desired
    header = struct.pack(">HHHHHH", query_id, flags, 1, 0, 0, 0)

    question = b""
    for label in hostname.split("."):
        question += bytes([len(label)]) + label.encode()
    question += b"\x00"
    question += struct.pack(">HH", 1, 1)  # QTYPE=A, QCLASS=IN

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    try:
        sock.sendto(header + question, (server, 53))
        data, _ = sock.recvfrom(512)
    finally:
        sock.close()

    ancount = struct.unpack(">H", data[6:8])[0]

    # Skip question section
    offset = 12
    while data[offset] != 0:
        offset += data[offset] + 1
    offset += 5  # null byte + QTYPE + QCLASS

    for _ in range(ancount):
        if data[offset] & 0xC0 == 0xC0:
            offset += 2
        else:
            while data[offset] != 0:
                offset += data[offset] + 1
            offset += 1
        rtype, _, _, rdlength = struct.unpack(">HHIH", data[offset : offset + 10])
        offset += 10
        if rtype == 1 and rdlength == 4:
            return ".".join(str(b) for b in data[offset : offset + 4])
        offset += rdlength

    raise RuntimeError(f"No A record found for {hostname} via {server}")


def print_frame(frame: TelemetryFrame) -> None:
    """Pretty-print a decoded frame to stdout."""
    ok = "OK" if frame.checksum_ok else "?"
    alert = f"  alert=0x{frame.alert_code:04X}" if frame.alert_code else ""
    print(f"  SN={frame.serial_number}  cksum={ok}{alert}")
    print(
        f"  Total: {frame.total_dc_power:7.1f} W  "
        f"{frame.total_dc_current:6.3f} A  "
        f"{frame.total_energy_today:8.1f} Wh  "
        f"freq={frame.ac_frequency:.2f} Hz  "
        f"AC={frame.ac_voltage:.0f} V  "
        f"temp={frame.temperature:.1f} °C"
    )
    for m in frame.modules:
        print(
            f"    [{m.index}] {m.dc_voltage:6.2f} V  "
            f"{m.dc_current:6.3f} A  "
            f"{m.dc_power:7.1f} W  "
            f"{m.energy_today:8.1f} Wh"
        )


class ProxyHandler(BaseHTTPRequestHandler):
    log_dir: Path = Path("captures")
    real_ip: str = ""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        ts = datetime.now(timezone.utc)
        frame = decode_frame(body)
        sn = frame.serial_number if frame else "unknown"

        print(
            f"\n[{ts:%H:%M:%S}] POST {self.path} "
            f"({len(body)}B) from {self.client_address[0]}"
        )

        if frame:
            print_frame(frame)

            entry = {"t": ts.isoformat(), **frame.to_dict(), "raw_hex": frame.raw_hex}
            log_file = self.log_dir / f"{sn}.jsonl"
            with open(log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        else:
            print(f"  (non-NEP payload: {body[:40].hex()}...)")

        # Forward to real server using resolved IP
        try:
            req = Request(
                f"http://{self.real_ip}{self.path}",
                data=body,
                headers={
                    "Host": CLOUD_HOST,
                    "Connection": "close",
                    "Content-Length": str(len(body)),
                },
                method="POST",
            )
            with urlopen(req, timeout=10) as resp:
                resp_body = resp.read()
                resp_code = resp.status

            print(f"  -> server {resp_code}: {resp_body!r}")
            self.send_response(resp_code)
            self.send_header("Content-Length", str(len(resp_body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(resp_body)
        except Exception as e:
            print(f"  -> forward error: {e}")
            fallback = ts.strftime("%Y%m%d%H%M%S").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(fallback)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(fallback)

    def log_message(self, fmt: str, *args: object) -> None:
        pass


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(
        description="MITM proxy for NEP microinverter y> binary protocol"
    )
    p.add_argument("--port", type=int, default=80, help="Listen port (default: 80)")
    p.add_argument("--log-dir", type=Path, default=Path("captures"))
    p.add_argument(
        "--dns",
        default="1.1.1.1",
        help="DNS server to resolve real nepviewer IP (default: 1.1.1.1)",
    )
    args = p.parse_args()

    args.log_dir.mkdir(parents=True, exist_ok=True)
    ProxyHandler.log_dir = args.log_dir

    # Detect LAN IP
    lan_ip = get_lan_ip()
    print(f"Detected LAN IP: {lan_ip}")

    # Resolve the real server IP via external DNS
    print(f"Resolving {CLOUD_HOST} via {args.dns}...")
    real_ip = dns_resolve(CLOUD_HOST, args.dns)
    print(f"  -> {real_ip}")
    ProxyHandler.real_ip = real_ip

    srv = HTTPServer(("0.0.0.0", args.port), ProxyHandler)
    print(f"\nNEP MITM Proxy listening on :{args.port}")
    print(f"  Forwarding to {CLOUD_HOST} ({real_ip})")
    print(f"  Logs: {args.log_dir.resolve()}")
    print(f"\nOpenWRT dnsmasq setup:")
    print(f'  echo "address=/{CLOUD_HOST}/{lan_ip}" >> /etc/dnsmasq.conf')
    print(f"  /etc/init.d/dnsmasq restart")
    print(f"\nWaiting for inverter traffic...\n")

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        srv.shutdown()


if __name__ == "__main__":
    main()
