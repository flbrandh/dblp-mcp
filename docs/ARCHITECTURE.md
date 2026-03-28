# Architecture

## Overview

The DBLP MCP server is organized as a small layered Python application:

1. **Transport layer**: MCP tool definitions in `src/dblp_mcp/server.py`
2. **Application layer**: import, search, status, and abstract-fetch orchestration
3. **Persistence layer**: SQLite schema and query helpers
4. **Integration layer**: DBLP file download and abstract provider calls

The design goal is to keep the large DBLP XML import path separate from the smaller post-import enrichment path.

## Main components

### `server.py`
Defines the MCP tool surface and delegates all real work to library functions. The MCP layer is intentionally thin so the same functionality can be tested outside an MCP runtime.

### `downloader.py`
Handles DBLP XML-area downloads only.

Responsibilities:
- validate DBLP download URLs
- reuse existing files by default
- hash cached files
- download large artifacts incrementally
- clean up partial files on error

This module is intentionally not used for generic web crawling.

### `importer.py`
Streams DBLP XML into SQLite.

Responsibilities:
- parse `.xml` and `.xml.gz`
- load DBLP DTD entities needed for real-world DBLP parsing
- map XML records to normalized Python objects
- write the relational schema in batches
- rebuild the full-text search index after import

Important constraint:
- import builds a fresh SQLite file and swaps it into place on success
- append/incremental import is intentionally unsupported

### `database.py`
Owns SQLite connection settings and schema creation.

Responsibilities:
- connection pragmas
- full schema creation for new databases
- additive abstract-schema creation for existing databases
- FTS rebuild logic

### `search.py`
Contains read-side queries only.

Responsibilities:
- full-text search over imported publications
- detailed publication lookup with related records
- database status reporting

### `abstracts/`
Contains the post-import abstract enrichment system.

### `fulltext/`
Contains the post-import legal full-text enrichment system.

#### `abstracts/base.py`
Shared dataclasses and provider protocol.

#### `abstracts/registry.py`
Ordered provider registration. This is the central place where provider precedence is defined.

#### `abstracts/service.py`
Main orchestration entry point for abstract fetching.

Responsibilities:
- resolve a publication by `dblp_key`
- derive lookup identifiers such as DOI and arXiv ID
- select compatible providers
- reuse cached abstracts unless refresh is requested
- persist successful abstracts
- record operational logs for unsupported or failed attempts

#### `abstracts/providers/openalex.py`
Fetches DOI-backed abstracts from the public OpenAlex API.

#### `abstracts/providers/arxiv.py`
Fetches arXiv-backed abstracts from the public arXiv API.

#### `fulltext/providers/ieee.py`
Resolves IEEE DOIs to IEEE Xplore document ids and uses the public stamp PDF endpoint.

#### `fulltext/providers/acm.py`
Builds ACM Digital Library DOI-based PDF candidates without browser automation.

#### `fulltext/providers/openalex.py`
Uses OpenAlex OA metadata as a legal full-text fallback.

#### `fulltext/service.py`
Main orchestration entry point for legal full-text fetching.

Responsibilities:
- resolve a publication by `dblp_key`
- derive DOI/arXiv lookup identifiers
- select legal full-text providers
- cache PDFs on disk and extracted text in SQLite
- reject presentation-like PDFs using page geometry heuristics
- record operational logs

## Data flow

### Import flow

1. `download_dblp_dump` downloads or reuses `dblp.xml.gz`
2. `build_dblp_sqlite` constructs a `DblpImporter`
3. `DblpImporter.import_file()` streams XML into SQLite tables
4. `rebuild_search_index()` creates the FTS5 search view
5. the completed temporary DB replaces the target DB atomically

### Search flow

1. `search_publications` runs an FTS query plus optional filters
2. matching publication ids are expanded into publication summaries
3. contributors and venues are looked up from normalized link tables

### Abstract flow

1. `fetch_publication_abstract` resolves a local publication by `dblp_key`
2. cached abstract is returned immediately unless `refresh=True`
3. DOI/arXiv lookup identifiers are extracted from imported metadata
4. the provider registry selects matching providers
5. the first successful provider response is normalized and stored
6. all outcomes are logged in `abstract_fetch_logs`

### Full-text flow

1. `fetch_publication_fulltext` resolves a local publication by `dblp_key`
2. cached fulltext is returned immediately unless `refresh=True`
3. DOI/arXiv lookup identifiers are extracted from imported metadata
4. the provider registry selects matching legal providers
5. a legal PDF candidate is downloaded to local storage
6. text is extracted and page geometry is checked to avoid slide decks
7. metadata/text are stored and all outcomes are logged in `fulltext_fetch_logs`

## Schema design

### Core imported DBLP tables

- `publications`
- `contributors`
- `publication_contributors`
- `venues`
- `publication_venues`
- `publication_identifiers`
- `publication_fields`
- `import_runs`
- `publication_search`

This split keeps the import normalized enough for search and joins while still preserving sparse DBLP metadata.

### Abstract enrichment tables

- `publication_abstracts`
- `abstract_fetch_logs`
- `publication_fulltexts`
- `fulltext_fetch_logs`

`publication_abstracts` stores the current cached abstract for a publication. `abstract_fetch_logs` is operational telemetry and intentionally keeps a history of fetch attempts.

## Extension points

### Add a new abstract provider

1. create a new provider module under `src/dblp_mcp/abstracts/providers/`
2. implement the provider protocol from `abstracts/base.py`
3. add the provider to `_PROVIDERS` in `abstracts/registry.py`
4. add tests using mocked network responses
5. document the new provider in `README.md`

### Add a new MCP tool

1. add the core logic to a library module first
2. keep MCP tool functions in `server.py` as thin wrappers
3. return structured dict payloads suitable for LM Studio and other MCP clients
4. add tests at the library level whenever possible

## Operational considerations

- SQLite is the single local source of truth after import
- the XML dump is needed only for rebuilds/reimports
- abstract fetching is on-demand and cached
- provider failures should be diagnosed through `abstract_fetch_logs`
- the MCP server uses stdio and is intended to be launched by the client, not as a long-running standalone daemon
