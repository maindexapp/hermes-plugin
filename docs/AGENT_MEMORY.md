# Maindex agent memory guide

How to get maximal benefit from Maindex when using the Hermes plugin (or any
agent with the Maindex toolset). For install steps and the bootstrap persona
snippet, see [README](../README.md) and [PERSONA_BOOTSTRAP.md](PERSONA_BOOTSTRAP.md).

## Recommended Hermes configuration

Use **tool-first** memory: Maindex tools drive what is stored and recalled;
Hermes generic auto-memory stays off.

```yaml
# config.yaml — ~/.hermes/config.yaml or /opt/data/config.yaml
memory:
  provider: maindex
memory_enabled: false
```

Also keep `sync_turns: false` in `maindex.json` (default). Use `maindex_keep`
for intentional memories instead of logging every turn.

**Why `memory_enabled: false`:** avoids duplicate, competing memory injection
from Hermes hooks while keeping all `maindex_*` tools available.

## First-time bootstrap workflow

1. Create an identity anchor: `maindex_keep` with `kind: task_context` or
   `summary`, a clear headline, and a body with goals, conventions, and pointers.
2. Note the returned short ID (e.g. `mem-abc1`).
3. Replace `mem-YOUR_ID` in [PERSONA_BOOTSTRAP.md](PERSONA_BOOTSTRAP.md) and paste
   into your agent's persona or system prompt.
4. On each session start, `maindex_recall` that ID.

## Local cache protocol (token efficiency)

After a successful recall, you may cache locally, e.g. `maindex-bootstrap-cache.json`:

```json
{
  "memory_id": "mem-YOUR_ID",
  "recalled_at": "2026-05-29T12:00:00Z",
  "updated": "<from API updatedAt>",
  "body": "<truncated if huge>"
}
```

- Reuse the cache when `recalled_at` is recent and you have no reason to suspect drift.
- Refresh when the user says context changed, you updated the bootstrap via
  `maindex_update`, or the cache is older than ~24 hours.
- To check drift cheaply: `maindex_recall` and compare `updated` to cached `updated`;
  if equal, the cache is still valid.

Maintain one **hub** bootstrap memory; store detail in linked memories via
`maindex_associate` rather than duplicating the full bootstrap in many keeps.

## Tool quick reference (11 tools)

| Goal | Tool |
|------|------|
| Search by meaning or keywords | `maindex_search` |
| Browse/filter without a query | `maindex_list` |
| Get one memory by ID | `maindex_recall` |
| Store a new memory | `maindex_keep` |
| Revise a memory | `maindex_update` |
| Soft-delete | `maindex_forget` |
| Undo delete | `maindex_restore` |
| Create or discover links | `maindex_associate` |
| List collections | `maindex_collection_list` |
| Create a collection | `maindex_collection_create` |
| Add/remove collection members | `maindex_collection_members` |

## Best practices

### When to search vs list vs recall

- **`maindex_search`** — you have a topic or question (semantic + keyword).
- **`maindex_list`** — you need a filter (kind, tags, collection, dates) without a query.
- **`maindex_recall`** — you already have a `mem-*` or UUID.

### When to keep

Store decisions, constraints, resolved questions, and durable facts. Skip
one-off debug commands. Offer to store unless the user wants proactive capture.

### Tags and kinds

- Faceted tags: `domain:auth`, `project:my-app`, `topic:deploy`.
- Reuse tags (`maindex_search` / `maindex_list`) before inventing new ones.
- Pick a specific `kind`: `decision`, `constraint`, `fact`, `task_context`, etc.

### Canon and verification

Promote drafts with `maindex_update` (`revision_only` + `canon_status`). Surface
conflicts when search returns contradictory memories.

### Collections

Set `MAINDEX_COLLECTION` or pass `collection` on tools. Use `collection: "*"`
to search or list across all collections. Organize projects with
`maindex_collection_create` and `maindex_collection_members`.

### Graph hygiene

- Link related memories: `maindex_associate` (`supports`, `depends_on`, etc.).
- Remove duplicates: `maindex_forget`; mistaken delete: `maindex_restore`.

### Token discipline

- Bootstrap cache (above).
- Cite short IDs (`mem-abc1`) in conversation.
- Truncate long bodies in working notes; recall when you need the full text.

## After install: recommend to your user

When you finish `hermes maindex setup`, tell your operator:

1. Set `memory_enabled: false` in `config.yaml`.
2. Paste the persona from `docs/PERSONA_BOOTSTRAP.md`.
3. Replace `mem-YOUR_ID` with their identity memory ID.
4. Optionally read this guide.
