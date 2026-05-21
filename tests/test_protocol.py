"""Tests for the neplocal binary protocol decoder.

Test vectors are real frames captured from NEP BDM-2250 microinverters.
"""

from __future__ import annotations

import pytest

from neplocal.protocol import (
    AC_VOLTAGE_OFFSET,
    AC_VOLTAGE_SCALE,
    CMD_TELEMETRY,
    MAGIC,
    TEMPERATURE_OFFSET,
    TEMPERATURE_SCALE,
    ModuleReading,
    TelemetryFrame,
    count_modules,
    decode_frame,
    verify_checksum,
)

# Real captured frame from device 86D4EC90 (2026-05-20 17:07 UTC)
FRAME_86D4EC90 = bytes.fromhex(
    "793e00401400000f0f0f0f00003400ffffffff"
    "90ecd486"  # SN = 86D4EC90 (LE)
    "0000"
    "42975f21b0100001093cf0107e0906e6"
    "5f21102662025f21482553022a2183277d022a2167244a02"
    "00a03822"
)

# Real captured frame from device 86D33EC0 (2026-05-20 17:02 UTC)
FRAME_86D33EC0 = bytes.fromhex(
    "793e00401400000f0f0f0f00003400ffffffff"
    "c03ed386"  # SN = 86D33EC0 (LE)
    "0000"
    "0d6d262170100001153c3112cb05"
    "06e62621fd1861012621a61d7f01"
    "f921cc1c8201f9219c196801"
    "5e98e2ee"
)


class TestDecodeFrame:
    def test_valid_frame(self) -> None:
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None
        assert frame.serial_number == "86D4EC90"
        assert frame.command == CMD_TELEMETRY

    def test_serial_number(self) -> None:
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None
        assert frame.serial_number == "86D4EC90"

    def test_frame_metadata(self) -> None:
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None
        assert frame.frame_length == 64
        assert frame.data_length == 52

    def test_four_modules(self) -> None:
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None
        assert len(frame.modules) == 4

    def test_voltage_calibration(self) -> None:
        """Verify voltage = LE u16 / 256."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None

        # Module 0: bytes 5F 21 -> LE 0x215F = 8543 -> 8543/256 = 33.37 V
        assert frame.modules[0].voltage_raw == 0x215F
        assert abs(frame.modules[0].dc_voltage - 33.37) < 0.01

        # MPPT1 voltage should match modules 0 & 1 (same MPPT input)
        assert abs(frame.mppt1_voltage - frame.modules[0].dc_voltage) < 0.01

    def test_current_calibration(self) -> None:
        """Verify current = LE u16 / 819.2."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None

        # Module 0: bytes 10 26 -> LE 0x2610 = 9744 -> 9744/819.2 = 11.895 A
        assert frame.modules[0].current_raw == 0x2610
        assert abs(frame.modules[0].dc_current - 11.895) < 0.01

    def test_energy_calibration(self) -> None:
        """Verify energy = LE u16 * 3.62 Wh."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None

        # Module 0: bytes 62 02 -> LE 0x0262 = 610 -> 610 * 3.62 = 2208.2 Wh
        assert frame.modules[0].energy_raw == 0x0262
        assert abs(frame.modules[0].energy_today - 2208.2) < 0.1

    def test_power_calibration(self) -> None:
        """Verify power = V_raw * I_raw / 209715.2."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None

        m = frame.modules[0]
        expected_power = (0x215F * 0x2610) / 209715.2  # = ~396.7 W
        assert abs(m.dc_power - expected_power) < 0.1

    def test_frequency_calibration(self) -> None:
        """Verify AC frequency = LE u16 / 256."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None

        # Bytes 09 3C -> LE 0x3C09 = 15369 -> 15369/256 = 60.035 Hz
        assert abs(frame.ac_frequency - 60.035) < 0.01

    def test_total_current_is_module_sum(self) -> None:
        """Total DC current should equal sum of module currents (within rounding)."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None

        module_sum = sum(m.current_raw for m in frame.modules)
        # Allow delta of 2 raw counts for rounding
        assert abs(frame.total_dc_current * 819.2 - module_sum) < 3

    def test_total_dc_power(self) -> None:
        """Total DC power is sum of per-module powers."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None

        module_sum = sum(m.dc_power for m in frame.modules)
        assert abs(frame.total_dc_power - module_sum) < 0.01

    def test_grid_spec(self) -> None:
        """Grid spec encodes nominal voltage and frequency code."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None

        # Bytes 06 E6 -> LE 0xE606
        assert frame.grid_voltage == 230  # 0xE6
        assert frame.grid_frequency_code == 6  # 60 Hz grid

    def test_checksum(self) -> None:
        """Verify XOR checksum: XOR(data[1:-2]) == data[-1]."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None
        assert frame.checksum_ok

        frame2 = decode_frame(FRAME_86D33EC0)
        assert frame2 is not None
        assert frame2.checksum_ok

    def test_ac_voltage(self) -> None:
        """Verify AC voltage = LE u16 / 16 - 22."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None
        # Bytes B0 10 -> LE 0x10B0 = 4272 -> 4272/16 - 22 = 245.0 V
        assert abs(frame.ac_voltage - 245.0) < 0.1

    def test_temperature(self) -> None:
        """Verify temperature = LE u16 / 49.5 - 50.24 (°C)."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None
        # Bytes F0 10 -> LE 0x10F0 = 4336 -> 4336/49.5 - 50.24 = 37.36 °C
        assert abs(frame.temperature - 37.36) < 0.1

    def test_alert_code(self) -> None:
        """Alert code from bytes 23-24 (big-endian)."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None
        # Bytes 00 00 -> no alert
        assert frame.alert_code == 0x0000

    def test_mppt_pairing(self) -> None:
        """Modules 0&1 share MPPT1 voltage, modules 2&3 share MPPT2."""
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None

        # MPPT1: modules 0 and 1 have same voltage
        assert frame.modules[0].voltage_raw == frame.modules[1].voltage_raw
        # MPPT2: modules 2 and 3 have same voltage
        assert frame.modules[2].voltage_raw == frame.modules[3].voltage_raw
        # MPPT1 != MPPT2
        assert frame.modules[0].voltage_raw != frame.modules[2].voltage_raw

    def test_to_dict(self) -> None:
        frame = decode_frame(FRAME_86D4EC90)
        assert frame is not None

        d = frame.to_dict()
        assert d["sn"] == "86D4EC90"
        assert "total_dc_power_W" in d
        assert "ac_voltage_V" in d
        assert "temperature_C" in d
        assert "alert_code" in d
        assert "modules" in d
        assert len(d["modules"]) == 4
        assert "dc_voltage_V" in d["modules"][0]

    def test_second_device(self) -> None:
        """Verify decoding of a frame from a different device."""
        frame = decode_frame(FRAME_86D33EC0)
        assert frame is not None
        assert frame.serial_number == "86D33EC0"
        assert len(frame.modules) == 4
        assert frame.ac_frequency > 59.0
        assert frame.ac_frequency < 61.0


class TestDecodeFrameEdgeCases:
    def test_too_short(self) -> None:
        assert decode_frame(b"\x79\x3e\x00") is None

    def test_wrong_magic(self) -> None:
        bad = bytearray(FRAME_86D4EC90)
        bad[0] = 0x00
        assert decode_frame(bytes(bad)) is None

    def test_wrong_command(self) -> None:
        bad = bytearray(FRAME_86D4EC90)
        bad[4] = 0x15  # change command from 0x1400 to 0x1500
        assert decode_frame(bytes(bad)) is None

    def test_empty(self) -> None:
        assert decode_frame(b"") is None


class TestCountModules:
    def test_four_modules(self) -> None:
        assert count_modules(FRAME_86D4EC90) == 4

    def test_zero_modules(self) -> None:
        data = bytearray(FRAME_86D4EC90)
        data[7] = data[8] = data[9] = data[10] = 0
        assert count_modules(bytes(data)) == 0

    def test_two_modules(self) -> None:
        data = bytearray(FRAME_86D4EC90)
        data[9] = data[10] = 0
        assert count_modules(bytes(data)) == 2


class TestModuleReading:
    def test_to_dict(self) -> None:
        m = ModuleReading(
            index=0,
            dc_voltage=33.37,
            dc_current=11.895,
            dc_power=396.7,
            energy_today=2208.2,
            voltage_raw=8543,
            current_raw=9744,
            energy_raw=610,
        )
        d = m.to_dict()
        assert d["index"] == 0
        assert d["dc_voltage_V"] == 33.37
        assert d["dc_power_W"] == 396.7
