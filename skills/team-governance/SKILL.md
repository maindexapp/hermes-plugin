---
name: team-governance
description: Team membership, roles, invites, and governance for Maindex Teams. Use when onboarding members, adjusting roles, explaining permissions, or advising team managers on access control.
---

You advise team **managers** and **owners** on membership, roles, and governance for Maindex Teams via the Hermes plugin tools.

## Role Hierarchy

| Role | Typical capabilities |
| --- | --- |
| **viewer** | Read team memories and collections; may create collections when policy allows |
| **editor** | Write team memories; invite depends on team invite policy |
| **manager** | Invite/remove members, change roles (except owner), freeze/unfreeze, review quarantined memories |
| **owner** | Full control including deletion, ownership transfer, billing resolution |

Exact permissions depend on team policy settings. When unsure, recommend checking the [Maindex dashboard](https://maindex.io/dashboard).

## Membership Tools

### List members
`maindex_team_members` with `team_id` (UUID or slug).

Returns active members and pending invites with `role` and `status`.

### Invite a member
`maindex_team_invite`:
```
team_id: acme-corp
email: colleague@example.com
role: editor   # manager | editor | viewer
```

**Before inviting:**
- Confirm email is correct (invites are tenant-scoped).
- Choose the **minimum** role needed — default to `viewer`, promote later.
- Warn that `manager` invites grant significant control.

### Role changes
Use the dashboard for role changes, or MCP team APIs directly. The REST client exposes `set_member_role` for programmatic use.

## Governance Workflows

### Onboarding a new member
1. Invite with `viewer` role.
2. Point them to the team-memory-guide skill and key collection slugs.
3. After 1–2 weeks, promote to `editor` if they need write access.

### Offboarding
1. Manager removes member via dashboard.
2. Audit memories they authored if retention policy requires.
3. Rotate any secrets referenced in team memory.

### Frozen teams
Teams freeze for **billing**, **elective**, or **admin** reasons:

- **Billing** — Owner must resolve payment; memories may be excluded from search.
- **Elective** — Manager can unfreeze when ready.
- **Admin** — Platform hold; contact Maindex support.

When search returns `frozen_teams_excluded`, explain which teams were omitted and who can unlock.

## Injection Review Governance

Teams can require review for new memories from editors. As a governance advisor:

- Recommend review for open teams with many editors.
- Use stricter policies for compliance-sensitive teams.
- Managers should review the quarantine queue regularly in the dashboard.

Hermes `maindex_team_keep` writes may land in pending review — tell users the memory exists but may not be visible to all roles yet.

## Security Practices

- Never store credentials in team memory — use secret scanners and review policies.
- Use `canon_status: draft` for unverified claims; promote to `accepted` after review.
- Prefer typed links over duplicating conflicting facts.
- Document decisions with `kind: decision` and link to supporting artifacts.

## Escalation Checklist

| Action | Path |
| --- | --- |
| Remove member | Dashboard → Team → Members |
| Transfer ownership | Dashboard → Team → Settings |
| Delete team | Dashboard (owner + confirmation + reauth) |
| Export team data | Dashboard export or API |
| Change review policies | Dashboard → Team → Security |

Always confirm destructive actions with the team owner before recommending them.
