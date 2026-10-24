# Release-candidate audit

Scope: OP1 8k v2, firmware 1.07, Linux x86_64. English UI. Preserve the vendor tool's neutral appearance and four-tab structure, with layouts that adapt to tiling windows.

## Initial defects and resulting behavior

| Initial defect | Candidate behavior |
|---|---|
| Only modified bytes were checked after writing | All 1024 payload bytes must equal the desired profile |
| Backups had no restore flow or checksum | Durable backups, checksum validation, review and restricted restore |
| Backups lived under the program directory | User state directory independent of installation prefix |
| Write failures could look like a harmless read error | Structured uncertain-write result with the saved backup path |
| Unknown firmware could receive 1.07-specific fields | Writes gated to firmware 1.07 |
| Reading/closing could silently discard edits | Pending state and explicit discard decision |
| Backing up reloaded the UI | Device backup preserves edits |
| Inactive CPI values could be rewritten by widget clamping | Only explicitly edited CPI records are serialized |
| CLI communication was unbounded | Deadline plus subprocess deadline; no automatic write resend |
| Smoke check could activate an existing instance without testing | Independent demo/test instance and explicit failure exit status |
| Installed workers depended on the source working directory | Workers use the installed package location explicitly |
| Large fixed rows overflowed tiled windows | Compact navigation, stacked rows, scrollable content, wrapping actions |

## Release requirements

- Understood commands and fields with traceable source evidence.
- Real changes and full read-back; restore verified after every controlled case.
- Reconnect persistence recorded separately from configuration acceptance.
- Honest physical-performance limits and exact compatibility claims.
- Tested normal and fault paths; clean-prefix installation, execution and removal.
- Deterministic archive, attribution, documented dependencies and CI definition.
- GitHub visibility/publication confirmed only after the candidate is reviewable.

No firmware flashing, additional device models, cloud features or toolkit rewrite are in scope. See `ACCEPTANCE.md` for measured results and outstanding gates. No claim of zero defects is made.
