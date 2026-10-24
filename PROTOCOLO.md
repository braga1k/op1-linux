# Protocol evidence: OP1 8k v2 / vendor tool 1.07

## Sources and provenance

- User-supplied `Endgame Gear OP1 8k v2 Configuration Tool v1.07.exe`, PE32 x86. SHA-256: `e0494dd635e0029fcac1a90e6fa09b00f3ab72d3cfd2abf33e33425153c36c4f`.
- REA 6.7.0 and Ghidra 12.1.4 static function dossiers. Engines and vendor code are not part of the runtime/release.
- Raw HID descriptor from the attached device (`3367:1978`), vendor collection `FF01/02`.
- Live USB control headers captured through Linux usbmon, limited to feature reports A0/A1 from this VID/PID.
- Full feature messages from the actual vendor executable under Wine 11.0, captured at the hidraw ioctl boundary. The trace excludes input reports and other devices. This establishes the messages sent by that executable through Wine; it is not a native-Windows USB capture.
- Community reference: qsxcv/UnofficialEGGWebConfig, revision `cc246318fc50df6dc05b6564b8ca02a6c2eaab50`. Claims were cross-checked against the executable and device, not assumed from the reference alone.

## Relevant static observations

| Address | Evidence |
|---|---|
| `0x403b20` | Load request A1/12, 80 ms wait, GET A0, 1024-byte configuration at report offset 16 |
| `0x403920` | Feature GET and busy status handling |
| `0x403c40` | Deserialize the wire payload into the UI structure |
| `0x404180` | Serialize, send A0/11, wait, read A1 status |
| `0x4042d0` | Internal-to-wire field mapping |
| `0x4045e0` | Firmware request A1/02, 50 ms wait |
| `0x411bd0` / `0x412030` | Read/write smoothing and downshift bits |
| `0x4118a0` | Sensor control IDs 1082 and 1084 |
| `0x4066a0` | GX Speed F1 / GX Safe F0 |

## Wire framing confirmed on the device

| Operation | Request | Nominal buffer | Observed return |
|---|---|---:|---:|
| Firmware | SET A1/02, GET A1 | 64 bytes | 63 bytes |
| Read profile | SET A1/12, GET A0 | 1041 bytes | 1040 bytes |
| Store profile | SET A0/11, GET A1 status | 1041 / 64 bytes | SET 1041 / GET 63 bytes |

The actual 1040-byte reply includes an embedded header (`00 01` or `A1 01` observed). The complete 1024-byte payload is already at offsets 16–1039. Do not shift it. The extra Windows-convention byte follows that payload and is padding. Short replies retain the embedded A1/status header. Other lengths are rejected.

Firmware bytes 17/18 are patch/major (`07 01` → 1.07). Status 01 means ready; 03 means busy. Writes are not automatically resent after an ambiguous error.

## Confirmed 1.07 encodings

Report offset **21** is the polling divider: 8000/divider. The vendor's dropdown order is 125, 250, 500, 1000, 2000, 4000, 8000 Hz; encoded as 64, 32, 16, 8, 4, 2, 1.

Report offset **27** contains two settings:

- Bits 0–1: smoothing Force off=2, Ripple off=0, Ripple on=1.
- Bits 2–3: CPI downshift Force off=8, Light timer=12, Medium timer=4, Default=0.
- Bits 4–7 are preserved.

All 14 dropdown choices plus a same-profile apply were exercised using the actual vendor controls and APPLY. Their captured SET reports form `tests/official-goldens.json`. Tests require the Python serializer to match each entire 1041-byte vendor write and its resulting payload.

## Native and persistence evidence

51 native configuration cases exercised polling, sensor fields, CPI levels/X/Y, active levels, filters/GX and mappings. 45 cases made an effective change; six selected an existing value and are explicitly marked as no-ops. Every case compared the full expected payload and restored the starting profile. Backups were saved before writing.

A separate physical USB disconnect/reconnect test applied 1000 Hz, observed removal and a new device generation, confirmed the whole payload persisted, then restored the user's original 4000 Hz profile. It proves persistence for that profile, not every possible combination.

Summary: `docs/VALIDATION.json`. Raw local runs remain outside the release in `validation/`; public regression fixtures contain the relevant device messages and provenance only.

## Limits

Feature acceptance and read-back do not measure effective polling frequency, CPI accuracy, physical lift-off distance, filtering strength, click latency or switch behavior. No such physical-performance result is claimed. Other firmware revisions and other mouse models are not write-enabled.
