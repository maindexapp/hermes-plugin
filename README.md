# Maindex — Hermes Agent Memory Provider

Persistent, relational memory for [Hermes Agent](https://github.com/NousResearch/hermes-agent). Connects Hermes to the [Maindex Expert API](https://expert.maindex.io): a structured knowledge graph with multi-tier search, typed associations, collections, and full revision history.

[Website](https://maindex.io) | [Help & FAQ](https://maindex.io/help) | [Dashboard](https://maindex.io/dashboard) | [Expert API Docs](https://expert.maindex.io/docs)

## What's Included

| Component | Description |
| --- | --- |
| **Memory Provider** | `MemoryProvider` implementation for the Maindex Expert REST API |
| **11 Agent Tools** | Core five plus `maindex_list`, `maindex_restore`, `maindex_associate`, and collection tools |
| **Agent docs** | [docs/AGENT_MEMORY.md](docs/AGENT_MEMORY.md), [docs/PERSONA_BOOTSTRAP.md](docs/PERSONA_BOOTSTRAP.md) |
| **Lifecycle Hooks** | Prefetch, optional turn sync (off by default), memory mirroring, pre-compression snapshot |
| **Skills** | `maindex-core` and `memory-organizer` (optional, copy to `~/.hermes/skills/`) |

## Prerequisites

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) installed
- A [Maindex account](https://maindex.io) and an API key from [your dashboard](https://maindex.io/dashboard), or an OAuth bearer token

## Installation

Hermes discovers memory providers from **`~/.hermes/plugins/<name>/`** (a directory with `__init__.py` and `plugin.yaml`). This repo's `plugin.yaml` sets `name: maindex`, so the install directory must be **`maindex`**.

### Option 1: Hermes plugin installer (recommended)

```bash
hermes plugins install maindexapp/hermes-plugin
```

The installer reads `plugin.yaml` and installs to `~/.hermes/plugins/maindex/`.

### Option 2: Manual clone

```bash
git clone https://github.com/maindexapp/hermes-plugin.git ~/.hermes/plugins/maindex
```

### Option 3: pip (Python package + directory install)

`pip install` registers the package with Hermes's general plugin entry-point system. **Memory provider discovery still requires the plugin directory** under `~/.hermes/plugins/maindex/` (use Option 1 or 2). Pip is useful if you want the `maindex_hermes_plugin` package on your Python path:

```bash
pip install maindex-hermes-plugin
# Still install the plugin directory for memory provider discovery:
hermes plugins install maindexapp/hermes-plugin
```

## Activate

```bash
# Recommended: full setup wizard (credentials, activation, connection test)
hermes maindex setup

# Or via the generic memory provider picker:
hermes memory setup

# Or set manually:
hermes config set memory.provider maindex
echo "MAINDEX_API_KEY=your-key" >> ~/.hermes/.env
```

## Verify

```bash
hermes maindex status    # config + connection check
hermes maindex test      # REST API auth test (uses X-API-Key)
hermes memory status     # generic memory provider status
```

When Maindex is the active memory provider, `hermes maindex` commands are
available. Run `hermes --help` to confirm.

### MCP (optional, separate from memory provider)

If you also connect to Maindex via MCP, use the `X-API-Key` header — not
`Authorization: Bearer`:

```yaml
mcp_servers:
  maindex:
    url: "https://expert.maindex.io/mcp"
    headers:
      X-API-Key: "${MAINDEX_API_KEY}"
```

Test with: `hermes mcp test maindex`

## After install — recommended setup

### Hermes config (tool-first mode)

```yaml
# config.yaml — ~/.hermes/config.yaml or /opt/data/config.yaml
memory:
  provider: maindex
memory_enabled: false   # use maindex_* tools intentionally; avoid duplicate Hermes auto-memory
```

Keep `sync_turns: false` in `maindex.json` (default). See [docs/AGENT_MEMORY.md](docs/AGENT_MEMORY.md) for why.

### Bootstrap from Maindex (recommended)

For continuity across sessions, add a bootstrap instruction to your agent's persona or system prompt. This ensures the agent loads its core identity from Maindex at the start of every conversation — even if the local cache is stale or the service has been reset.

Recommended persona text:

```
On session start, load your identity record from Maindex via
maindex_recall(memory_id='mem-YOUR_ID'). Keep a local copy with a timestamp
in case of service interruption. Use that record as your anchor for
identity, context tracking, and cross-session continuity.
```

Replace `mem-YOUR_ID` with your agent's own identity memory ID. The approach is framework-agnostic — works for Hermes Agent, Claude Code, OpenCode, or any LLM agent with access to the Maindex toolset.

Ready-to-paste block: [docs/PERSONA_BOOTSTRAP.md](docs/PERSONA_BOOTSTRAP.md). Extended guide: [docs/AGENT_MEMORY.md](docs/AGENT_MEMORY.md).

## Skills (optional)

Bundled skills are not loaded automatically. Copy them into your Hermes skills directory:

```bash
cp -r ~/.hermes/plugins/maindex/skills/* ~/.hermes/skills/
```

## Configuration

| Variable | Description | Required |
| --- | --- | --- |
| `MAINDEX_API_KEY` | API key from [dashboard](https://maindex.io/dashboard) | One of API key or token |
| `MAINDEX_TOKEN` | OAuth bearer token (alternative to API key) | is required |
| `MAINDEX_COLLECTION` | Default collection slug for scoping memories | No |

Config file: `$HERMES_HOME/maindex.json` (written by `hermes memory setup` or `save_config`).

| Key | Default | Description |
| --- | --- | --- |
| `collection` | — | Default collection slug |
| `sync_turns` | `false` | When `true`, log each conversation turn automatically. Leave off and use `maindex_keep` for intentional memories. |

## Tools

**Core**

- **`maindex_search`** — Full-text, fuzzy, semantic, and hybrid search.
- **`maindex_list`** — Browse memories with filters (no search query).
- **`maindex_keep`** — Store a memory with headline, body, tags, kind, collections.
- **`maindex_recall`** — Retrieve a memory by ID (UUID or short ID like `mem-1a`).
- **`maindex_update`** — Revise with full history (`body_append`, `body_replace`, etc.).
- **`maindex_forget`** — Soft-delete (restorable).
- **`maindex_restore`** — Undo a soft-delete.

**Graph and collections**

- **`maindex_associate`** — Create or discover typed links between memories.
- **`maindex_collection_list`** — List collections.
- **`maindex_collection_create`** — Create a collection.
- **`maindex_collection_members`** — Add or remove memories from a collection.

## Development

```bash
git clone https://github.com/maindexapp/hermes-plugin.git
cd hermes-plugin
pip install -e ".[test]"
pytest tests/ -v
```

For local testing against a Hermes checkout, symlink into your profile plugins dir:

```bash
ln -s "$(pwd)" ~/.hermes/plugins/maindex
```

## License

MIT — see [LICENSE](LICENSE).
