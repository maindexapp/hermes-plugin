# Hermes plugin review (2026-11-09)

**Scope:** Code (`__init__.py` REST client + 19 tools), skills, README/docs vs [maindex.io/help](https://maindex.io/help/), [Teams guide](https://maindex.io/help/teams/), Expert API v1.2.2.

## Verdict

| Area | Status |
|------|--------|
| **REST / tools implementation** | OK — 19 tools; team routes; tests **151 passed** |
| **vs Expert MCP** | Expected gap — no Hermes wrappers for `memory_bulk_*`, `memory_supersede`, `collection_unlock`, `system_report_bug` (documented; use Expert MCP or dashboard) |
| **Skills / docs** | **Updated** — synced Teams roles, tool counts, conventions with site + shared plugin content |
| **Plugin version** | **1.4.1** (skills/docs only; no API behavior change) |

## Changes made (local — publish when ready)

- `skills/maindex-core/SKILL.md` — conversations, superseding, teams workspace, 19-tool tree, MCP gap note
- `skills/team-memory-guide/SKILL.md` — owner role, collection-create permissions, help links
- `skills/team-governance/SKILL.md` — viewer/editor permissions vs [Teams guide](https://maindex.io/help/teams/)
- `docs/AGENT_MEMORY.md` — 19-tool quick reference + teams
- `README.md`, `plugin.yaml` — v1.4.1

## Founder action

```bash
cd ~/code/maindex-repos/plugins
./publish.sh hermes-plugin   # when you want GitHub updated
```

Copy refreshed skills to `~/.hermes/skills/` if you use bundled skills locally.
