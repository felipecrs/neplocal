"""neplocal - Decode the local binary protocol used by NEP solar microinverters."""

from .protocol import (
    CLOUD_HOST,
    CLOUD_PATH,
    CMD_TELEMETRY,
    CURRENT_SCALE,
    ENERGY_SCALE,
    FREQUENCY_SCALE,
    MAGIC,
    MODULE_SIZE,
    POWER_SCALE,
    VOLTAGE_SCALE,
    ModuleReading,
    TelemetryFrame,
    count_modules,
    decode_frame,
    verify_checksum,
)

__all__ = [
    "MAGIC",
    "CMD_TELEMETRY",
    "CLOUD_HOST",
    "CLOUD_PATH",
    "VOLTAGE_SCALE",
    "CURRENT_SCALE",
    "POWER_SCALE",
    "ENERGY_SCALE",
    "FREQUENCY_SCALE",
    "MODULE_SIZE",
    "TelemetryFrame",
    "ModuleReading",
    "decode_frame",
    "verify_checksum",
    "count_modules",
]
