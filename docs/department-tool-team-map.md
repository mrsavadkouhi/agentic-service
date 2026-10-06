# Department-to-Tool-team map for verification

Inspection and operator decisions: 2026-10-06 (Asia/Tehran), through SSH to `mirza-ha1`.

**Agent execution remains inactive. All 30 mapped department entries are operator-verified; 42 unspecified entries use ticket-specific clarification.**

The initial inventory contained 92 teams: 12 Tool and 80 non-Tool. The explicitly requested merge moved one existing key and one source-only member from TapsiCloud-Tool into Cloud-Tool, then removed the empty source. The refreshed inventory contains 91 teams: 11 Tool and 80 non-Tool. Read-back verified preserved key owner, models, budget, expiry and metadata, unchanged non-Tool UI memberships, and Cloud's existing model/reasoning policies and 220/1d budget.

[Machine-readable map](department-tool-team-map.json) · [Current inventory](discovery/litellm-team-inventory.json) · [Before-merge inventory](discovery/litellm-team-inventory.before-cloud-merge.json) · [Verified merge report](discovery/cloud-team-merge.json)

All 72 department strings from the deployed department catalog match one live non-Tool team after case-insensitive comparison and outer-whitespace stripping. Internal spacing is preserved. The catalog has not been revalidated against live AD. Only team IDs, aliases and kinds were retained in these inventories; no keys, memberships or user emails are included.

The map contains 30 approved entries and 42 unspecified entries. All proposed destinations have been verified by the operator; unspecified mappings remain ticket-specific.

## Approved mappings

| Department(s) | Existing Tool team | Entries |
|---|---|---|
| `Tech & Product - Cloud` | `Cloud-Tool` | 1 |
| All eight `Tapsi Box - …` departments, including Executive Management | `TapsiBox-Tool` | 8 |

`TapsiBox-Manager-Tool` remains manual for access upgrades and provisioning. A department name never automatically selects it. `Admin-Tool` and `Platform-Tool` are also not implicit defaults.

## Additional verified mappings

| Department(s) | Approved Tool team | Entries |
|---|---|---|
| `Tech & Product - Cab` | `Cab-Tool` | 1 |
| `Tech & Product - Foundation` | `Foundation-Tool` | 1 |
| `Growth`; `Growth - Call Center`; `Growth - Creative`; `Growth - Executive Assistant`; `Growth - Growth`; `Growth - Growth Planning`; `Growth - Marketing`; `Growth - Operations`; `Growth - OPEX`; `Growth - OPS`; `Growth - Planning` | `Growth-Tool` | 11 |
| `Tech & Product - Integration` | `Integration-Tool` | 1 |
| `Tech & Product - One` | `One-Tool` | 1 |
| `Tech - Journey`; `Tech - Marketplace`; `Tech - Support`; `Tech - Tech`; `Tech & Product`; `Tech & Product - Tech & Product` | `Tech-Tool` | 6 |

## Full department review

| Department / live non-Tool alias | Tool team | Review state |
|---|---|---|
| `Consultant` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Corp.Comm - Corp.Comm` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Finance - Finance` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Finance - Finance-New Ventures` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Finance - Hesabres` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Finance - Payroll` | Unspecified; obtain ticket-specific mapping | unmapped |
| `FP&A - FP&A` | Unspecified; obtain ticket-specific mapping | unmapped |
| `FP&A - FP&A New Ventures` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Growth` | `Growth-Tool` | approved |
| `Growth - Call Center` | `Growth-Tool` | approved |
| `Growth - Creative` | `Growth-Tool` | approved |
| `Growth - Executive Assistant` | `Growth-Tool` | approved |
| `Growth - Growth` | `Growth-Tool` | approved |
| `Growth - Growth Planning` | `Growth-Tool` | approved |
| `Growth - Marketing` | `Growth-Tool` | approved |
| `Growth - Operations` | `Growth-Tool` | approved |
| `Growth - OPEX` | `Growth-Tool` | approved |
| `Growth - OPS` | `Growth-Tool` | approved |
| `Growth - Planning` | `Growth-Tool` | approved |
| `HR - Admin` | Unspecified; obtain ticket-specific mapping | unmapped |
| `HR - HR` | Unspecified; obtain ticket-specific mapping | unmapped |
| `HR - HRBP` | Unspecified; obtain ticket-specific mapping | unmapped |
| `HR - Office` | Unspecified; obtain ticket-specific mapping | unmapped |
| `HR - People & Culture` | Unspecified; obtain ticket-specific mapping | unmapped |
| `HR - Workplace & People Operations` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Internal Audit - Internal Audit` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Investment - Executive Assistant` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Investment - Investment` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Legal & Regulatory - Legal & Regulatory` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Management Office` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Management Office - Executive Assistant` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Management Office - Management Office` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Operations - Warehouse` | Unspecified; obtain ticket-specific mapping | unmapped |
| `OPS` | Unspecified; obtain ticket-specific mapping | unmapped |
| `OPS - DA & Cities` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Security - Executive Assistant` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Security - Fraud` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Security - Guard` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Security - Procurement` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Security - Reception` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Security - Security` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Security - SOS` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Security - Verification` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Strategy - Strategy` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Super App Growth & Business Development` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Super App Growth & Business Development -  Market Insight` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Super App Growth & Business Development - Business Development` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Super App Growth & Business Development - Growth Technology` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Super App Growth & Business Development - Market Insight` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Super App Strategy & CX - Super App Strategy & CX` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Tapsi Box - Data` | `TapsiBox-Tool` | approved |
| `Tapsi Box - Design` | `TapsiBox-Tool` | approved |
| `Tapsi Box - Executive Management` | `TapsiBox-Tool` | approved |
| `Tapsi Box - HR` | `TapsiBox-Tool` | approved |
| `Tapsi Box - Operations` | `TapsiBox-Tool` | approved |
| `Tapsi Box - OPS` | `TapsiBox-Tool` | approved |
| `Tapsi Box - Product` | `TapsiBox-Tool` | approved |
| `Tapsi Box - Tech` | `TapsiBox-Tool` | approved |
| `Tapsi Market - Management` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Tapsi Market - Operations & Logistics` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Tapsi Market - Tech & Product` | Unspecified; obtain ticket-specific mapping | unmapped |
| `Tech - Journey` | `Tech-Tool` | approved |
| `Tech - Marketplace` | `Tech-Tool` | approved |
| `Tech - Support` | `Tech-Tool` | approved |
| `Tech - Tech` | `Tech-Tool` | approved |
| `Tech & Product` | `Tech-Tool` | approved |
| `Tech & Product - Cab` | `Cab-Tool` | approved |
| `Tech & Product - Cloud` | `Cloud-Tool` | approved |
| `Tech & Product - Foundation` | `Foundation-Tool` | approved |
| `Tech & Product - Integration` | `Integration-Tool` | approved |
| `Tech & Product - One` | `One-Tool` | approved |
| `Tech & Product - Tech & Product` | `Tech-Tool` | approved |

## Other live non-Tool teams

These eight aliases are absent from the deployed department catalog; their role as an AD department key is unverified. Do not infer departments from UI entitlement memberships.

| Live alias | Department status |
|---|---|
| `Conf - KB` | Not in deployed catalog |
| `Group Finance - Group Finance` | Not in deployed catalog |
| `HR - KB` | Not in deployed catalog |
| `IT` | Not in deployed catalog |
| `UI - Astra` | Not in deployed catalog |
| `UI - Fable` | Not in deployed catalog |
| `UI - Opus` | Not in deployed catalog |
| `UI - Sol` | Not in deployed catalog |

## Ticket-specific mapping and team creation

For an unspecified/unapproved mapping, set On Hold and ask the assigned technician, or the request's original DWE in-charge person if null. They supply the department/team mapping in a ticket note and set Open. Validate the department from authoritative identity and use the supplied mapping only for this ticket. Keep its note, actor and team ID in workflow/audit evidence; do not update the department-wide map or reuse it automatically for later tickets.

Resolve the specified existing Tool team. If it does not exist, create it as an approved supporting step of the key-creation workflow using explicit initial model grants, budget/reset and all other necessary terms. Unspecified terms use clarification again. Record the resulting immutable team ID and reconcile retries before issuing a key. A newly created team persists in LiteLLM, but its ticket-specific department mapping does not become a shared policy.

Never use this flow to provision/upgrade the manual manager team, evade unsupported direct-key model requests, widen existing team grants, or move an existing key. LibreChat non-Tool memberships remain separate. Existing-key reasoning/budget jobs keep their current Tool team. The completed one-off Cloud merge was explicitly operator-directed and is not an automated ticket job.
