> **Disclaimer:** This project was written entirely by AI-assisted coding agents. Human review is strongly recommended before production use.

# Quickstart

## 1. Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
```

## 2. Set the data directory

```bash
export DBLP_MCP_DATA_DIR=/absolute/path/to/data
```

## 3. Run the server

Normal mode:

```bash
python app.py
```

Privileged operator mode:

```bash
python app.py --privileged
```

## 4. LM Studio config

```json
{
  "mcpServers": {
    "dblp": {
      "command": "/path/to/.venv/bin/python",
      "args": ["app.py"],
      "cwd": "/path/to/repo",
      "env": {
        "DBLP_MCP_DATA_DIR": "/absolute/path/to/data"
      }
    }
  }
}
```

## 5. Health and debugging

Use MCP tools `get_dblp_status` and `get_recent_fetch_failures` to verify the database and inspect recent enrichment failures.
