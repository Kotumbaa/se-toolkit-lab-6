# Agent Architecture

## Overview

This agent is a CLI tool that answers questions about the project by calling a Large Language Model (LLM) with **tools**. The agent can:
- List files in directories (`list_files`)
- Read file contents (`read_file`)
- Query the backend HTTP API (`query_api`)
- Use an **agentic loop** to iteratively discover information and answer complex questions

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────┐
│  Command Line   │ ──▶ │   agent.py   │ ──▶ │  LLM API    │ ──▶ │  Answer  │
│  "How many      │     │  (Python +   │     │  (Qwen)     │     │  (JSON   │
│  items in DB?"  │     │   3 Tools)   │     │  + Tools    │     │  + Tools)│
└─────────────────┘     └──────────────┘     └─────────────┘     └──────────┘
                               │
                               ▼
                        ┌─────────────┐
                        │ Backend API │
                        │ (FastAPI)   │
                        └─────────────┘
```

## Components

### 1. Environment Loading

The agent reads configuration from two files:

**`.env.agent.secret`** (LLM configuration):
| Variable | Purpose |
|----------|---------|
| `LLM_API_KEY` | API key for LLM authentication |
| `LLM_API_BASE` | Base URL of the LLM API endpoint |
| `LLM_MODEL` | Model name (e.g., `qwen3-coder-plus`) |

**`.env.docker.secret`** (Backend API configuration):
| Variable | Purpose |
|----------|---------|
| `LMS_API_KEY` | API key for backend authentication |
| `AGENT_API_BASE_URL` | Base URL for backend API (default: `http://localhost:42002`) |

**Important:** The autochecker injects its own values. Never hardcode these!

### 2. Tools

The agent has three tools that the LLM can call:

#### `read_file`
Reads the contents of a file from the project repository.

- **Parameters:** `path` (string) — relative path from project root
- **Returns:** File contents as string, or error message
- **Security:** Validates path to prevent directory traversal (`..` not allowed)

#### `list_files`
Lists files and directories in a directory.

- **Parameters:** `path` (string) — relative directory path from project root
- **Returns:** Newline-separated list of entries
- **Security:** Validates path to prevent directory traversal

#### `query_api`
Calls the backend HTTP API with authentication.

- **Parameters:** 
  - `method` (string) — HTTP method (GET, POST, PUT, DELETE)
  - `path` (string) — API path (e.g., `/items/`, `/analytics/completion-rate`)
  - `body` (string, optional) — JSON request body for POST/PUT
- **Returns:** JSON string with `status_code` and `body`
- **Authentication:** Uses `Authorization: Bearer {LMS_API_KEY}` header

**Implementation:**
```python
def query_api(method: str, path: str, body: str = None) -> str:
    url = f"{AGENT_API_BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {LMS_API_KEY}",
        "Content-Type": "application/json",
    }
    response = httpx.request(method, url, headers=headers, json=body)
    return json.dumps({
        "status_code": response.status_code,
        "body": response.json() if response.content else None
    })
```

### 3. Agentic Loop

The agent uses an iterative loop to answer questions:

```
1. Send user question + all tool definitions to LLM
2. Parse response:
   - If tool_calls: 
     a. Execute each tool (read_file, list_files, or query_api)
     b. Append assistant message + tool results to conversation
     c. Go to step 1
   - If content (no tool_calls):
     a. Extract answer
     b. Extract source reference
     c. Return JSON and exit
3. Max 10 iterations (prevents infinite loops)
```

**Key insight:** After each tool call, we must append BOTH the assistant's message (with tool_calls) AND the tool response to the conversation history. This lets the LLM understand the full context.

### 4. System Prompt

The system prompt guides the LLM to use tools appropriately:

```
You are a documentation and system assistant for a software engineering lab project.

You have access to these tools:
1. `list_files` - List files in a directory (use for discovering wiki files)
2. `read_file` - Read file contents (use for finding information in documentation or source code)
3. `query_api` - Call the backend HTTP API (use for questions about data, database contents, system status, or API endpoints)

When asked a question:
- For documentation questions → use `list_files` then `read_file`
- For data questions (how many items, what is the score, etc.) → use `query_api`
- For system questions (what framework, what port) → use `read_file` on source code or `query_api`

Always include the source reference in your final answer when using wiki files.
For API queries, mention the endpoint used.
```

### 5. Output Format

```json
{
  "answer": "There are 120 items in the database.",
  "source": "",  // Optional for API queries
  "tool_calls": [
    {
      "tool": "query_api",
      "args": {"method": "GET", "path": "/items/"},
      "result": "{\"status_code\": 200, \"body\": [...]}"
    }
  ]
}
```

## LLM Provider

**Provider:** Qwen Code API (via qwen-code-oai-proxy)

**Model:** `qwen3-coder-plus`

**Why this choice:**
- Works from Russia without VPN
- 1000 free requests per day
- OpenAI-compatible API with tool calling support
- Strong code understanding capabilities

## Tool Calling Format

The agent uses the OpenAI-compatible tool calling format:

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "query_api",
        "description": "Call the backend HTTP API...",
        "parameters": {
          "type": "object",
          "properties": {
            "method": {"type": "string", "description": "HTTP method..."},
            "path": {"type": "string", "description": "API path..."},
            "body": {"type": "string", "description": "Optional JSON body..."}
          },
          "required": ["method", "path"],
          "additionalProperties": false
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

## Path Security

Both file tools validate paths to prevent directory traversal:

```python
def validate_path(path: str) -> Path:
    # Reject paths with '..'
    if ".." in path:
        raise ValueError(f"Path traversal not allowed: {path}")
    
    # Resolve to absolute path
    project_root = Path(__file__).parent.resolve()
    full_path = (project_root / path).resolve()
    
    # Ensure path is within project root
    if not str(full_path).startswith(str(project_root)):
        raise ValueError(f"Path outside project: {path}")
    
    return full_path
```

## Error Handling

| Error | Behavior |
|-------|----------|
| Missing environment variables | Print error to stderr, exit code 1 |
| Network timeout (>60s for LLM, >30s for API) | Print error to stderr, exit code 1 |
| Invalid API response | Print error to stderr, exit code 1 |
| Path traversal attempt | Return error message as tool result |
| Max iterations reached | Return partial answer with tool_calls so far |
| API authentication error | Return 401 status in tool result |

## Usage

```bash
# Basic usage
uv run agent.py "What files are in the wiki?"

# Question requiring file reading
uv run agent.py "How do you resolve a merge conflict?"

# Question requiring API query
uv run agent.py "How many items are in the database?"

# Example output
{
  "answer": "...",
  "source": "wiki/git.md#merge-conflict",
  "tool_calls": [...]
}
```

## File Structure

```
agent.py              # Main CLI script with tools and agentic loop
.env.agent.secret     # LLM credentials (gitignored)
.env.docker.secret    # Backend API credentials (gitignored)
AGENT.md              # This documentation
plans/task-3.md       # Implementation plan + benchmark results
tests/test_agent.py   # Regression tests (5 tests)
```

## Testing

Run tests with:
```bash
uv run pytest tests/test_agent.py -v
```

Tests:
1. `test_agent_returns_valid_json` — Basic JSON output validation
2. `test_agent_uses_list_files_tool` — Verifies list_files for wiki questions
3. `test_agent_uses_read_file_for_merge_conflict` — Verifies read_file and source extraction
4. `test_agent_uses_query_api_for_item_count` — Verifies query_api for database questions
5. `test_agent_uses_query_api_for_status` — Verifies query_api for status questions

## Benchmark Results

**Local Score:** 4/5 passing questions (80%)

### Passing Questions
- ✅ Branch protection steps (wiki lookup)
- ✅ SSH connection steps (wiki lookup)
- ✅ Python web framework (source code lookup)
- ✅ API router modules (source code lookup)

### Known Issues
- ❌ Item count question — Database is empty locally (ETL pipeline not run). Agent correctly uses `query_api` but returns 0 items. The autochecker will run with a populated database.

## Lessons Learned

1. **Tool message order matters:** When sending tool results back to the LLM, you must first append the assistant's message (with tool_calls), then append the tool response. Skipping the assistant message causes API errors.

2. **Path validation is critical:** Without proper validation, tools could read sensitive files outside the project directory.

3. **System prompt design:** The system prompt needs to explicitly tell the LLM when to use each tool. We learned to categorize questions:
   - Documentation → `list_files` + `read_file`
   - Data → `query_api`
   - System facts → either `read_file` or `query_api`

4. **Debug output to stderr:** Keeping stdout clean for JSON parsing while logging to stderr makes debugging much easier.

5. **API authentication:** The backend uses `Authorization: Bearer {LMS_API_KEY}` header format, not `X-API-Key`. Getting this wrong causes 401 errors.

6. **Environment variable separation:** Two distinct keys serve different purposes:
   - `LLM_API_KEY` — authenticates with the LLM provider
   - `LMS_API_KEY` — authenticates with the backend API
   Mixing these up causes authentication failures.

7. **Database state matters:** The agent can only report what's actually in the database. If the ETL pipeline hasn't run, the database will be empty and the agent will correctly report 0 items.

## Architecture Summary

The agent follows a **tool-augmented LLM** architecture:

1. **LLM as reasoner:** The LLM decides which tool to call based on the question
2. **Tools as effectors:** Tools execute real-world actions (read files, call APIs)
3. **Loop as integrator:** The agentic loop feeds tool results back to the LLM
4. **JSON as interface:** Clean separation between agent logic and external consumers

This architecture allows the agent to answer complex questions that require multiple steps of information gathering and synthesis.
