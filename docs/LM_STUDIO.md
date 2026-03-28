# LM Studio MCP Setup

This guide shows how to connect LM Studio to the local DBLP MCP server.

## Preconditions

Set `DBLP_MCP_DATA_DIR` explicitly in the LM Studio config. The server now expects an explicit data directory unless started with `--allow-implicit-data-dir`.


Before using the MCP server from LM Studio, make sure the local database already exists:

- `data/dblp.xml.gz`
- `data/dblp.dtd`
- `data/dblp.sqlite`

If you still need to build them:

```bash
python -m dblp_mcp.cli download --destination data/dblp.xml.gz
python -m dblp_mcp.cli import --xml-path data/dblp.xml.gz --database-path data/dblp.sqlite
```

## MCP configuration

Use a stdio MCP server definition like this:

```json
{
  "mcpServers": {
    "dblp": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["app.py"],
      "cwd": "/absolute/path/to/repo",
      "env": {
        "DBLP_MCP_DATA_DIR": "/absolute/path/to/data"
      }
    }
  }
}
```

## Why stdio is expected

This server is implemented with FastMCP stdio transport. That means:

- LM Studio starts the server process for you
- the server communicates over stdin/stdout
- running `python app.py` manually without a connected client exits immediately

This is normal behavior.

## Recommended first checks in LM Studio

After adding the MCP config and reloading MCP servers, call these tools first:

### 1. `get_dblp_status`
Expected fields:
- `exists: true`
- a large `publications` count
- a nonzero database `size_bytes`

Example healthy values in this repository:
- `publications`: about 12.4 million
- `contributors`: about 4.1 million

### 2. `search_publications`
Example query:
- `graph neural networks`

This confirms LM Studio can both see the DB and run FTS queries.

### 3. `get_publication`
Example key:
- `conf/icse/GropengiesserDB25`

This confirms detailed publication lookup works.

### 4. `fetch_publication_abstract`
Example key:
- `conf/icse/GropengiesserDB25`

This confirms abstract providers, caching, and DB writes work.

## Suggested LM Studio prompts

- “Call `get_dblp_status` and tell me whether the DBLP database is loaded.”
- “Search for papers about graph neural networks.”
- “Get the publication `conf/icse/GropengiesserDB25`.”
- “Fetch the abstract for `conf/icse/GropengiesserDB25`.”

## Troubleshooting

### Problem: LM Studio connects, but the model claims the DB is empty

Usually this means one of these happened:

1. the model guessed instead of calling a status/search tool
2. LM Studio is using the wrong data directory
3. the database file was not built yet
4. LM Studio needs the MCP server reloaded after code changes

What to do:
- call `get_dblp_status`
- verify `DBLP_MCP_DATA_DIR` points to the correct `data/` directory
- verify `data/dblp.sqlite` exists
- reload or restart the MCP server in LM Studio

### Problem: the MCP server starts but immediately exits

That is expected when you run `python app.py` manually without an MCP client. LM Studio must launch it.

### Problem: search works in CLI but not in LM Studio

Check:
- the LM Studio config uses the correct Python executable from `.venv`
- `cwd` is the repository root
- `DBLP_MCP_DATA_DIR` points to the same `data/` directory you used for import
- LM Studio was reloaded after edits to the MCP server

### Problem: abstract fetching returns `unsupported`

That means the paper does not currently expose a supported lookup identifier for the implemented providers.

Current built-in abstract providers are:
- OpenAlex for DOI-backed papers
- arXiv for arXiv-backed papers

Inspect `abstract_fetch_logs` in SQLite to see what happened.

### Problem: abstract fetching returns `not_found`

That means a provider was attempted but did not return an abstract. This can happen when a public metadata source lacks an abstract even though the paper metadata is present.

### Problem: tool changes do not appear in LM Studio

Reload or restart MCP servers in LM Studio. The tool list is loaded from the running server process.

## Operator checklist

When in doubt, verify these items in order:

1. `.venv` exists and dependencies are installed
2. `data/dblp.sqlite` exists
3. LM Studio config points to the correct `.venv/bin/python`
4. `DBLP_MCP_DATA_DIR` points to the correct `data` directory
5. `get_dblp_status` reports a populated database
6. `search_publications` returns expected results

## Related docs

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/OPERATIONS.md`


## Full-text note

The current full-text tool returns extracted text plus local PDF metadata/path. It does not yet emit page images or attached PDF blobs directly to LM Studio.


IEEE and ACM support are implemented through lawful provider logic, but some papers may still return `not_found` if the site blocks non-browser retrieval or does not expose a usable PDF response.


## Privileged mode

If you want LM Studio to expose the administrative DBLP maintenance tools (`download_dblp_dump` and `build_dblp_sqlite`), change the args to:

```json
"args": ["app.py", "--privileged"]
```

Without `--privileged`, the server only exposes read/search/enrichment tools.

Network-backed abstract/fulltext tools can be disabled with `DBLP_MCP_ENABLE_NETWORK=0`. Returned PDF paths are relative to the configured data dir rather than absolute host paths.


For operator debugging, you can also call `get_recent_fetch_failures` to inspect why abstract/fulltext retrieval failed recently.
