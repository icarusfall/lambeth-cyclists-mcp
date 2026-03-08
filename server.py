"""Lambeth Cyclists MCP Server

Read-only tools for querying Notion databases via MCP.
Deployed on Railway, consumed by the Anthropic API.

Uses the Notion data_sources API (notion-client v3).
"""

import os
import sys
import logging
from mcp.server.fastmcp import FastMCP
from notion_client import Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — database IDs and their data source IDs
# To add a new database: retrieve it, grab the data_sources[0].id, add here.
# ---------------------------------------------------------------------------
DATABASES = {
    "meetings": {
        "db_id": "2e42d7a24378803fb811d2f6ed029137",
        "ds_id": "2e42d7a2-4378-80b4-bba9-000bfdd54b95",
        "label": "Meetings",
    },
    "wards": {
        "db_id": "3002d7a24378814ba99cf54d0664ab1c",
        "ds_id": "3002d7a2-4378-81f4-85f6-000b48c100c1",
        "label": "Wards",
    },
    "councillors": {
        "db_id": "3002d7a24378814388effd4357a003d3",
        "ds_id": "3002d7a2-4378-81d8-8f0e-000be42cf371",
        "label": "Councillors & Candidates",
    },
    "items": {
        "db_id": "2e32d7a2437880298c81f1af94c441a0",
        "ds_id": "2e32d7a2-4378-80c7-ab8b-000b859cd636",
        "label": "Items",
    },
    "projects": {
        "db_id": "2e42d7a2437880d686e8ff554556b0c1",
        "ds_id": "2e42d7a2-4378-80f3-bafd-000baf137869",
        "label": "Projects",
    },
}

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
notion = Client(auth=os.environ["NOTION_API_TOKEN"])
mcp = FastMCP("lambeth-cyclists")

# ---------------------------------------------------------------------------
# Notion helpers
# ---------------------------------------------------------------------------


def rich_text_to_str(rt_array):
    """Convert a Notion rich-text array to a plain string."""
    return "".join(seg.get("plain_text", "") for seg in rt_array)


def extract_property_value(prop):
    """Return a human-readable value from a Notion property object."""
    t = prop["type"]

    if t == "title":
        return rich_text_to_str(prop["title"])
    if t == "rich_text":
        return rich_text_to_str(prop["rich_text"])
    if t == "number":
        return str(prop["number"]) if prop["number"] is not None else None
    if t == "select":
        return prop["select"]["name"] if prop["select"] else None
    if t == "multi_select":
        return ", ".join(s["name"] for s in prop["multi_select"]) or None
    if t == "date":
        d = prop["date"]
        if not d:
            return None
        start = d.get("start", "")
        end = d.get("end")
        return f"{start} to {end}" if end else start
    if t == "checkbox":
        return "Yes" if prop["checkbox"] else "No"
    if t == "url":
        return prop["url"]
    if t == "email":
        return prop["email"]
    if t == "phone_number":
        return prop["phone_number"]
    if t == "people":
        names = [p.get("name", "Unknown") for p in prop["people"]]
        return ", ".join(names) if names else None
    if t == "relation":
        n = len(prop["relation"])
        return f"({n} linked)" if n else None
    if t == "formula":
        f = prop["formula"]
        return str(f.get(f["type"]))
    if t == "rollup":
        r = prop["rollup"]
        rtype = r["type"]
        if rtype == "array":
            items = r.get("array", [])
            if items:
                return ", ".join(
                    str(extract_property_value(i)) for i in items if i
                )
            return None
        return str(r.get(rtype))
    if t == "status":
        return prop["status"]["name"] if prop["status"] else None
    if t == "created_time":
        return prop["created_time"]
    if t == "last_edited_time":
        return prop["last_edited_time"]
    if t == "created_by":
        return prop["created_by"].get("name", "Unknown")
    if t == "last_edited_by":
        return prop["last_edited_by"].get("name", "Unknown")
    if t == "unique_id":
        uid = prop["unique_id"]
        prefix = uid.get("prefix", "")
        number = uid.get("number", "")
        return f"{prefix}-{number}" if prefix else str(number)
    return f"[{t}]"


def get_page_title(page):
    """Extract the title property from a Notion page."""
    for prop in page.get("properties", {}).values():
        if prop["type"] == "title":
            return rich_text_to_str(prop["title"]) or "Untitled"
    return "Untitled"


def format_properties(page):
    """Format all properties of a page as markdown."""
    lines = []
    title = get_page_title(page)
    lines.append(f"### {title}")

    for name, prop in sorted(page.get("properties", {}).items()):
        if prop["type"] == "title":
            continue
        value = extract_property_value(prop)
        if value is not None and str(value).strip():
            lines.append(f"- **{name}**: {value}")

    url = page.get("url")
    if url:
        lines.append(f"- [Open in Notion]({url})")

    # Include page ID for drill-down with get_page_detail
    lines.append(f"- *Page ID*: `{page['id']}`")

    return "\n".join(lines)


def get_page_content(page_id):
    """Fetch all blocks from a page and return as markdown."""
    all_blocks = []
    cursor = None

    while True:
        kwargs = {"block_id": page_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        try:
            response = notion.blocks.children.list(**kwargs)
        except Exception as e:
            logger.error("Error fetching blocks for %s: %s", page_id, e)
            return ""
        all_blocks.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return blocks_to_markdown(all_blocks)


def blocks_to_markdown(blocks):
    """Convert Notion blocks to markdown text."""
    lines = []
    for block in blocks:
        bt = block["type"]
        if bt == "paragraph":
            text = rich_text_to_str(block["paragraph"]["rich_text"])
            if text:
                lines.append(text)
        elif bt == "heading_1":
            lines.append(f"# {rich_text_to_str(block['heading_1']['rich_text'])}")
        elif bt == "heading_2":
            lines.append(f"## {rich_text_to_str(block['heading_2']['rich_text'])}")
        elif bt == "heading_3":
            lines.append(f"### {rich_text_to_str(block['heading_3']['rich_text'])}")
        elif bt == "bulleted_list_item":
            lines.append(
                f"- {rich_text_to_str(block['bulleted_list_item']['rich_text'])}"
            )
        elif bt == "numbered_list_item":
            lines.append(
                f"1. {rich_text_to_str(block['numbered_list_item']['rich_text'])}"
            )
        elif bt == "to_do":
            text = rich_text_to_str(block["to_do"]["rich_text"])
            checked = "x" if block["to_do"].get("checked") else " "
            lines.append(f"- [{checked}] {text}")
        elif bt == "toggle":
            lines.append(
                f"<details><summary>{rich_text_to_str(block['toggle']['rich_text'])}</summary></details>"
            )
        elif bt == "divider":
            lines.append("---")
        elif bt == "callout":
            text = rich_text_to_str(block["callout"]["rich_text"])
            emoji = block["callout"].get("icon", {}).get("emoji", "")
            lines.append(f"> {emoji} {text}")
        elif bt == "quote":
            lines.append(f"> {rich_text_to_str(block['quote']['rich_text'])}")
        elif bt == "code":
            text = rich_text_to_str(block["code"]["rich_text"])
            lang = block["code"].get("language", "")
            lines.append(f"```{lang}\n{text}\n```")
        elif bt == "table_row":
            cells = block.get("table_row", {}).get("cells", [])
            row = " | ".join(rich_text_to_str(cell) for cell in cells)
            lines.append(f"| {row} |")
        elif bt == "child_page":
            lines.append(
                f"**{block['child_page'].get('title', 'Untitled')}** (sub-page)"
            )
        elif bt == "child_database":
            lines.append(
                f"**{block['child_database'].get('title', 'Untitled')}** (database)"
            )
    return "\n\n".join(lines)


def query_database(db_key, filter_obj=None, sorts=None, limit=None):
    """Query a Notion database via data_sources.query().

    Returns a list of pages or an error string.
    """
    db_conf = DATABASES.get(db_key)
    if not db_conf:
        return f"Unknown database '{db_key}'. Available: {', '.join(DATABASES.keys())}"

    kwargs = {"data_source_id": db_conf["ds_id"]}
    if filter_obj:
        kwargs["filter"] = filter_obj
    if sorts:
        kwargs["sorts"] = sorts
    if limit:
        kwargs["page_size"] = min(limit, 100)

    try:
        response = notion.data_sources.query(**kwargs)
        return response.get("results", [])
    except Exception as e:
        logger.error("Error querying %s: %s", db_key, e)
        return f"Error querying {db_key}: {e}"


def get_data_source_info(db_key):
    """Retrieve data source metadata (title, properties) for a database."""
    db_conf = DATABASES.get(db_key)
    if not db_conf:
        return None
    try:
        return notion.data_sources.retrieve(data_source_id=db_conf["ds_id"])
    except Exception as e:
        logger.error("Error retrieving data source for %s: %s", db_key, e)
        return None


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def search_all(query: str) -> str:
    """Search across all Lambeth Cyclists Notion content.

    Use this for broad queries when you don't know which database to look in,
    or when the user asks a general question.

    Examples of when to use this tool:
    - "anything about bike lanes on Brixton Road"
    - "what do we know about John Smith"
    - "cycle parking"
    """
    try:
        response = notion.search(query=query, page_size=10)
        results = response.get("results", [])
    except Exception as e:
        return f"Search error: {e}"

    if not results:
        return (
            f"No results found for '{query}'. Try different keywords, "
            "or use a specific tool like list_meetings() or get_ward_data()."
        )

    parts = [f"## Search results for '{query}'\n"]
    for page in results:
        parts.append(format_properties(page))
        parts.append("")
    return "\n".join(parts)


@mcp.tool()
def list_meetings(limit: int = 10) -> str:
    """List recent Lambeth Cyclists meetings.

    Returns meetings sorted by date (most recent first). Each result includes
    the meeting title, date, type, and other metadata.

    Use get_meeting_agenda() to get the full content of a specific meeting.

    Examples:
    - list_meetings() — 10 most recent meetings
    - list_meetings(limit=3) — just the latest 3

    Meeting types: regular_committee, special, planning, emergency
    """
    results = query_database(
        "meetings",
        sorts=[{"property": "Meeting Date", "direction": "descending"}],
        limit=limit,
    )
    if isinstance(results, str):
        return results
    if not results:
        return "No meetings found."

    parts = [f"## Meetings (showing {len(results)})\n"]
    for page in results:
        parts.append(format_properties(page))
        parts.append("")
    return "\n".join(parts)


@mcp.tool()
def get_meeting_agenda(date: str = "", title_search: str = "") -> str:
    """Get the full agenda or minutes for a specific meeting.

    Looks up a meeting by date or title keyword, then returns its properties
    AND full page content (agenda items, minutes, notes, etc.).

    Args:
        date: Date string like "2026-03-05" or partial like "2026-03".
              Matches against the "Meeting Date" property.
        title_search: Keyword(s) to match in the meeting title, e.g. "AGM".

    Examples:
    - get_meeting_agenda(date="2026-03-05")
    - get_meeting_agenda(title_search="AGM")
    - get_meeting_agenda(date="2026-02") — any meeting in Feb 2026
    """
    # If exact date given, try server-side filter first
    filter_obj = None
    if date and len(date) == 10:  # YYYY-MM-DD
        filter_obj = {
            "property": "Meeting Date",
            "date": {"equals": date},
        }

    results = query_database(
        "meetings",
        filter_obj=filter_obj,
        sorts=[{"property": "Meeting Date", "direction": "descending"}],
        limit=20,
    )
    if isinstance(results, str):
        return results
    if not results and filter_obj:
        # Exact date didn't match — fall back to fetching all and filtering
        results = query_database(
            "meetings",
            sorts=[{"property": "Meeting Date", "direction": "descending"}],
            limit=20,
        )
        if isinstance(results, str):
            return results

    if not results:
        return "No meetings found. Try list_meetings() to see what's available."

    # Client-side filter by partial date (e.g. "2026-02")
    if date and len(date) < 10:
        date_matched = []
        for page in results:
            meeting_date = page.get("properties", {}).get("Meeting Date", {})
            if meeting_date.get("type") == "date" and meeting_date.get("date"):
                if meeting_date["date"].get("start", "").startswith(date):
                    date_matched.append(page)
        if date_matched:
            results = date_matched

    # Filter by title keyword
    if title_search:
        title_matched = [
            p for p in results
            if title_search.lower() in get_page_title(p).lower()
        ]
        if title_matched:
            results = title_matched

    if not results:
        return (
            f"No meetings matched date='{date}' title='{title_search}'. "
            "Try list_meetings() to see available meetings."
        )

    # Return the best match with full page content
    page = results[0]
    parts = [format_properties(page), "\n---\n"]

    content = get_page_content(page["id"])
    parts.append(content if content else "*(No page content found)*")

    if len(results) > 1:
        parts.append(
            f"\n---\n*{len(results) - 1} other meeting(s) also matched. "
            "Showing the most recent.*"
        )
    return "\n".join(parts)


@mcp.tool()
def get_action_items(status: str = "all", assignee: str = "") -> str:
    """Get action items from the Items database.

    The Items database contains emails, consultations, and action items
    received by Lambeth Cyclists.

    Args:
        status: Filter by status — "all" for everything, or one of:
                "new", "reviewed", "response_drafted", "submitted",
                "monitoring", "closed"
        assignee: Filter by person name (case-insensitive partial match).

    Examples:
    - get_action_items() — everything
    - get_action_items(status="new") — new/unprocessed items
    - get_action_items(status="monitoring") — items being monitored
    """
    filter_obj = None
    if status and status.lower() != "all":
        filter_obj = {
            "property": "Status",
            "select": {"equals": status},
        }

    results = query_database(
        "items",
        filter_obj=filter_obj,
        sorts=[{"property": "Date Received", "direction": "descending"}],
    )
    if isinstance(results, str):
        return results

    # Client-side filter for assignee
    if assignee and results:
        filtered = [
            p for p in results
            if assignee.lower() in format_properties(p).lower()
        ]
        if not filtered:
            return f"No items found for '{assignee}'."
        results = filtered

    if not results:
        msg = "No items found"
        if status and status.lower() != "all":
            msg += f" with status '{status}'"
        return msg + "."

    parts = [f"## Items ({len(results)} found)\n"]
    for page in results:
        parts.append(format_properties(page))
        parts.append("")
    return "\n".join(parts)


@mcp.tool()
def get_ward_data(ward_name: str = "") -> str:
    """Get ward-level data from the Wards database.

    Returns ward information including election analysis for the May 2026
    Lambeth council elections. Data includes competitiveness, 2022 margin,
    priority level, cycling issues, and engagement status.

    Args:
        ward_name: Optional ward name (case-insensitive partial match).
                   Leave empty to get all wards.

    Competitiveness values: Safe Labour, Labour-Green, Labour-LD, Three-way
    Priority values: High, Medium, Low
    Status values: Research, Outreach, Engaged, Committed, No response

    Examples:
    - get_ward_data() — all wards
    - get_ward_data("Brixton") — wards matching "Brixton"
    - get_ward_data("Herne Hill") — Herne Hill ward
    """
    results = query_database("wards")
    if isinstance(results, str):
        return results
    if not results:
        return "No ward data found."

    if ward_name:
        filtered = [
            p for p in results
            if ward_name.lower() in get_page_title(p).lower()
        ]
        if not filtered:
            all_names = [get_page_title(p) for p in results]
            return (
                f"No ward matching '{ward_name}'. "
                f"Available wards: {', '.join(sorted(all_names))}"
            )
        results = filtered

    parts = [
        f"## Ward Data ({len(results)} ward{'s' if len(results) != 1 else ''})\n"
    ]
    for page in results:
        parts.append(format_properties(page))
        parts.append("")
    return "\n".join(parts)


@mcp.tool()
def get_councillor_data(
    ward_name: str = "",
    councillor_name: str = "",
    party: str = "",
) -> str:
    """Get councillor and candidate information.

    The Councillors & Candidates database tracks current councillors and
    declared/potential candidates for the May 2026 Lambeth elections,
    including their party, ward, position on cycling, and engagement level.

    Args:
        ward_name: Filter by ward (case-insensitive partial match).
        councillor_name: Filter by name (case-insensitive partial match).
        party: Filter by party — "Labour", "Green", "Liberal Democrat",
               or "Conservative".

    Status values: Current Councillor, Declared Candidate, Potential Candidate,
                   2026 Candidate, Departed
    Engagement values: Not contacted, Contacted, Meeting scheduled, Supportive,
                       Committed, Opposed

    Examples:
    - get_councillor_data() — all councillors and candidates
    - get_councillor_data(party="Green")
    - get_councillor_data(councillor_name="Smith")
    - get_councillor_data(ward_name="Brixton")
    """
    filter_obj = None
    if party:
        filter_obj = {
            "property": "Party",
            "select": {"equals": party},
        }

    results = query_database("councillors", filter_obj=filter_obj)
    if isinstance(results, str):
        return results
    if not results:
        return "No councillor data found."

    if councillor_name:
        results = [
            p for p in results
            if councillor_name.lower() in get_page_title(p).lower()
        ]
    if ward_name:
        results = [
            p for p in results
            if ward_name.lower() in format_properties(p).lower()
        ]

    if not results:
        return "No councillors found matching those criteria."

    parts = [f"## Councillors & Candidates ({len(results)} found)\n"]
    for page in results:
        parts.append(format_properties(page))
        parts.append("")
    return "\n".join(parts)


@mcp.tool()
def get_battleground_wards() -> str:
    """Get wards that are competitive for the May 2026 Lambeth elections.

    Returns wards where the Competitiveness is NOT "Safe Labour" — i.e.,
    wards classified as Labour-Green, Labour-LD, or Three-way marginals.
    Also includes any wards with Priority set to "High".
    """
    results = query_database("wards")
    if isinstance(results, str):
        return results
    if not results:
        return "No ward data found."

    battleground = []
    for page in results:
        props = page.get("properties", {})

        # Check Competitiveness
        comp = props.get("Competitiveness", {})
        if comp.get("type") == "select" and comp.get("select"):
            comp_val = comp["select"]["name"]
            if comp_val != "Safe Labour":
                battleground.append(page)
                continue

        # Check Priority
        priority = props.get("Priority", {})
        if priority.get("type") == "select" and priority.get("select"):
            if priority["select"]["name"] == "High":
                battleground.append(page)
                continue

    if not battleground:
        return (
            "No battleground wards found. All wards may be classified as "
            "Safe Labour, or competitiveness data hasn't been entered yet. "
            "Use get_ward_data() to see all ward data."
        )

    parts = [f"## Battleground Wards ({len(battleground)} found)\n"]
    for page in battleground:
        parts.append(format_properties(page))
        parts.append("")
    return "\n".join(parts)


@mcp.tool()
def get_projects(status: str = "all") -> str:
    """Get projects from the Projects database.

    Lambeth Cyclists' campaigns and projects, including infrastructure
    campaigns, partnerships, research, and ongoing monitoring.

    Args:
        status: "all" for everything, or one of:
                "planning", "active", "paused", "completed", "archived"

    Project types: infrastructure_campaign, campaigning, research,
                   partnership, ongoing_monitoring, membership

    Examples:
    - get_projects() — all projects
    - get_projects("active") — only active projects
    - get_projects("planning") — projects in planning phase
    """
    filter_obj = None
    if status and status.lower() != "all":
        filter_obj = {
            "property": "Status",
            "select": {"equals": status},
        }

    results = query_database(
        "projects",
        filter_obj=filter_obj,
        sorts=[{"property": "Start Date", "direction": "descending"}],
    )
    if isinstance(results, str):
        return results
    if not results:
        msg = "No projects found"
        if status and status.lower() != "all":
            msg += f" with status '{status}'"
        return msg + "."

    parts = [f"## Projects ({len(results)} found)\n"]
    for page in results:
        parts.append(format_properties(page))
        parts.append("")
    return "\n".join(parts)


@mcp.tool()
def get_page_detail(page_id: str) -> str:
    """Get the full content of any Notion page by its ID.

    Use this to drill into a specific page when other tools return summaries
    and you need the full content (meeting minutes, detailed ward notes, etc.).

    The page ID is included in results from other tools (listed as 'Page ID').

    Args:
        page_id: The Notion page ID string.
    """
    try:
        page = notion.pages.retrieve(page_id=page_id)
    except Exception as e:
        return f"Error retrieving page: {e}"

    parts = [format_properties(page), "\n---\n"]
    content = get_page_content(page_id)
    parts.append(content if content else "*(No page content)*")
    return "\n".join(parts)


@mcp.tool()
def list_databases() -> str:
    """List all available Notion databases and their property schemas.

    Use this to discover what data is available, what each database is called,
    and what property names/types it has. Helpful for understanding the data
    model or debugging when queries don't return expected results.
    """
    parts = ["## Available Databases\n"]

    for key, db_conf in DATABASES.items():
        ds_info = get_data_source_info(key)
        if ds_info:
            title = rich_text_to_str(ds_info.get("title", []))
            parts.append(f"### {title or db_conf['label']}")
            parts.append(f"- **Key**: `{key}`")

            props = ds_info.get("properties", {})
            if props:
                parts.append(f"- **Properties** ({len(props)}):")
                for prop_name, prop_info in sorted(props.items()):
                    ptype = prop_info["type"]
                    extra = ""
                    if ptype == "select":
                        opts = [
                            o["name"]
                            for o in prop_info.get("select", {}).get(
                                "options", []
                            )
                        ]
                        if opts:
                            extra = f" — options: {', '.join(opts)}"
                    parts.append(f"  - {prop_name} (`{ptype}`){extra}")
        else:
            parts.append(f"### {db_conf['label']}")
            parts.append(f"- **Key**: `{key}`")
            parts.append("- *(Could not retrieve database info)*")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Server startup
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    transport = sys.argv[1] if len(sys.argv) > 1 else "streamable-http"

    logger.info(
        "Starting Lambeth Cyclists MCP server — port=%s transport=%s",
        port,
        transport,
    )

    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
