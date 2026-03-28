# AGENTS.md - Python/Flask Repository Guide

## Purpose

This file guides coding agents working in this repository.
Prefer small, safe changes that match existing patterns.
Use the specialized OpenCode agent team for substantial work.

## Build / Lint / Test Commands

### Setup

```bash
pip install -r requirements-dev.txt
pip install -r requirements-prod.txt
```

### Run Application

```bash
python app.py
gunicorn --bind 0.0.0.0:8000 app:app
```

### Tests

```bash
pytest
python -m pytest tests/test_app.py
python -m pytest tests/test_app.py::test_index
pytest -v
pytest --cov=app
```

### Lint / Format

```bash
black src/
black --check src/
pylint src/
```

## Code Style Guidelines

### Imports

- Order imports as: standard library, third-party, local.
- Keep imports at module top unless a local import is required.
- Prefer explicit imports over wildcard imports.

### Formatting

- Follow Black formatting.
- Use 4-space indentation.
- Keep lines within 88 characters when practical.
- Prefer small functions and straightforward control flow.

### Types

- Add type hints for new or modified functions.
- Use `typing` forms such as `Optional`, `Dict`, `List`, `Union`.
- Keep return types explicit for public helpers and services.

### Naming

- Use `snake_case` for files, functions, variables, and methods.
- Use `PascalCase` for classes.
- Use `UPPER_CASE` for constants.
- Prefix private helpers with `_`.

### Flask / Project Structure

- Keep `app.py` as the main entry point.
- Put route handlers in `src/routes/`.
- Put business logic in `src/services/`.
- Put models and schemas in `src/models/`.
- Put shared helpers in `src/utils/`.
- Keep validation and response shaping near the boundary.

### Error Handling

- Never use bare `except`.
- Raise specific exceptions with actionable messages.
- Return consistent HTTP status codes and JSON error shapes.
- Do not leak stack traces, secrets, or internal details.

### Logging

- Use `logging.getLogger(__name__)`.
- Log enough context to debug failures.
- Never log passwords, tokens, API keys, session values, or personal data.

### Configuration / Security

- Read configuration from environment variables.
- Do not hardcode secrets or deployment-specific values.
- Validate all user input at the boundary.
- Use SQLAlchemy ORM or parameterized queries only.
- Review auth, permissions, file access, redirects, and external requests carefully.
- Default to least privilege for config and runtime behavior.

## Testing Guidelines

- Use `pytest` and keep tests in `tests/`.
- Cover happy path, validation failures, and edge cases.
- Prefer focused unit tests plus targeted endpoint tests.
- Use fixtures for setup and isolation.
- Mock external systems where appropriate.
- Aim for at least 80% coverage on meaningful application code.

## Git / Change Discipline

- Make small, focused changes.
- Do not rewrite unrelated files.
- Follow conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
- Never commit secrets, credentials, or `.env` contents.

## OpenCode Agent Team

Custom agent files live in `.opencode/agents/`:

- `project-manager.md`
- `requirements-engineer.md`
- `architect.md`
- `api-designer.md`
- `developer.md`
- `tester.md`
- `code-reviewer.md`
- `security-auditor.md`
- `docs-specialist.md`
- `devops-engineer.md`
- `dependency-auditor.md`
- `release-manager.md`
- `team.md`

### Required Delivery Process

1. `@project-manager` coordinates the task and enforces gates.
2. `@requirements-engineer` defines scope, assumptions, and acceptance criteria.
3. `@explore` inspects the existing codebase and patterns.
4. `@architect` reviews structure, module boundaries, and design tradeoffs.
5. `@api-designer` reviews route, schema, and contract changes.
6. `@developer` implements the smallest correct change.
7. `@tester` adds or updates tests and maps them to behavior changes.
8. `@security-auditor` reviews risks for inputs, auth, secrets, and config.
9. `@dependency-auditor` reviews package and supply-chain changes when relevant.
10. `@code-reviewer` performs final quality review.
11. `@docs-specialist` updates setup, API, or workflow docs when needed.
12. `@devops-engineer` reviews runtime, CI, and deployment concerns when relevant.
13. `@release-manager` gives the final ship / no-ship recommendation.

### Merge Gates

- Requirements are clear and testable.
- Changed behavior is covered by tests.
- `black --check src/` passes.
- `pylint src/` passes with acceptable quality.
- Security review finds no unresolved critical issues.
- Dependency review is complete when packages or tooling changed.
- Documentation is updated when behavior or workflow changed.
- Release notes, rollout notes, and rollback considerations are captured for risky changes.

### Agent Standards

- All specialist agents should use explicit handoff templates.
- Review and security agents should classify findings by severity.
- Editing agents should follow a minimal-change bias.
- Agents should state when a task is out of scope and hand it to the correct specialist.

### Persistent Agent Notes

- Every custom agent owns a durable note folder at `./agent-notes/<agent>/`.
- Use notes to retain learning beyond a single task: architecture decisions, user stories, review checklists, testing heuristics, release rules, and recurring pitfalls.
- Do not store ephemeral scratch work, temporary debugging output, or task-local chatter.
- Each note entry should use a stable markdown structure with `Title`, `Date`, a scoped context field, the durable observation or rule, supporting evidence, actionable guidance, and `Status`.
- Agents should update their notes when they discover a reusable lesson, recurring defect pattern, or lasting repository convention.

## Additional Rule Sources

- Cursor rules: `.cursor/rules/python-flask-dev.md`
- No `.cursorrules` file was present when this guide was written.
- No `.github/copilot-instructions.md` file was present when this guide was written.
