# Acceptance matrix — 1.0.0-rc.1

Candidate status: **ready for review, not a published stable release**. Target: OP1 8k v2 (`3367:1978`), firmware **1.07**, Arch/Omarchy Linux x86_64. English UI; vendor-style organization with a dark palette requested by the user.

| Capability | Implemented | Source evidence | Real device evidence | Limit |
|---|---|---|---|---|
| Discovery / identity / firmware | Yes | Descriptor + vendor imports/routines | Read 1.07; selected vendor interface | One mouse at a time |
| Seven polling choices | Yes | Vendor routine + 7 differential SET reports | Native change/read-back + restoration | Effective report timing not measured |
| Smoothing / CPI downshift | Yes | Vendor UI controls + all 7 choices captured | Native change/read-back + restoration | Physical sensor effect not measured |
| CPI values, separate X/Y | Yes | Serializer + clamp routine | Each stage changed; X/Y split tested | CPI accuracy not measured |
| Enabled/active levels | Yes | Serializer/UI | Levels 1–4 read back and restored | No live event subscription |
| Lift-off / angle / Motion Sync / jitter / FPS / LED | Yes | Serializer/UI/reference cross-check | All fields changed/read back/restored | Physical behavior not bench-measured |
| Slamclick, five multiclick filters, GX modes | Yes | Serializer/UI; GX constants | Five filters + both GX modes changed/read back | Click/switch latency not measured |
| Seven physical mappings | Yes | Serializer/UI/reference | Each mapping slot changed/read back; primary click retained | Each physical gesture not separately verified |
| Full-profile verification | Yes | Transaction audit | All native cases checked all 1024 bytes | No concurrent third-party configurator guarantee |
| Durable backups / restore | Yes | Code audit, checksum/fault tests | Restore after each live case | Unknown/custom field differences refused |
| Persistence on USB reconnect | Yes | Independent removal/re-enumeration observation | 1000 Hz profile persisted; original 4000 Hz restored | One profile combination tested |
| Permissions / missing / busy / malformed / stale / failed write | Yes | Structured errors + fault injection | Access rule and reconnect verified | Physical unplug during a write not attempted |
| Pending edits / discard / keyboard paths | Yes | GTK integration tests | UI run on Hyprland | Assistive-technology audit not performed |
| Narrow tiling / scaling | Yes | Responsive containers | 12 page/size checks at 400/520/900 px + four at 2× scale | Final visual preference review remains |
| Install / run / remove from archive | Yes | Deterministic build + isolated runtime test | No development tree required | Isolated Arch runtime; Ubuntu workflow not yet run remotely |
| GitHub CI | Defined | `.github/workflows/ci.yml` | Not run remotely before upload | Local checks do not imply a green GitHub run |

## Release gates

- Review the candidate UI and supported scope; do not interpret configuration tests as physical-performance certification.
- Clean-install and layout checks passed locally; review the screenshots and rerun them on the release commit if code changes.
- Confirm the repository name/visibility and publication before creating a remote release.
- Run the workflow on the actual GitHub commit; inspect that result before calling it a stable published v1.

Known exclusions: firmware flashing, new mouse models, keyboard/macro/fixed-CPI action authoring, factory reset and automatic live profile updates. No claim of zero defects or complete Windows-tool parity is made.
