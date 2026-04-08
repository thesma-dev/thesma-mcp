# CLAUDE.md

## MANDATORY: Use td for Task Management

You must run td usage --new-session at conversation start (or after /clear) to see current work.
Use td usage -q for subsequent reads.

## Project

Thesma MCP Server — MCP server that gives AI assistants native access to Thesma's SEC EDGAR data.

The MCP server is a thin translation layer: it receives MCP tool calls from AI assistants (Claude, Cursor, ChatGPT), translates them into Thesma REST API requests, and formats the responses as structured text for LLM consumption. It has no database, no data processing, and no state beyond an in-memory ticker cache.

## Stack

- Python 3.12+, MCP Python SDK (FastMCP), httpx
- Ruff for linting/formatting, mypy strict mode
- pytest + pytest-asyncio for testing, respx for HTTP mocking

## Key directories

| Directory | Purpose |
|---|---|
| `src/thesma_mcp/` | Server code (client, resolver, formatters, server) |
| `src/thesma_mcp/tools/` | MCP tool definitions |
| `tests/` | pytest tests |

## Linked repos

- **Docs repo:** `/Users/willcodejavaforfood/Documents/gov-data-docs` — product specifications and implementation prompts
- **API repo:** `/Users/willcodejavaforfood/Documents/GitHub/govdata-api` — Thesma REST API that this MCP server wraps

## Development

### Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # then fill in THESMA_API_KEY
```

### Testing

- `make test` — run all tests
- `make check` — lint + type-check + test (all quality gates)

## Port

- HTTP transport: **8200** (default, overridden by `PORT` env var on Railway)

## Deployment

The MCP server is deployed on Railway via Streamable HTTP.

- **Dockerfile**: Does NOT set `THESMA_MCP_TRANSPORT` — must be passed at runtime
- **Railway env vars**: `THESMA_MCP_TRANSPORT=http`, `THESMA_API_KEY` (optional — enables free-tier fallback), `PORT` (set by Railway)
- **Health check**: `GET /health` on the Railway domain

## Conventions

- Ruff for linting and formatting (line length 120)
- mypy strict mode
- All imports start with `thesma_mcp.`
- `src/` layout with `pyproject.toml` (no setup.py)

## Pre-handoff checklist

Before running `td handoff`, you MUST pass all three checks:

```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
```

Fix all errors yourself — do not hand off code with lint, formatting, or type errors.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR to main:

1. **lint** — `ruff check` + `ruff format --check`
2. **type-check** — `mypy src/`
3. **test** — `pytest` (no database needed, all API calls are mocked)

## Docs repo

The product specification lives at `/Users/willcodejavaforfood/Documents/gov-data-docs/`. Implementation prompts are written there and fed to Claude Code here.
