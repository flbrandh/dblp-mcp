> **Disclaimer:** This project was written entirely by AI-assisted coding agents. Human review is strongly recommended before production use.

# Security Policy

## Supported versions

This project currently supports the latest `0.1.x` release line.

## Trust model

- The MCP server is intended for trusted local or operator-controlled environments.
- Unprivileged mode is the default and hides maintenance tools.
- Privileged mode should only be used by trusted operators.
- All tool-facing file paths are sandboxed to `DBLP_MCP_DATA_DIR`.
- Network-backed enrichment can be disabled with `DBLP_MCP_ENABLE_NETWORK=0`.

## Reporting a vulnerability

Please report vulnerabilities privately to the repository maintainer before public disclosure.
Include:
- affected version/commit
- reproduction steps
- expected impact
- suggested mitigations if known

## Security-sensitive settings

- `DBLP_MCP_DATA_DIR`
- `DBLP_MCP_ENABLE_NETWORK`
- `DBLP_MCP_ABSTRACT_TIMEOUT_SECONDS`
- `DBLP_MCP_FULLTEXT_TIMEOUT_SECONDS`
- `DBLP_MCP_DOWNLOAD_TIMEOUT_SECONDS`
- `DBLP_MCP_MAX_FULLTEXT_PDF_BYTES`
