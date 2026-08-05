---
name: team-memory-guide
description: Guide for storing and retrieving shared team memories in Maindex Teams. Use when working with team-scoped knowledge, onboarding to a team graph, or deciding what belongs in team vs personal memory.
---

You help team members use Maindex Teams effectively — shared knowledge that persists across people and sessions, with role-based access and optional injection review.

## Team vs Personal Memory

| Scope | When to use | Tools |
| --- | --- | --- |
| **Personal** | Your preferences, drafts, private notes | `maindex_keep`, `maindex_search`, `maindex_list` (no `team` param) |
| **Team** | Decisions, runbooks, specs the whole team needs | `maindex_team_keep`, `maindex_team_search`, or personal tools with `team` slug |

Use `team: personal` on search/list to explicitly scope to personal memories only.

## Core Team Tools

1. **`maindex_team_list`** — See teams you belong to and your role (`viewer`, `editor`, `manager`).
2. **`maindex_team_search`** — Search within a team by meaning (same retrieval tiers as personal search).
3. **`maindex_team_keep`** — Write to a team collection. Requires `team` slug + `collection` slug + `content`.
4. **`maindex_team_collection_create`** — Create a new collection (viewer+ can create when policy allows).

## Writing Good Team Memories

- **Headlines as assertions** — "We use OAuth2 + PKCE for mobile auth" not "Auth notes".
- **Tag with team context** — `project:api`, `domain:security`, `status:accepted`.
- **Set kind intentionally** — `decision` for choices, `constraint` for hard rules, `fact` for verified info.
- **One topic per memory** — Easier to link, review, and supersede later.

Team writes may enter **injection review** depending on team policy. Editors' memories can be quarantined until a manager approves. Do not assume immediate visibility for all roles.

## Reading Team Memory

Before answering team questions:

1. Run `maindex_team_search` with the team slug and a focused query.
2. Use `maindex_recall` on specific short IDs for full detail and links.
3. Check `canon_status` — prefer `accepted` over `draft` when both exist.

If results mention frozen teams, billing or elective freeze may be blocking writes — tell the user to contact a manager or owner.

## Collections Within Teams

Collections organize team knowledge by project, domain, or workflow:

- List team detail via `maindex_team_list` with `team_id` to see collections.
- Create with `maindex_team_collection_create` when starting a new workstream.
- Always pass the **collection slug** to `maindex_team_keep`.

Naming: lowercase, hyphenated slugs (`release-process`, `onboarding`).

## Linking Team Knowledge

Use `maindex_associate` for typed links between team memories (same as personal). Use `maindex_unassociate` to remove stale links.

Relation types that work well in teams:

- `depends_on` — prerequisite decisions or docs
- `supports` / `contradicts` — evidence chains
- `derived_from` — provenance from meetings or tickets
- `belongs_to` — hierarchy under a parent decision

## Handoff Checklist

When finishing team work, capture:

- Decisions made (`kind: decision`, `canon_status: accepted`)
- Open questions (`kind: question`)
- Constraints discovered (`kind: constraint`)
- Links to related memories via `maindex_associate`

Always confirm with the user before writing sensitive or irreversible team knowledge.
