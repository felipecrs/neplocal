"""CLI: ``python -m neplocal --hex <hex_string> [--json]``."""

from __future__ import annotations

import argparse
import sys

from .protocol import TelemetryFrame, decode_frame


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m neplocal",
        description="Decode NEP microinverter binary telemetry frames",
    )
    parser.add_argument(
        "--hex",
        required=True,
        help="Raw hex string of the binary frame (spaces allowed)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of human-readable text",
    )
    args = parser.parse_args()

    try:
        data = bytes.fromhex(args.hex.replace(" ", ""))
    except ValueError as e:
        print(f"Invalid hex: {e}", file=sys.stderr)
        sys.exit(1)

    frame = decode_frame(data)
    if frame is None:
        print("Not a valid NEP telemetry frame.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        import json

        print(json.dumps(frame.to_dict(), indent=2))
    else:
        _print_frame(frame)


def _print_frame(frame: TelemetryFrame) -> None:
    print(f"NEP Telemetry Frame ({len(frame.raw_hex) // 2} bytes)")
    print(f"  Serial Number    : {frame.serial_number}")
    print(f"  Command          : 0x{frame.command:04X}")
    print(f"  Checksum         : {'OK' if frame.checksum_ok else 'FAIL'}")
    print()
    print(f"  Total DC Power   : {frame.total_dc_power:8.1f} W")
    print(f"  Total DC Current : {frame.total_dc_current:8.3f} A")
    print(f"  MPPT1 Voltage    : {frame.mppt1_voltage:8.2f} V")
    print(f"  AC Frequency     : {frame.ac_frequency:8.2f} Hz")
    print(f"  Energy Today     : {frame.total_energy_today:8.1f} Wh")
    print(f"  Grid Spec        : {frame.grid_voltage}V / code {frame.grid_frequency_code}")
    print()
    print(f"  Modules ({len(frame.modules)}):")
    for m in frame.modules:
        print(
            f"    [{m.index}] {m.dc_voltage:6.2f} V  "
            f"{m.dc_current:6.3f} A  "
            f"{m.dc_power:7.1f} W  "
            f"{m.energy_today:8.1f} Wh"
        )


if __name__ == "__main__":
    main()
