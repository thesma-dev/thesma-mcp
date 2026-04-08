# Architecture

## Overview

The Thesma MCP Server is a thin translation layer between AI assistants and the Thesma REST API. It implements the Model Context Protocol (MCP) to expose SEC EDGAR financial data as native tools that LLMs can call.

```
AI Assistant (Claude, Cursor, ChatGPT)
    |
    | MCP Protocol (STDIO or Streamable HTTP)
    v
Thesma MCP Server
    |
    | HTTP (httpx)
    v
Thesma REST API (api.thesma.dev)
    |
    v
SEC EDGAR Data (PostgreSQL)
```

## Components

### Server (`server.py`)
- FastMCP server instance with lifespan management
- Transport selection: STDIO (default, local) or Streamable HTTP (hosted on Railway)
- Per-request auth: `Authorization: Bearer <api-key>` header overrides the default key
- `get_client(ctx)` helper extracts auth from the HTTP request or falls back to the shared default client
- `/health` endpoint for Railway health checks
- API key required at startup for STDIO; optional for HTTP (per-request keys supported)

### API Client (`client.py`)
- Async httpx client wrapping the Thesma REST API
- Authentication via Bearer token
- Error translation (HTTP errors → human-readable MCP messages)
- 30s request timeout, no retries

### Ticker Resolver (`resolver.py`)
- Translates stock tickers (AAPL) to SEC CIKs (0000320193)
- In-memory cache for resolved mappings
- Case-insensitive lookup

### Formatters (`formatters.py`)
- Number formatting (currency, percent, shares) for LLM-friendly output
- Table formatting (aligned text, not markdown pipes)
- Source attribution and pagination summaries

### Tools (`tools/`)
- MCP tool definitions (added in MCP-03 through MCP-05)
- Each tool calls the API client, formats the response, returns structured text

## Data flow

1. LLM sends an MCP tool call (e.g., `get_financials(ticker="AAPL")`)
2. Tool function resolves ticker → CIK via resolver
3. Tool calls Thesma REST API via client
4. Tool formats JSON response into structured text via formatters
5. Formatted text returned to LLM via MCP protocol

## Key design decisions

- **No database** — all state comes from the Thesma API
- **No caching** (except ticker→CIK) — the API handles caching
- **Text output, not JSON** — LLMs reason better over formatted text
- **STDIO primary** — simplest integration for local AI assistants
- **Stateless HTTP** — Railway deployment uses `stateless_http=True` to avoid sticky sessions

## Deployment

The MCP server is deployed on Railway as a Streamable HTTP service.

- **Dockerfile**: Python 3.12-slim, installs the package in production mode, exposes port 8200
- **Transport**: Set via `THESMA_MCP_TRANSPORT=http` env var (not baked into the image)
- **Health check**: `GET /health` → `{"status": "ok"}`
- **Auth model**: Optional `Authorization: Bearer <api-key>` header per-request. If absent, falls back to `THESMA_API_KEY` env var (free-tier default). If neither is present, tool calls return an error.
- **Server-scoped TickerResolver**: CIK lookups are cached in memory across all requests, not per-user
