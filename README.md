# Thesma MCP Server

Give your AI assistant access to SEC, Census, BLS, and SBA data.

[![PyPI version](https://img.shields.io/pypi/v/thesma-mcp)](https://pypi.org/project/thesma-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/thesma-mcp)](https://pypi.org/project/thesma-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

## What it does

An [MCP](https://modelcontextprotocol.io/) server that wraps the [Thesma API](https://thesma.dev), giving AI assistants (Claude, Cursor, ChatGPT) native access to SEC EDGAR filings — US-GAAP 10-K and IFRS 20-F, covering every US-listed public company on NYSE and NASDAQ (~6,000 companies) — plus Bureau of Labor Statistics employment data, US Census Bureau demographics, and SBA 7(a) small business lending. Ask questions in plain English, get structured data back.

## Quick example

> "What was Apple's revenue last year?"

The AI calls `get_financials` and returns Apple's income statement with formatted line items.

> "What was Spotify's revenue last year?"

The AI calls `get_financials` for SPOT and returns Spotify's income statement in EUR with `taxonomy: ifrs-full` and `by_nature` presentation metadata.

> "Find high-margin S&P 500 companies where insiders are buying"

The AI calls `screen_companies` with margin filters and insider buying signals.

> "Which funds increased their position in NVDA last quarter?"

The AI calls `get_holding_changes` and shows quarter-over-quarter position changes.

> "What's the average wage for software developers in Texas?"

The AI calls `get_occupation_wages` with SOC code 15-1252 and state filter, returning median and percentile wage data.

> "What does Apple's labor market look like — hiring trends, local wages, compensation benchmarks?"

The AI calls `get_company` for AAPL, which automatically includes BLS labor market context alongside SEC company details.

> "Give me a full picture of Apple — profile, financials, ratios, insider trades, top holders, executive compensation, and board."

The AI calls `get_company('AAPL', include='financials,ratios,insider_trades,holders,compensation,board,labor_context,lending_context')` and returns a composed view in one call instead of eight tool invocations.

## Installation

```bash
pip install thesma-mcp
```

### Claude Desktop

Add to your config file (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "thesma": {
      "command": "uvx",
      "args": ["thesma-mcp"],
      "env": {
        "THESMA_API_KEY": "your-api-key"
      }
    }
  }
}
```

### Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "thesma": {
      "command": "uvx",
      "args": ["thesma-mcp"],
      "env": {
        "THESMA_API_KEY": "your-api-key"
      }
    }
  }
}
```

> **Using `pip install` instead of `uvx`?** If you've already installed `thesma-mcp` with pip, you can use `"command": "thesma-mcp"` directly (no `args` needed) instead of `uvx`.

Get your API key at [portal.thesma.dev](https://portal.thesma.dev) (free tier: 250 requests/day).

## Available tools

### Company Discovery

| Tool | Description |
|------|-------------|
| `search_companies` | Find US public companies by name, ticker, index tier, exchange, domicile, taxonomy, or currency |
| `get_company` | Get company details — CIK, SIC code, fiscal year end, index membership, exchange, domicile |

### Financial Statements

| Tool | Description |
|------|-------------|
| `get_financials` | Get income statement, balance sheet, or cash flow from SEC filings — US-GAAP 10-K and IFRS 20-F, returned in native currency |
| `get_financial_metric` | Get a single financial metric over time for trend analysis; per-point currency honors presentation-currency transitions |

### Financial Ratios

| Tool | Description |
|------|-------------|
| `get_ratios` | Get computed financial ratios — margins, returns, leverage, growth |
| `get_ratio_history` | Get a single ratio over time for trend analysis |

### Screening

| Tool | Description |
|------|-------------|
| `screen_companies` | Find companies matching financial criteria — profitability, growth, leverage, index tier, SIC, exchange, domicile, taxonomy, currency, insider/institutional signals, labor market, SBA lending (county + industry) |

### Corporate Events

| Tool | Description |
|------|-------------|
| `get_events` | Get 8-K corporate events — earnings, M&A, leadership changes, material agreements |

### Insider Trading

| Tool | Description |
|------|-------------|
| `get_insider_trades` | Get Form 4 insider transactions — purchases, sales, grants, option exercises |

### Institutional Holdings

| Tool | Description |
|------|-------------|
| `search_funds` | Find institutional investment managers (hedge funds, mutual funds) by name |
| `get_institutional_holders` | Get which funds hold a company's stock with shares and market values |
| `get_fund_holdings` | Get a fund's portfolio — what stocks it owns |
| `get_holding_changes` | Get quarter-over-quarter changes in institutional positions |

### Compensation & Governance

| Tool | Description |
|------|-------------|
| `get_executive_compensation` | Get executive pay — salary, bonus, stock awards, total, CEO pay ratio |
| `get_board_members` | Get board of directors — age, tenure, independence, committee memberships |

### Filings

| Tool | Description |
|------|-------------|
| `search_filings` | Search SEC filings by company, type (10-K, 10-Q, 8-K, etc.), and date range |

### Filing Section Search

| Tool | Description |
|------|-------------|
| `search_filing_sections` | Semantic search of SEC filing section content (Risk Factors, MD&A, etc.) by natural-language query — optionally scoped by ticker, filing type, section type, year, or similarity threshold |

### Webhooks

| Tool | Description |
|------|-------------|
| `list_webhook_event_types` | List the 5 event types you can subscribe to |
| `list_webhooks` | List your webhook subscriptions |
| `create_webhook` | Create a new subscription (returns one-time HMAC secret) |
| `get_webhook` | Get details for one subscription |
| `update_webhook` | Modify url / events / filing_types / is_active / description |
| `delete_webhook` | Delete a subscription |
| `list_webhook_deliveries` | Recent delivery attempts (debugging) |
| `rotate_webhook_secret` | Generate a new HMAC secret (invalidates old) |
| `send_webhook_test` | Enqueue a synthetic test delivery |
| `replay_webhook_delivery` | Re-queue a past delivery (within 7-day window) |

### Industry Lookup

| Tool | Description |
|------|-------------|
| `search_industries` | Find BLS industries by name or NAICS level |
| `get_industry_detail` | Get industry details — child industries, data availability across CES/QCEW/OEWS |

### Industry Employment (CES)

| Tool | Description |
|------|-------------|
| `get_industry_employment` | Get employment, earnings, and hours data for an industry by NAICS code |

### County Employment & Wages (QCEW)

| Tool | Description |
|------|-------------|
| `get_county_employment` | Get quarterly employment data for a US county by FIPS code |
| `get_county_wages` | Get county wage snapshot with location quotients vs. national average |

### Occupation Wages (OEWS)

| Tool | Description |
|------|-------------|
| `search_occupations` | Find BLS occupations by name or SOC group |
| `get_occupation_wages` | Get occupation wage data — mean, median, and percentile distribution |

### Labor Market Turnover (JOLTS)

| Tool | Description |
|------|-------------|
| `get_industry_turnover` | Get job openings, hires, quits, and layoffs for an industry |
| `get_state_turnover` | Get state-level labor market turnover (total nonfarm) |
| `get_regional_turnover` | Get turnover data for a Census region (Northeast, South, Midwest, West) |

### Local Area Unemployment (LAUS)

| Tool | Description |
|------|-------------|
| `get_county_unemployment` | Get monthly unemployment rate, labor force, and employment for a US county (never seasonally adjusted) |
| `compare_county_unemployment` | Compare unemployment metrics across up to 10 counties in a single period |
| `get_state_unemployment` | Get monthly state unemployment with labor force participation rate and employment-population ratio (SA or NSA) |
| `compare_state_unemployment` | Compare unemployment metrics across up to 10 states in a single period |

### SBA 7(a) Lending

| Tool | Description |
|------|-------------|
| `get_county_lending` | Get quarterly SBA 7(a) loan aggregates for a US county (loan count, total amount, charge-off rate) |
| `get_state_lending` | Get quarterly SBA 7(a) loan aggregates for a US state |
| `get_industry_lending` | Get quarterly SBA 7(a) loan aggregates for a NAICS industry, optionally scoped to state or county |
| `get_lenders` | List SBA 7(a) lenders ranked by loan count, total amount, or average loan size |
| `get_lender` | Get details and quarterly history for a single SBA lender by lender_id |
| `get_lending_characteristics` | Get loan size, term length, interest rate, sub-programme, and business-type distributions for a quarter |
| `get_lending_outcomes` | Get vintage cohort charge-off rates and maturity status |
| `explore_sba_metrics` | Browse available SBA metrics by category or keyword |
| `get_sba_metric_detail` | Get full definition, unit, cadence, and data availability for a single SBA metric |

### BLS Discovery

| Tool | Description |
|------|-------------|
| `explore_bls_metrics` | Browse available BLS metrics by category, source, or keyword |

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `THESMA_API_KEY` | Yes | API key from [portal.thesma.dev](https://portal.thesma.dev) |
| `THESMA_API_URL` | No | Override API base URL (default: `https://api.thesma.dev`) |

## Data coverage

- ~6,000 US-listed public companies on NYSE and NASDAQ — US-GAAP filers plus IFRS 20-F filers (Spotify, Nu Holdings, ASML, and other US-listed IFRS reporters). Native-currency reporting; no USD normalization.
- **SEC EDGAR:** financial statements (2009-present), insider trades, institutional holdings, executive compensation, board data, corporate events, filings
- **Bureau of Labor Statistics:** industry employment (CES), county wages (QCEW), occupation wages (OEWS), job openings and turnover (JOLTS), local unemployment (LAUS)
- **Small Business Administration:** 7(a) loan program data — quarterly lending aggregates by county/state/industry, lender rankings, loan characteristics (size, term, rate, sub-programme), vintage cohort charge-off outcomes
- **Labor & lending market enrichment:** `get_company` automatically includes BLS labor context and SBA 7(a) lending context; `screen_companies` supports labor market and SBA lending filters
- **Known gaps:** IFRS bank filings (Nu Holdings, HSBC, Deutsche Bank, etc.) — the core banking-statement extensions (`net_interest_income`, etc.) are US-GAAP-specific today; IFRS banking fields land in a future release.
- All data sourced from US federal public-domain sources: SEC EDGAR, US Census Bureau, Bureau of Labor Statistics, Small Business Administration

## Links

- [Thesma API docs](https://api.thesma.dev/docs)
- [Developer portal](https://portal.thesma.dev)
- [Pricing](https://thesma.dev/pricing)
- [Security & data rights](https://thesma.dev/security)
- [Website](https://thesma.dev)

## License

MIT
