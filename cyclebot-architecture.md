# CycleBot: Lambeth Cyclists AI Assistant

## Architecture Overview

A conversational AI interface that lets Lambeth Cyclists members query Notion databases (meeting agendas, action items, ward election data, and more) via natural language. Phase 1 is a Vercel-hosted web frontend; Phase 2 will add a WhatsApp bot as a second interface to the same backend.

```
┌─────────────────────┐
│   Vercel Frontend    │
│   (React/Next.js)    │
│                      │
│  ?key=abc123 in URL  │
│  Chat UI             │
├──────────┬──────────┤
           │ POST /api/chat
           ▼
┌─────────────────────┐
│   Vercel API Route   │
│   (Edge Function)    │
│                      │
│  - Validates API key │
│  - Proxies to        │
│    Anthropic API     │
│  - Attaches MCP      │
│    server URL        │
├──────────┬──────────┤
           │ Anthropic Messages API
           │ (with mcp_servers param)
           ▼
┌─────────────────────┐      ┌─────────────────────┐
│   Anthropic API      │─────▶│   MCP Server         │
│   (Claude Sonnet)    │◀─────│   (Railway)          │
│                      │      │                      │
│  Orchestrates tool   │      │  - FastMCP (Python)  │
│  calls based on      │      │  - SSE transport     │
│  user's question     │      │  - Notion API client │
└─────────────────────┘      │  - Read-only tools   │
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   Notion Databases   │
                              │                      │
                              │  - Meetings          │
                              │  - Actions/Tasks     │
                              │  - Wards/Elections   │
                              │  - Any other DBs     │
                              └─────────────────────┘
```

## Component Details

### 1. MCP Server (Railway)

**Tech**: Python 3.11+, `mcp[cli]` package, `notion-client`, `httpx`

**Deployment**: Separate Railway service from your existing daemon. Shares the same Notion API token (set as env var). Exposes an SSE endpoint.

**Tools to expose** (start with these, add more as needed):

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `search_all` | Full-text search across all Notion databases | `query: str` |
| `get_meeting_agenda` | Get agenda/minutes for a specific meeting | `date: str` (ISO or natural like "last Tuesday") |
| `list_meetings` | List recent meetings | `limit: int = 5` |
| `get_action_items` | Get action items, optionally filtered | `status: str = "all"`, `assignee: str = None` |
| `get_ward_data` | Get ward election analysis | `ward_name: str = None` (all wards if omitted) |
| `get_battleground_wards` | Get wards flagged as marginal/battleground | (no params) |
| `list_databases` | List all available Notion databases | (no params — useful for discovery) |

**Key design decisions**:
- **Read-only**: No tools that create or modify Notion data. This is a query interface.
- **Rich docstrings**: Each tool's docstring is what Claude sees to decide when to use it. Make them detailed and include example queries.
- **Return markdown**: Format Notion data as readable markdown in tool responses — Claude will synthesise it into natural answers.
- **Error handling**: Return clear error messages (e.g., "No meeting found for that date — here are the most recent meetings: ...") rather than tracebacks.

**Environment variables**:
- `NOTION_API_TOKEN` — your existing integration token
- `MCP_API_KEY` — a shared secret the Vercel backend sends in headers, so the MCP server isn't open to the world

### 2. Vercel Frontend

**Tech**: Next.js 14 (App Router), React, Tailwind CSS

**Auth**: API key passed as URL query parameter (`?key=abc123`). The key is validated server-side in the API route. If invalid, the chat UI shows "Invalid access link — ask a committee member for the correct URL." Keys are stored as a comma-separated env var (`VALID_API_KEYS=abc123,def456`) so you can issue multiple keys or rotate them without redeploying.

**Pages**:
- `/` — redirects to an info page or shows "access link required"
- `/?key=abc123` — the chat interface

**API route** (`/api/chat`):
- Receives: `{ messages: [...], key: "abc123" }`
- Validates key against `VALID_API_KEYS`
- Calls Anthropic Messages API with:
  - `model: "claude-sonnet-4-20250514"`
  - `system`: A prompt describing CycleBot's role (see below)
  - `messages`: The conversation history
  - `mcp_servers`: `[{ type: "url", url: RAILWAY_MCP_URL, name: "lambeth-cyclists" }]`
- Streams the response back to the frontend

**UI features** (keep it simple for v1):
- Chat message list with user/assistant bubbles
- Input box with send button
- "Powered by Lambeth Cyclists" footer
- Mobile-responsive (most members will use this on phones)
- Suggested starter questions: "What's the agenda for the next meeting?", "What are the battleground wards?", "Any open action items?"

**Environment variables** (Vercel):
- `ANTHROPIC_API_KEY` — your Anthropic API key
- `VALID_API_KEYS` — comma-separated list of valid access keys
- `MCP_SERVER_URL` — your Railway MCP server's SSE endpoint

### 3. System Prompt for CycleBot

```
You are CycleBot, the AI assistant for Lambeth Cyclists, a cycling
advocacy group in Lambeth, South London.

You help members find information from the group's records including
meeting agendas and minutes, action items, and ward-level election
analysis for the May 2026 Lambeth council elections.

Guidelines:
- Use the available tools to look up information before answering.
  Never guess or make up data.
- If a query is ambiguous, search broadly first, then narrow down.
- Keep answers concise and practical — members are busy people.
- For ward/election queries, always clarify which election cycle
  the data relates to.
- If you can't find something, say so honestly and suggest what
  the member might search for instead.
- You have read-only access. If someone asks you to update or
  create records, explain they'll need to do that in Notion directly.
- Be friendly but not corporate. This is a community cycling group,
  not a boardroom.
```

## Phase 2: WhatsApp Bot (Future)

When you're ready to add this, the architecture extends naturally:

```
┌──────────────┐     webhook     ┌──────────────┐
│   WhatsApp   │ ───────────────▶│  Railway      │
│   Cloud API  │ ◀───────────────│  Bot Service  │
└──────────────┘   send message  └──────┬───────┘
                                        │ same Anthropic API call
                                        │ same MCP server
                                        ▼
                                 (existing infrastructure)
```

The bot service is a new Railway service (or module) that:
- Receives webhooks from WhatsApp when @CycleBot is mentioned
- Extracts the message text
- Calls the Anthropic API with the same system prompt and MCP server
- Sends the response back to the group chat

Same brain, different mouth.

## Deployment Sequence

1. **Build and deploy MCP server** to Railway
2. **Test MCP server** locally using `mcp dev` CLI tool
3. **Build Vercel frontend** with chat UI and API route
4. **Deploy to Vercel**, set env vars
5. **Test end-to-end** with a few queries
6. **Generate API key links** and share with committee members
7. **Iterate on tools** — add more Notion queries based on what people actually ask

## Cost Estimate

- **Railway**: Already on Pro plan. MCP server is lightweight (idles most of the time). ~$0-2/month additional.
- **Anthropic API**: Claude Sonnet. Typical query = ~1K input tokens + tool calls + ~500 output tokens. At ~$3/M input, $15/M output, even 100 queries/day would be well under $5/month. Realistically this will be pennies.
- **Vercel**: Free tier is fine for this traffic level.
- **Notion API**: Free, you're already using it.

---

# Claude Code Prompt

Use this prompt to kick off the build in Claude Code. It assumes you're starting in a fresh project directory.

---

## Prompt: MCP Server

```
I want to build an MCP server for Lambeth Cyclists, a cycling advocacy
group. It should expose read-only tools that query our Notion databases
and return the results as markdown.

Tech stack:
- Python 3.11+
- mcp[cli] package (FastMCP)
- notion-client for Notion API
- SSE transport for remote access
- Deploy to Railway

The server should expose these tools:
1. search_all(query: str) - full-text search across all Notion databases
2. get_meeting_agenda(date: str) - get agenda/minutes for a meeting by date
3. list_meetings(limit: int = 5) - list recent meetings
4. get_action_items(status: str = "all", assignee: str = None) - query actions
5. get_ward_data(ward_name: str = None) - ward election analysis
6. get_battleground_wards() - wards flagged as marginal
7. list_databases() - list all available databases (for discovery)

Environment variables:
- NOTION_API_TOKEN: Notion integration token
- MCP_API_KEY: shared secret for auth (validate in middleware)
- PORT: server port (Railway sets this)

Important:
- All tools are READ-ONLY. No creating/updating Notion data.
- Tool docstrings should be detailed — they're what Claude reads to
  decide when to use each tool. Include example queries in docstrings.
- Return data as formatted markdown strings.
- Handle errors gracefully — return helpful messages, not tracebacks.
- Include a requirements.txt and a Procfile for Railway deployment.
- The Notion database IDs should be in a config dict at the top of
  the file (I'll fill them in). Structure it so adding new databases
  is easy.

Start by creating the project structure and the main server file.
I'll provide my Notion database IDs once the skeleton is ready.
```

## Prompt: Vercel Frontend

```
I want to build a chat frontend for CycleBot, the Lambeth Cyclists
AI assistant. It talks to an MCP server (already built and deployed
on Railway) via the Anthropic Messages API.

Tech stack:
- Next.js 14 (App Router)
- React + Tailwind CSS
- Vercel deployment
- Anthropic SDK for the API route

Architecture:
- The frontend is a simple chat interface
- Auth: API key in URL query param (?key=abc123)
- Keys validated server-side against VALID_API_KEYS env var
- API route /api/chat that:
  - Validates the key
  - Calls Anthropic Messages API with mcp_servers param pointing
    to our Railway MCP server
  - Streams the response back
  - Uses claude-sonnet-4-20250514

UI requirements:
- Clean, mobile-first chat interface (most users on phones)
- User/assistant message bubbles
- Suggested starter questions on empty state:
  "What's the agenda for the next meeting?"
  "What are the battleground wards?"
  "Any open action items?"
- "Powered by Lambeth Cyclists" footer
- Simple loading state while waiting for response
- Error handling for invalid key, API failures

System prompt for CycleBot (include in the API route):
"""
You are CycleBot, the AI assistant for Lambeth Cyclists, a cycling
advocacy group in Lambeth, South London. You help members find
information from the group's records including meeting agendas and
minutes, action items, and ward-level election analysis for the
May 2026 Lambeth council elections. Use the available tools to look
up information before answering. Never guess or make up data. Keep
answers concise. Be friendly but not corporate — this is a community
cycling group.
"""

Environment variables:
- ANTHROPIC_API_KEY
- VALID_API_KEYS (comma-separated)
- MCP_SERVER_URL (Railway SSE endpoint)

Please create the full project structure. Keep it minimal — no
unnecessary dependencies or over-engineering.
```

---

*Architecture doc for CycleBot v1. Charlie / Lambeth Cyclists. March 2026.*
