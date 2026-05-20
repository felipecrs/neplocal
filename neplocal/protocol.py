"""NEP microinverter local binary protocol decoder.

See README.md for the full protocol specification.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

MAGIC = b"\x79\x3e"
CMD_TELEMETRY = 0x1400

CLOUD_HOST = "www.nepviewer.net"
CLOUD_PATH = "/t.php"

VOLTAGE_SCALE = 256.0
CURRENT_SCALE = 819.2
POWER_SCALE = 209715.2
ENERGY_SCALE = 3.62
FREQUENCY_SCALE = 256.0

OFF_MAGIC = 0
OFF_LENGTH = 2
OFF_COMMAND = 4
OFF_FLAGS = 6
OFF_DATA_LEN = 12
OFF_SN = 19
OFF_TOTAL_CURRENT = 25
OFF_MPPT1_VOLTAGE = 27
OFF_UNKNOWN_A = 29
OFF_AC_FREQ = 33
OFF_UNKNOWN_B = 35
OFF_TOTAL_ENERGY = 37
OFF_GRID_SPEC = 39
OFF_MODULES = 41
MODULE_SIZE = 6


@dataclass
class ModuleReading:
    """Decoded per-module telemetry reading."""

    index: int
    dc_voltage: float
    dc_current: float
    dc_power: float
    energy_today: float
    voltage_raw: int = 0
    current_raw: int = 0
    energy_raw: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "dc_voltage_V": round(self.dc_voltage, 2),
            "dc_current_A": round(self.dc_current, 3),
            "dc_power_W": round(self.dc_power, 1),
            "energy_today_Wh": round(self.energy_today, 1),
        }


@dataclass
class TelemetryFrame:
    """Fully decoded telemetry frame from a NEP microinverter."""

    serial_number: str
    command: int
    total_dc_current: float
    mppt1_voltage: float
    ac_frequency: float
    total_energy_today: float
    total_dc_power: float
    grid_spec_raw: int
    modules: list[ModuleReading] = field(default_factory=list)
    frame_length: int = 0
    data_length: int = 0
    checksum_ok: bool = False
    unknown_a: int = 0
    unknown_b: int = 0
    raw_hex: str = ""

    @property
    def grid_voltage(self) -> int:
        return (self.grid_spec_raw >> 8) & 0xFF

    @property
    def grid_frequency_code(self) -> int:
        return self.grid_spec_raw & 0xFF

    def to_dict(self) -> dict[str, Any]:
        return {
            "sn": self.serial_number,
            "total_dc_power_W": round(self.total_dc_power, 1),
            "total_dc_current_A": round(self.total_dc_current, 3),
            "total_energy_today_Wh": round(self.total_energy_today, 1),
            "mppt1_voltage_V": round(self.mppt1_voltage, 2),
            "ac_frequency_Hz": round(self.ac_frequency, 2),
            "grid_voltage_V": self.grid_voltage,
            "modules": [m.to_dict() for m in self.modules],
            "checksum_ok": self.checksum_ok,
        }


def _le16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _be16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def verify_checksum(data: bytes) -> bool:
    """Verify XOR checksum (last byte vs XOR of all preceding bytes)."""
    xor = 0
    for b in data[:-1]:
        xor ^= b
    return xor == data[-1]


def count_modules(data: bytes) -> int:
    """Count active modules from flag bytes at positions 7-10."""
    if len(data) < 11:
        return 0
    return sum(1 for i in range(7, 11) if data[i] != 0)


def decode_frame(data: bytes) -> TelemetryFrame | None:
    """Decode a raw y> telemetry frame. Returns ``None`` if invalid."""
    if len(data) < OFF_MODULES or data[OFF_MAGIC : OFF_MAGIC + 2] != MAGIC:
        return None

    command = _be16(data, OFF_COMMAND)
    if command != CMD_TELEMETRY:
        return None

    frame_length = _be16(data, OFF_LENGTH)
    data_length = _be16(data, OFF_DATA_LEN)
    sn_raw = struct.unpack_from("<I", data, OFF_SN)[0]
    serial_number = f"{sn_raw:08X}"

    # Aggregate readings (all little-endian)
    total_current_raw = _le16(data, OFF_TOTAL_CURRENT)
    mppt1_voltage_raw = _le16(data, OFF_MPPT1_VOLTAGE)
    unknown_a = _le16(data, OFF_UNKNOWN_A)
    ac_freq_raw = _le16(data, OFF_AC_FREQ)
    unknown_b = _le16(data, OFF_UNKNOWN_B)
    total_energy_raw = _le16(data, OFF_TOTAL_ENERGY)
    grid_spec_raw = _le16(data, OFF_GRID_SPEC)

    # Per-module data
    num_modules = count_modules(data)
    modules: list[ModuleReading] = []

    for idx in range(num_modules):
        offset = OFF_MODULES + idx * MODULE_SIZE
        if offset + MODULE_SIZE > len(data) - 1:  # leave room for checksum
            break

        v_raw = _le16(data, offset)
        i_raw = _le16(data, offset + 2)
        e_raw = _le16(data, offset + 4)

        modules.append(
            ModuleReading(
                index=idx,
                dc_voltage=v_raw / VOLTAGE_SCALE,
                dc_current=i_raw / CURRENT_SCALE,
                dc_power=(v_raw * i_raw) / POWER_SCALE,
                energy_today=e_raw * ENERGY_SCALE,
                voltage_raw=v_raw,
                current_raw=i_raw,
                energy_raw=e_raw,
            )
        )

    total_dc_power = sum(m.dc_power for m in modules)

    return TelemetryFrame(
        serial_number=serial_number,
        command=command,
        total_dc_current=total_current_raw / CURRENT_SCALE,
        mppt1_voltage=mppt1_voltage_raw / VOLTAGE_SCALE,
        ac_frequency=ac_freq_raw / FREQUENCY_SCALE,
        total_energy_today=total_energy_raw * ENERGY_SCALE,
        total_dc_power=total_dc_power,
        grid_spec_raw=grid_spec_raw,
        modules=modules,
        frame_length=frame_length,
        data_length=data_length,
        checksum_ok=verify_checksum(data),
        unknown_a=unknown_a,
        unknown_b=unknown_b,
        raw_hex=data.hex(),
    )
