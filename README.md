# DBLP MCP Server

> **Disclaimer:** This project was written entirely by AI-assisted coding agents. Human review is strongly recommended before production use, publication, or security-sensitive deployment.

This project provides a Python MCP server for working with the DBLP computer science bibliography locally. It is designed around a two-step workflow:

1. download the raw DBLP XML dump from `https://dblp.org/xml/`
2. stream that XML into a normalized SQLite database that can be searched without loading the full dataset into RAM

On top of the bibliographic database, the server can also fetch and cache paper abstracts from supported public sources.

## Features

- download and cache the official DBLP XML dump
- stream `.xml` and `.xml.gz` files into SQLite using bounded memory
- search publications using SQLite FTS5
- inspect one publication by DBLP key
- fetch and cache abstracts from modular source providers
- fetch and cache legal full-text PDFs plus extracted text from modular source providers
- log unsupported abstract sources and provider failures for later development

## Installation

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
```

## Configuration

The server reads a small number of environment variables:

- `DBLP_MCP_DATA_DIR`: directory containing `dblp.xml.gz`, `dblp.dtd`, and `dblp.sqlite`
- `DBLP_MCP_BATCH_SIZE`: batch size used by the XML importer
- `DBLP_MCP_ENABLE_NETWORK`: set to `0` to disable abstract/fulltext network fetches
- `DBLP_MCP_ABSTRACT_TIMEOUT_SECONDS`: timeout for abstract providers
- `DBLP_MCP_FULLTEXT_TIMEOUT_SECONDS`: timeout for fulltext providers
- `DBLP_MCP_DOWNLOAD_TIMEOUT_SECONDS`: timeout for privileged DBLP downloads
- `DBLP_MCP_MAX_FULLTEXT_PDF_BYTES`: maximum accepted PDF size for fulltext caching

Default paths are derived from `DBLP_MCP_DATA_DIR`:

- XML dump: `data/dblp.xml.gz`
- DTD file: `data/dblp.dtd`
- SQLite database: `data/dblp.sqlite`

## Running the MCP server

The server uses MCP stdio transport and is intended to be launched by an MCP client such as LM Studio.

`DBLP_MCP_DATA_DIR` should be set explicitly for published deployments. By default the server now refuses to start unless the data dir is configured, unless you pass `--allow-implicit-data-dir` for local-only fallback behavior.

```bash
python app.py
```

By default, the server starts in unprivileged mode and hides maintenance tools that can download raw DBLP data or rebuild the SQLite database. To expose those tools, launch it with:

```bash
python app.py --privileged
```

When run without a connected MCP client, the process exits immediately because stdio closes.

### Example LM Studio MCP configuration

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

## MCP tools

The following two tools are only exposed when the server is launched with `--privileged`.

### `download_dblp_dump`
Download the DBLP XML dump or DTD into local storage.

Parameters:
- `destination`: local output path
- `source_url`: DBLP XML-area URL, defaults to `https://dblp.org/xml/dblp.xml.gz`
- `replace`: if `false`, reuse an existing local file instead of downloading again

Returns:
- source URL
- destination path (always constrained to `DBLP_MCP_DATA_DIR`)
- file size
- SHA-256 digest
- timestamp
- whether the file came from cache

### `build_dblp_sqlite`
Stream the DBLP XML dump into a searchable SQLite database.

Parameters:
- `xml_path`: path to `.xml` or `.xml.gz`
- `database_path`: target SQLite file
- `replace`: rebuild the SQLite file atomically
- `batch_size`: commit frequency during import

Returns:
- source and database paths
- whether replace mode was used
- import statistics for publications, contributors, identifiers, venue links, and extra fields

Notes:
- the importer processes the XML incrementally with `iterparse`
- the importer always builds a fresh database and swaps it into place on success
- incremental append imports are intentionally not supported

### `search_publications`
Search imported publications using structured term groups over the SQLite FTS index.

Parameters:
- `term_groups`: list of OR-groups; the outer list means AND between groups
- `database_path`: SQLite file to search, constrained to `DBLP_MCP_DATA_DIR`
- `limit`: maximum number of results, from 1 to 1000
- `year_from`, `year_to`: optional year filters
- `record_types`: optional DBLP record type filter list
- `contributor`: optional normalized contributor substring filter
- `venue`: optional normalized venue substring filter

Returns:
- the normalized `term_groups`
- result count
- compact publication summaries by default
- optional contributor and venue lists when explicitly requested

### `get_publication`
Fetch one publication by canonical DBLP key.

Parameters:
- `dblp_key`: DBLP record key such as `conf/icse/GropengiesserDB25`
- `database_path`: SQLite file to inspect, constrained to `DBLP_MCP_DATA_DIR`

Returns:
- bibliographic core fields
- contributors
- venues
- full `abstract`, if one has already been fetched and cached
- optional identifiers, extra sparse fields, and fulltext metadata when explicitly requested

### `fetch_publication_abstract`
Fetch an abstract for an imported publication and cache it in SQLite.

Parameters:
- `dblp_key`: DBLP key of an imported publication
- `database_path`: SQLite file to update
- `refresh`: if `true`, bypass the cached abstract and try the providers again

Behavior:
- resolves the publication from local SQLite
- derives provider lookup identifiers from stored DBLP identifiers and fields
- tries source-specific providers in order
- stores successful abstract fetches in `publication_abstracts`
- writes success/failure/unsupported entries to `abstract_fetch_logs`

Result statuses:
- `cached`: a stored abstract was returned without network access
- `fetched`: a provider returned a new abstract and it was stored
- `unsupported`: no supported provider could be derived from the publication metadata
- `not_found`: supported providers ran but did not produce an abstract

Current providers:
- `openalex`: DOI-based lookup through the public OpenAlex API
- `arxiv`: arXiv lookup through the public arXiv API

Current full-text providers:
- `arxiv_pdf`: direct arXiv PDF lookup
- `ieee_pdf`: IEEE DOI resolution followed by IEEE stamp PDF retrieval
- `acm_pdf`: ACM direct DOI-to-PDF pattern
- `openalex_pdf`: OpenAlex-discovered open-access PDF URLs

### `fetch_publication_abstracts`
Fetch abstracts for a whole list of imported publications.

Parameters:
- `dblp_keys`: list of DBLP keys
- `database_path`: SQLite file to update
- `refresh`: if `true`, bypass cached abstracts for every requested key

Returns:
- a `summary` object with counts for `fetched`, `cached`, `unsupported`, `not_found`, `missing`, and `error`
- a `results` list with one structured result per requested key

This tool is intended for batch use cases where partial success is acceptable. Missing or unsupported records do not stop the rest of the batch.

### `fetch_publication_fulltext`
Fetch a legal full-text PDF and extracted text for one imported publication.

Parameters:
- `dblp_key`: DBLP key of an imported publication
- `database_path`: SQLite file to update
- `refresh`: if `true`, bypass the cached fulltext and retry the providers

Returns:
- provider and source metadata
- local cached PDF path relative to `DBLP_MCP_DATA_DIR`
- SHA-256, size, and page count
- a token-efficient `excerpt` and `text_length` by default
- optional full extracted text when explicitly requested
- `image_status` plus `page_image_paths` (currently text-only / unsupported by default)

### `fetch_publication_fulltexts`
Fetch legal full-text PDFs and extracted text for a whole list of imported publications.

Parameters:
- `dblp_keys`: list of DBLP keys
- `database_path`: SQLite file to update
- `refresh`: if `true`, bypass cached fulltext entries for each requested key

Returns:
- a `summary` object with counts for `fetched`, `cached`, `unsupported`, `not_found`, `missing`, and `error`
- a `results` list with one structured result per requested key

### `get_recent_fetch_failures`
Inspect recent abstract/fulltext fetch failures for operator debugging.

Parameters:
- `database_path`: SQLite file to inspect, constrained to `DBLP_MCP_DATA_DIR`
- `category`: one of `all`, `abstract`, or `fulltext`
- `limit`: maximum rows to return, from 1 to 200

Returns failure log entries with category, provider, attempted URL, status, error code, and timestamp.

### `get_dblp_status`
Report the state of the SQLite database.

Parameters:
- `database_path`: SQLite file to inspect

Returns:
- whether the file exists
- database size in bytes
- counts for publications, contributors, cached abstracts, abstract fetch logs, cached fulltexts, and fulltext fetch logs
- the most recent import runs

## Helper CLI

A small helper CLI exists for local development:

```bash
python -m dblp_mcp.cli download --destination data/dblp.xml.gz
python -m dblp_mcp.cli import --xml-path data/dblp.xml.gz --database-path data/dblp.sqlite
python -m dblp_mcp.cli search --database-path data/dblp.sqlite --query "graph neural networks"
python -m dblp_mcp.cli get --database-path data/dblp.sqlite --dblp-key "conf/icse/GropengiesserDB25"
```

The abstract-fetching workflow is currently exposed through MCP, not through the helper CLI.

## Architecture overview

Core modules:

- `src/dblp_mcp/server.py`: MCP tool definitions and top-level server wiring
- `src/dblp_mcp/cli.py`: local helper CLI for download/import/search/get workflows
- `src/dblp_mcp/downloader.py`: DBLP XML/DTD download logic and file caching
- `src/dblp_mcp/importer.py`: streaming XML-to-SQLite importer
- `src/dblp_mcp/database.py`: SQLite connection settings, schema creation, and additive schema helpers
- `src/dblp_mcp/search.py`: publication search, publication lookup, and database status reporting
- `src/dblp_mcp/abstracts/`: modular abstract provider system and orchestration
- `src/dblp_mcp/fulltext/`: modular legal full-text provider system, cache, and extraction

### Abstract provider architecture

Abstract fetching is intentionally separate from DBLP XML import.

- `abstracts/base.py`: provider protocol plus shared lookup/result dataclasses
- `abstracts/registry.py`: ordered provider registry
- `abstracts/service.py`: publication resolution, provider selection, caching, and log writing
- `abstracts/providers/openalex.py`: DOI-backed abstract fetcher using OpenAlex
- `abstracts/providers/arxiv.py`: arXiv-backed abstract fetcher using the arXiv API

This keeps source-specific logic isolated so new providers can be added without changing the importer.

## Data model

The SQLite schema is normalized around imported DBLP metadata and post-import enrichments.

### Core bibliographic tables

- `publications`: one row per imported DBLP record
- `contributors`: normalized author/editor names
- `publication_contributors`: ordered author/editor links
- `venues`: normalized journal, conference, series, publisher, and school names
- `publication_venues`: publication-to-venue links with relation types and ordering
- `publication_identifiers`: DOI, URL, EE, ISBN, ISSN, and related stable identifiers
- `publication_fields`: sparse XML fields that do not justify dedicated columns
- `import_runs`: import provenance, counts, and status
- `publication_search`: FTS5 index built from titles, contributors, and venues

### Abstract and full-text enrichment tables

- `publication_abstracts`: cached abstract text plus provider, source URL, and fetch timestamp
- `abstract_fetch_logs`: one row per abstract fetch outcome, including unsupported sources and provider errors
- `publication_fulltexts`: cached full-text PDF metadata plus extracted text
- `fulltext_fetch_logs`: one row per full-text fetch outcome, including unsupported sources and provider errors

`publication_abstracts` stores the best known cached abstract for a publication. `abstract_fetch_logs` is intentionally append-only operational telemetry for developers who want to see where support is missing or broken.

## Example workflows

### Build the local DBLP database

```bash
python -m dblp_mcp.cli download --destination data/dblp.xml.gz
python -m dblp_mcp.cli import --xml-path data/dblp.xml.gz --database-path data/dblp.sqlite
python -m dblp_mcp.cli search --database-path data/dblp.sqlite --query "graph neural networks"
```

### Fetch and inspect an abstract through MCP

1. Call `fetch_publication_abstract(dblp_key="conf/icse/GropengiesserDB25")` or `fetch_publication_abstracts(...)`
2. Call `get_publication(dblp_key="conf/icse/GropengiesserDB25")`
3. Inspect the returned `abstract` object

### Monitor abstract support coverage

1. Call `get_dblp_status()`
2. Check `abstracts` and `abstract_fetch_logs`
3. Inspect `abstract_fetch_logs` directly in SQLite when you need provider-level debugging

## Current limitations

- abstract and full-text fetching are on-demand, not bulk background enrichment
- only OpenAlex and arXiv providers are implemented today
- no abstract/fulltext CLI command exists yet
- abstracts are cached in SQLite but not indexed in the current FTS table
- unsupported or blocked sources are logged for later provider implementation


## Publication files

This repository includes:
- `LICENSE` (MIT)
- `CHANGELOG.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- GitHub Actions CI in `.github/workflows/ci.yml`


Additional controls:
- `DBLP_MCP_ENABLE_ABSTRACT_NETWORK=0` disables abstract providers only
- `DBLP_MCP_ENABLE_FULLTEXT_NETWORK=0` disables fulltext providers only
- batch tools enforce configurable limits for abstract and fulltext requests

- `DBLP_MCP_PROVIDER_DELAY_MIN_SECONDS` / `DBLP_MCP_PROVIDER_DELAY_MAX_SECONDS` add a small randomized default delay before provider requests; provider-specific overrides use names like `DBLP_MCP_PROVIDER_DELAY_OPENALEX_MIN_SECONDS` and `DBLP_MCP_PROVIDER_DELAY_IEEE_PDF_MAX_SECONDS`
