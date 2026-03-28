# Contributing

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
```

## Validation

```bash
python -m pytest
mypy src
python -m compileall src tests app.py
```

## Guidelines

- prefer small, focused changes
- keep network behavior explicit and legal-source only
- preserve data-dir sandboxing and privileged-mode boundaries
- add tests for changed MCP-visible behavior
