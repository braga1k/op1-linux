# Changelog

## 1.0.0 — 2026-10-24

- First stable release, promoted from the reviewed and tested 1.0.0-rc.1.
- Same application behavior and supported hardware scope as rc.1.
- Physical-performance measurements and unverified gestures remain explicit in the acceptance matrix.

## 1.0.0-rc.1 — 2026-10-24

- English interface and public documentation.
- Vendor-style four-tab organization, dark background and responsive tiling layouts.
- 51 live configuration cases, 15 captured vendor cases and physical reconnect persistence check.
- Full-profile verification after writes, firmware gating and durable backups.
- Backup review and restore for managed settings; custom/unknown differences are refused.
- Pending-change tracking, explicit discard decisions and preserved edits when backing up.
- Structured device/access/write-state errors and bounded worker execution.
- Installable archive with desktop launcher, removal support and automated validation.

This is a release candidate. See `docs/ACCEPTANCE.md` for measured coverage and remaining release gates.
