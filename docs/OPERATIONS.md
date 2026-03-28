# Operations Guide

## Typical lifecycle

### 1. Install dependencies

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
```

### 2. Download the DBLP dump

```bash
python -m dblp_mcp.cli download --destination data/dblp.xml.gz
```

Behavior:
- the file is downloaded only once per destination by default
- rerunning the command reuses the local file unless `--replace` is supplied

### 3. Build the SQLite database

```bash
python -m dblp_mcp.cli import --xml-path data/dblp.xml.gz --database-path data/dblp.sqlite
```

Behavior:
- import is streaming and memory-bounded
- a temporary SQLite file is built and swapped into place when complete
- if import fails, the previous good database remains in place

### 4. Smoke-test the database

```bash
python -m dblp_mcp.cli search --database-path data/dblp.sqlite --query "graph neural networks"
python -m dblp_mcp.cli get --database-path data/dblp.sqlite --dblp-key "conf/icse/GropengiesserDB25"
```

### 5. Use through MCP

Configure LM Studio or another MCP client to launch:

- command: `.venv/bin/python`
- args: `app.py`
- cwd: repository root
- env: `DBLP_MCP_DATA_DIR=/path/to/data`

## Common maintenance tasks

### Rebuild after code/schema changes

The simplest supported migration path is rebuild:

```bash
python -m dblp_mcp.cli import --xml-path data/dblp.xml.gz --database-path data/dblp.sqlite
```

This is especially appropriate when core import schema or FTS behavior changes.

### Check database state

Use MCP tool `get_dblp_status` to inspect:
- file existence
- DB size
- publication and contributor counts
- abstract count
- abstract fetch log count
- recent import runs

### Fetch and cache an abstract

Use MCP tool `fetch_publication_abstract` with a `dblp_key`.

Expected outcomes:
- `cached`
- `fetched`
- `unsupported`
- `not_found`

### Investigate abstract issues

Inspect `abstract_fetch_logs` in SQLite.

Examples:

```sql
SELECT *
FROM abstract_fetch_logs
ORDER BY created_at DESC
LIMIT 20;
```

```sql
SELECT provider, status, error_code, COUNT(*)
FROM abstract_fetch_logs
GROUP BY provider, status, error_code
ORDER BY COUNT(*) DESC;
```

Use these logs to identify publishers or identifier patterns that still need provider support.

## File layout in `data/`

Typical local state:

- `dblp.xml.gz`: raw DBLP dump
- `dblp.dtd`: DBLP DTD used for entity handling during import
- `dblp.sqlite`: searchable SQLite database
- optional log/output files created during local debugging

## Performance notes

- first import of the full DBLP dump can take significant time and disk space
- SQLite file size is expected to be large for the full DBLP corpus
- keeping the raw XML dump allows rebuilds without downloading again
- abstract fetching is cheap relative to full import because it is on-demand and cached

## Safe operating assumptions

- use only public data sources for abstract fetching
- do not treat `refresh=True` as a bulk crawler mode
- monitor `abstract_fetch_logs` before adding new provider logic
- prefer official/public APIs over HTML scraping when extending provider support

## Recommended validation commands

```bash
.venv/bin/python -m pytest
.venv/bin/python -m compileall src tests app.py
```


## Full-text fetching

Use MCP tools `fetch_publication_fulltext` or `fetch_publication_fulltexts` for lawful full-text retrieval.

Current behavior:
- caches PDFs under `data/fulltext/`
- stores extracted text and metadata in SQLite
- rejects presentation-like PDFs based on page geometry
- currently returns text plus local file metadata; page images are not yet generated

Supported full-text providers currently include arXiv, IEEE DOI resolution, ACM DOI-based PDF candidates, and OpenAlex OA PDF discovery.


## Privileged mode

The MCP server hides `download_dblp_dump` and `build_dblp_sqlite` unless it is launched with `--privileged`. Use privileged mode only for trusted operator sessions that need to refresh raw DBLP data or rebuild the SQLite database.


## Security-oriented runtime settings

- Set `DBLP_MCP_DATA_DIR` explicitly in production-like setups.
- Keep all tool paths inside that directory; the server now rejects paths outside it.
- Set `DBLP_MCP_ENABLE_NETWORK=0` if you want a read-only, no-egress deployment.
- Tune `DBLP_MCP_ABSTRACT_TIMEOUT_SECONDS`, `DBLP_MCP_FULLTEXT_TIMEOUT_SECONDS`, and `DBLP_MCP_MAX_FULLTEXT_PDF_BYTES` for your environment.

Use `get_recent_fetch_failures` to inspect recent abstract/fulltext fetch failures without opening SQLite manually.


Additional controls:
- `DBLP_MCP_ENABLE_ABSTRACT_NETWORK=0` disables abstract providers only
- `DBLP_MCP_ENABLE_FULLTEXT_NETWORK=0` disables fulltext providers only
- batch tools enforce configurable limits for abstract and fulltext requests

- `DBLP_MCP_PROVIDER_DELAY_MIN_SECONDS` / `DBLP_MCP_PROVIDER_DELAY_MAX_SECONDS` add a small randomized default delay before provider requests; provider-specific overrides use names like `DBLP_MCP_PROVIDER_DELAY_OPENALEX_MIN_SECONDS` and `DBLP_MCP_PROVIDER_DELAY_IEEE_PDF_MAX_SECONDS`
