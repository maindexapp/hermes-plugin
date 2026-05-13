# Maindex — Hermes Agent Plugin

Persistent, relational memory for [Hermes Agent](https://github.com/NousResearch/hermes-agent). This plugin connects Hermes to the [Maindex Expert API](https://expert.maindex.io) — a structured knowledge graph with multi-tier search, typed associations, collections, and full revision history. Your agent gets long-term memory that works across sessions, projects, and platforms.

This plugin uses the **Hermes MemoryProvider interface** to expose the Maindex Expert API through Hermes's tool system, lifecycle hooks, and configuration flow. It connects to the Expert REST API at `https://expert.maindex.io` — the same backend that powers the 14-tool MCP interface — but surfaces the 5 most essential tools through Hermes's native tool routing, along with automatic prefetch, sync, and memory mirroring.

[Website](https://maindex.io) | [Help & FAQ](https://maindex.io/help) | [Dashboard](https://maindex.io/dashboard)

## What's Included

| Component                              | Description                                                                                                                  |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **Memory Provider** (plugin)           | MemoryProvider implementation connecting Hermes to the Maindex Expert REST API with dual auth (API key + OAuth bearer token) |
| **5 Agent Tools**                      | `maindex_search`, `maindex_keep`, `maindex_recall`, `maindex_update`, `maindex_forget`                                      |
| **Automatic Prefetch**                 | Semantic search before each turn surfaces relevant memories as context                                                       |
| **Turn Sync**                          | Conversation facts are stored automatically after each turn                                                                  |
| **Memory Mirroring**                   | Built-in MEMORY.md and USER.md writes are mirrored to your Maindex graph                                                    |
| **Maindex Core** (skill)              | Memory conventions, tool guidance, archivist behavior, and decision tree for effective knowledge management                    |
| **Memory Organizer** (skill)          | Audit and organize your knowledge graph — find duplicates, create links, standardize tags, build collections                  |

## Prerequisites

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) installed
- A Maindex account — [sign up at maindex.io](https://maindex.io)
- An API key from [your dashboard](https://maindex.io/dashboard), or an OAuth bearer token

## Installation

Copy (or symlink) this directory into your Hermes Agent's plugin directory:

```bash
# From your hermes-agent repo root:
cp -r /path/to/hermes-plugin plugins/memory/maindex

# Or symlink for development:
ln -s /path/to/hermes-plugin plugins/memory/maindex
```

Then activate via the setup wizard or config:

```bash
# Interactive setup (prompts for API key):
hermes memory setup

# Or set directly:
hermes config set memory.provider maindex
```

### Skills

To use the bundled skills, copy them into your Hermes skills directory:

```bash
cp -r plugins/memory/maindex/skills/* ~/.hermes/skills/
```

## Configuration

Set credentials via environment variables in your profile's `.env` file, or through `hermes memory setup`:

| Variable             | Description                                     | Required |
| -------------------- | ----------------------------------------------- | -------- |
| `MAINDEX_API_KEY`    | API key from [dashboard](https://maindex.io/dashboard) | One of these |
| `MAINDEX_TOKEN`      | OAuth bearer token (alternative to API key)     | is required  |
| `MAINDEX_COLLECTION` | Default collection slug for scoping (optional)  | No       |

Both `MAINDEX_API_KEY` and `MAINDEX_TOKEN` are supported. Bearer token takes priority if both are set.

## Tools

Once active, your agent has access to 5 Maindex tools:

- **`maindex_search`** — Full-text, fuzzy, semantic, and hybrid search across memories. Filter by tags, kind, and collection.
- **`maindex_keep`** — Store a new memory with headline, body, tags, kind, and collection assignment.
- **`maindex_recall`** — Retrieve a specific memory by ID (UUID or short ID like `mem-1a`).
- **`maindex_update`** — Revise an existing memory with full revision history preserved. Modes: `body_append`, `body_replace`, `headline_replace`, `headline_and_body_replace`, `revision_only`. Can also change `kind`, `canon_status`, `confidence`, and `verification_status`.
- **`maindex_forget`** — Soft-delete a memory (restorable).

## Lifecycle Hooks

The plugin integrates with Hermes's memory lifecycle:

- **Prefetch**: Before each turn, searches Maindex for memories relevant to the user's message and injects them as context.
- **Sync**: After each turn, stores conversation content as a note tagged `source:hermes`.
- **Memory Mirror**: When the built-in memory system writes to MEMORY.md or USER.md, the content is mirrored to Maindex as a fact.
- **Pre-Compress**: Before context compression discards old messages, a summary snapshot is stored in Maindex.

## Expert API

This plugin connects to the [Maindex Expert API](https://expert.maindex.io) — the full-fidelity knowledge graph backend. The Expert API provides:

- 14 MCP tools (this plugin exposes the 5 most essential through Hermes's tool interface)
- Structured memories with headline, body, kind, canon status, confidence, and verification status
- Typed associations between memories (supports, contradicts, depends_on, expands, etc.)
- Collections for project-level organization
- Full revision history on every memory
- Multi-tier search: exact match, relaxed OR, fuzzy trigram, semantic, and hybrid

The complete Expert API documentation is available at [expert.maindex.io/docs](https://expert.maindex.io/docs).

## Links

- [Maindex](https://maindex.io) — Website
- [Expert API Docs](https://expert.maindex.io/docs) — Full OpenAPI documentation
- [Setup Guide](https://maindex.io/help) — Step-by-step setup for all platforms
- [Dashboard](https://maindex.io/dashboard) — Manage API keys and view usage
