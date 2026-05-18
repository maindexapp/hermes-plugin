# Maindex — Hermes Agent Memory Provider

Persistent, relational memory for [Hermes Agent](https://github.com/NousResearch/hermes-agent). Connects Hermes to the [Maindex Expert API](https://expert.maindex.io): a structured knowledge graph with multi-tier search, typed associations, collections, and full revision history.

[Website](https://maindex.io) | [Help & FAQ](https://maindex.io/help) | [Dashboard](https://maindex.io/dashboard) | [Expert API Docs](https://expert.maindex.io/docs)

## What's Included

| Component | Description |
| --- | --- |
| **Memory Provider** | `MemoryProvider` implementation for the Maindex Expert REST API |
| **5 Agent Tools** | `maindex_search`, `maindex_keep`, `maindex_recall`, `maindex_update`, `maindex_forget` |
| **Lifecycle Hooks** | Prefetch, turn sync, memory mirroring, pre-compression snapshot |
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
# Interactive setup (prompts for API key, runs connection check):
hermes memory setup

# Or set directly:
hermes config set memory.provider maindex
echo "MAINDEX_API_KEY=your-key" >> ~/.hermes/.env
```

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

## Tools

- **`maindex_search`** — Full-text, fuzzy, semantic, and hybrid search. Filter by tags, kind, collection.
- **`maindex_keep`** — Store a memory with headline, body, tags, kind, collections.
- **`maindex_recall`** — Retrieve a memory by ID (UUID or short ID like `mem-1a`).
- **`maindex_update`** — Revise with full history (`body_append`, `body_replace`, `headline_replace`, etc.).
- **`maindex_forget`** — Soft-delete (restorable).

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
