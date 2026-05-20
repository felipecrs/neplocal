> [!IMPORTANT]
> This is AI-generated content with very little QA on top.

# neplocal

Decode the local binary protocol used by [NEP](https://northernep.com/) solar microinverters.

NEP microinverters (e.g. BDM-2250) periodically report telemetry to the NEP cloud (`www.nepviewer.net`) using a proprietary binary protocol over plain HTTP.
This library decodes those frames into calibrated real-unit readings -- volts, amps, watts, and watt-hours -- with no cloud dependency and no external libraries required.

## Quick start

```python
from neplocal import decode_frame

raw = bytes.fromhex(
    "793e00401400000f0f0f0f00003400ffffffff"
    "90ecd486000042975f21b0100001093cf01"
    "07e0906e65f21102662025f2148255302"
    "2a2183277d022a2167244a0200a03822"
)

frame = decode_frame(raw)
if frame:
    print(f"{frame.serial_number}: {frame.total_dc_power:.1f} W  "
          f"AC={frame.ac_voltage:.0f} V  temp={frame.temperature:.1f} °C  "
          f"cksum={'OK' if frame.checksum_ok else 'FAIL'}")
    for m in frame.modules:
        print(f"  Module {m.index}: {m.dc_power:.1f} W  {m.dc_voltage:.1f} V  {m.dc_current:.3f} A")
```

Output:

```
86D4EC90: 1572.5 W  AC=245 V  temp=37.3 °C  cksum=OK
  Module 0: 396.9 W  33.4 V  11.895 A
  Module 1: 388.8 W  33.4 V  11.650 A
  Module 2: 409.5 W  33.2 V  12.347 A
  Module 3: 377.3 W  33.2 V  11.376 A
```

## Install

```bash
pip install .          # from this repo
# or
uv pip install .
```

No runtime dependencies -- just Python 3.12+.

## CLI

Decode a hex frame from the command line:

```bash
python -m neplocal --hex "793e00401400000f0f0f0f00003400ffffffff90ecd486..."
python -m neplocal --hex "793e..." --json    # JSON output
```

## Protocol documentation

### Background

NEP microinverters communicate with the cloud via a WiFi gateway (built into the inverter or external). Every ~5 minutes, the inverter sends a plain HTTP POST to:

```
POST http://www.nepviewer.net/t.php
```

The request body is a binary frame using what we call the **"y>" protocol** (named after its 2-byte magic `0x79 0x3E`). The server responds with a timestamp string (used for clock sync). All communication is unencrypted HTTP on port 80.

### Frame layout

A complete telemetry frame for a 4-module inverter is **69 bytes**:

```
 Offset  Len  Field                 Encoding
 ------  ---  --------------------  ------------------------------------
  0       2   Magic                 0x79 0x3E ("y>")
  2       2   Payload length        big-endian u16
  4       2   Command               big-endian u16 (0x1400 = telemetry)
  6       1   Padding               0x00
  7       4   Module flags          1 byte per slot; non-zero = active
 11       1   Padding               0x00
 12       2   Data length           big-endian u16
 14       5   Padding               0x00 0xFF 0xFF 0xFF 0xFF
 19       4   Serial number         little-endian u32 -> hex string
 23       2   Alert code            big-endian u16 (0x0000 = OK)
 25       2   Total DC current      little-endian u16
 27       2   MPPT1 DC voltage      little-endian u16
 29       2   AC voltage RMS        little-endian u16
 31       2   Constant              0x00 0x01
 33       2   AC frequency          little-endian u16
 35       2   Temperature           little-endian u16
 37       2   Total energy today    little-endian u16
 39       2   Grid specification    little-endian u16
 41      6*M  Per-module data       M modules x 6 bytes each
 41+6*M   3   Tail                  3 bytes (unknown purpose)
 44+6*M   1   Checksum              1 byte (algorithm unverified)
```

### Per-module data (6 bytes per module)

```
 Offset  Len  Field            Encoding
 ------  ---  ---------------  -------------------------
 0        2   DC voltage       little-endian u16
 2        2   DC current       little-endian u16
 4        2   Energy today     little-endian u16
```

### Scale factors

All 16-bit data words are **little-endian unsigned**. The following scale factors were derived by cross-referencing captured binary frames against the [NEP cloud API](https://api.nepviewer.net) (device-detail, playback, and site-modules endpoints):

| Field | Formula | Unit | Notes |
|---|---|---|---|
| DC Voltage | raw / 256 | V | 8.8 fixed-point |
| Current | raw / 819.2 | A | |
| Power | V_raw * I_raw / 209,715.2 | W | Derived from V and I scales |
| Energy | raw * 3.62 | Wh | Resets daily |
| AC Frequency | raw / 256 | Hz | 8.8 fixed-point |
| AC Voltage | raw / 16 − 22 | V | RMS grid voltage; see [calibration notes](#ac-voltage-and-temperature-calibration) |
| Temperature | raw / 48 − 53 | °C | Inverter temperature; linear approximation of non-linear sensor |

### Grid specification field (bytes 39-40)

The LE u16 at offset 39 encodes grid parameters:

- **High byte**: nominal AC voltage (e.g. `0xE6` = 230 V)
- **Low byte**: frequency code (e.g. `0x06` = 60 Hz grid, `0x05` = 50 Hz)

### Alert code (bytes 23-24)

The BE u16 at offset 23 encodes the device's current alert status. Observed values:

| Code | Meaning | Notes |
|---|---|---|
| `0x0000` | OK | Normal operation |
| `0x0040` | AC voltage RMS over | Grid voltage exceeds threshold |
| `0x0020` | Frequency under | Grid frequency below threshold |

These codes match the `alert_code` field returned by the NEP cloud API (`device-detail` and `site-modules` endpoints). When an alert is active, the grid specification low byte also changes (see below).

### Module flags (bytes 7-10)

Each byte corresponds to a module slot (0-3). A non-zero value (`0x0F` observed) indicates the slot is active. This determines how many 6-byte module groups follow the aggregate data at offset 41.

### Aggregate field relationships

These relationships were verified across multiple captures from two devices:

- **Total DC current** (offset 25) = sum of all module currents (raw values, within +/-2 counts of rounding)
- **Total energy today** (offset 37) = sum of all module energies (within +/-3 counts)
- **MPPT1 voltage** (offset 27) matches modules 0 and 1 (same MPPT input)
- Modules 2 and 3 share a second MPPT voltage (different from MPPT1)

### Checksum

The last byte is a **XOR checksum** computed over `data[1:-2]` -- all bytes except the first magic byte (`0x79`), the last tail byte, and the checksum itself:

```
checksum = XOR(data[1], data[2], ..., data[len-3])
```

Equivalently: `checksum = XOR(frame[1 : -2])`. Verified against 65 captured frames from two devices.

### Decoded fields (formerly unknown)

| Offset | Field | Scale | Notes |
|---|---|---|---|
| 23-24 | Alert code | BE u16 | `0x0000`=OK, `0x0040`=AC over-voltage, `0x0020`=freq under |
| 29-30 | AC voltage RMS | LE u16 / 16 − 22 | Measured grid voltage in V; same across co-located devices |
| 35-36 | Temperature | LE u16 / 48 − 53 | Internal inverter temp in °C; device-specific |

### Remaining unknown fields

| Offset | Observed values | Notes |
|---|---|---|
| 41+6*M to 41+6*M+2 (Tail) | varies | 3 bytes, changes every report, no clear pattern |

## MITM proxy

The package includes a transparent HTTP proxy for capturing live inverter traffic:

```bash
python -m neplocal.proxy [--port 80] [--log-dir ./captures] [--dns 1.1.1.1]
```

### How it works

1. A DNS override (e.g. via dnsmasq on the router) redirects `www.nepviewer.net` to your machine
2. The proxy accepts the inverter's HTTP POST, decodes the frame, logs it, and forwards to the real server
3. The server response (a timestamp for clock sync) is passed back to the inverter

The proxy resolves the real `www.nepviewer.net` IP via a raw DNS query to `1.1.1.1`, bypassing the local DNS override.

### Setup (OpenWRT example)

```bash
# On your OpenWRT router -- redirect DNS for nepviewer to your PC:
echo "address=/www.nepviewer.net/YOUR_PC_IP" >> /etc/dnsmasq.conf
/etc/init.d/dnsmasq restart

# On your PC -- run the proxy (needs admin/root for port 80):
python -m neplocal.proxy

# The proxy will auto-detect your LAN IP and print the exact dnsmasq command.
```

### Docker

```bash
docker build -t neplocal-proxy https://github.com/felipecrs/neplocal.git
docker run --rm -p 80:80 -u $(id -u):$(id -g) -v ./captures:/wd/captures neplocal-proxy
```

Pass extra flags after the image name (e.g. `--dns 8.8.8.8`). The image is ~50 MB (Python 3.14 Alpine, zero pip dependencies).

### Log format

Each intercepted frame is appended as a JSON line to `captures/<SERIAL_NUMBER>.jsonl`:

```json
{
  "t": "2026-05-20T17:07:38.698954+00:00",
  "sn": "86D4EC90",
  "total_dc_power_W": 1572.5,
  "total_dc_current_A": 47.268,
  "total_energy_today_Wh": 8796.6,
  "mppt1_voltage_V": 33.37,
  "ac_voltage_V": 245.0,
  "ac_frequency_Hz": 60.04,
  "temperature_C": 37.33,
  "grid_voltage_V": 230,
  "alert_code": "0x0000",
  "modules": [
    {"index": 0, "dc_voltage_V": 33.37, "dc_current_A": 11.895, "dc_power_W": 396.9, "energy_today_Wh": 2208.2},
    {"index": 1, "dc_voltage_V": 33.37, "dc_current_A": 11.65, "dc_power_W": 388.8, "energy_today_Wh": 2153.9},
    {"index": 2, "dc_voltage_V": 33.16, "dc_current_A": 12.347, "dc_power_W": 409.5, "energy_today_Wh": 2305.9},
    {"index": 3, "dc_voltage_V": 33.16, "dc_current_A": 11.376, "dc_power_W": 377.3, "energy_today_Wh": 2121.3}
  ],
  "checksum_ok": true,
  "raw_hex": "793e004014...",
  "decoder": "bd8eedcdbbddcbdff4b6a75a888bb80e11813d66ce01c72d18754b7375bc43b2"
}
```

## Calibration methodology

The scale factors were derived by:

1. Running the MITM proxy to capture raw binary frames from two BDM-2250 inverters
2. Simultaneously querying the NEP cloud API for the same devices:
   - `device-detail` -- current power, voltage, frequency
   - `device/playback` -- 5-minute power history (W) for the capture window
   - `site/modules` -- per-module current power and energy
3. Systematically testing divisors/multipliers until cloud values matched binary values within measurement precision

The cloud API reports **AC output power** while the binary protocol reports **DC input** per module. The ~2-3% delta between sum-of-DC-module-power and cloud-reported-AC-power is consistent with inverter conversion efficiency losses.

### AC voltage and temperature calibration

Formulas were calibrated by time-aligning binary captures with the cloud API's per-parameter chart data (`/device/statistics/echarts` with `lines=["AC Voltage","Temperature"]`).

**AC voltage** (bytes 29-30): `raw / 16 − 22`.

- The **`/ 16`** is definitive: all observed raw values are exact multiples of 16, and the cloud reports only exact integers (0 fractional values in 800+ data points across 4 days). This means the measurement has 1 V resolution and the encoding multiplies by 16.
- The **`− 22`** offset is empirical (±1 V): determined by comparing `raw/16` against cloud values at matching timestamps. A purely multiplicative model `raw × 11/192` also fits the observed voltage range (233–247 V) but produces non-integer intermediate results. The two models diverge at lower voltages (<230 V); binary captures during low-voltage conditions would resolve the ambiguity.
- The cloud-reported AC voltage for two co-located devices can differ by up to 7 V at the same moment (measurement noise + per-device variation), so the offset cannot be verified more precisely than ±2 V from cloud data alone.
- Confirmed against a multimeter reading of 240 V.

**Temperature** (bytes 35-36): `raw / 48 − 53`.

- The temperature sensor is **non-linear** (likely NTC thermistor). Evidence: the slope `Δraw / ΔT` is ~43 raw units/°C at 26–29 °C but ~48 raw units/°C at 27–35 °C. A linear formula is inherently an approximation.
- `/ 48 − 53` was calibrated over the wider range (27–35 °C, 14 time-aligned data points). It matches the cloud within ±1 °C across this range. It may be less accurate at temperature extremes (the cloud reports 17–59 °C for these devices).
- The cloud reports only integer °C for temperature as well.

## Tested devices

| Model | Modules | Gateway | Grid | Verified |
|---|---|---|---|---|
| BDM-2250 | 4 (2x MPPT) | Built-in WiFi | 230V / 60Hz | Yes (2 units) |

Other NEP models using the same gateway firmware likely use the same protocol. Models with different module counts (e.g. BDM-600 with 1 module, BDM-1200 with 2) should work but are untested.

## What's remaining

### Solved (previously unknown)

- **Checksum algorithm**: XOR of `data[1:-2]` (all bytes except the first magic byte, last tail byte, and checksum). Verified on 65 captured frames.
- **AC voltage RMS** (bytes 29-30): Grid voltage measured by the inverter, encoded as LE u16 / 16 − 22. Values ~202-247 V observed on a 230 V nominal grid. The `/16` divisor is definitive (exact integer output); the `−22` offset is empirical (±1 V). See [calibration notes](#ac-voltage-and-temperature-calibration).
- **Temperature** (bytes 35-36): Internal inverter temperature in °C, encoded as LE u16 / 48 − 53. This is a linear approximation of a non-linear sensor (likely NTC thermistor). Accurate to ±1 °C in the 27–35 °C range; may diverge at extremes. See [calibration notes](#ac-voltage-and-temperature-calibration).
- **Alert code** (bytes 23-24): Previously labeled as padding. Encodes the device alert status as a BE u16, matching the cloud API's `alert_code` field (e.g. `0x0040` = "AC voltage RMS over").

### Known unknowns

- **Tail bytes** (3 bytes after module data): Change every report. Could be a sequence counter, timestamp fragment, or additional measurements. No pattern identified yet.
- **Other command codes**: Only `0x1400` (telemetry) has been observed. The protocol likely supports other commands (configuration, firmware update, etc.) but these haven't been captured.
- **Grid spec low byte**: Changes from `0x06` (normal 60 Hz operation) to `0x01` during alerts and startup. The exact encoding is unclear -- it may represent an operational mode rather than just a frequency code.

### Potential future work

- **Local polling**: The inverter listens on TCP port 80 and UDP port 8900. Initial probing with y> frames got no responses, but the protocol for local queries may differ from the cloud reporting format. If a query frame format is found, local polling without the MITM proxy becomes possible.
- **More models**: Test with other NEP inverter models (BDM-600, BDM-1200, BDM-800, three-phase models) to verify the protocol is consistent.
- **Home Assistant integration**: Build a HA custom component that uses the MITM proxy approach (or local polling if discovered) for cloud-free solar monitoring.
- **Energy counter rollover**: The energy field is a 16-bit value (max ~237 kWh at the 3.62 scale). Need to verify behavior at rollover -- likely resets daily at midnight.
- **AC current and power**: AC voltage is now decoded (bytes 29-30). AC current and per-module AC power are still unaccounted for -- the cloud API reports these values but they may require a different query command or be derived server-side from DC power with an efficiency factor.

## Related

- [aionepviewer](https://github.com/felipecrs/aionepviewer) -- Async Python library for the NEPViewer Cloud API

## License

MIT
