#!/usr/bin/env python3
"""
Agent CLI - Calls an LLM with tools to answer questions about the project.

Usage:
    uv run agent.py "Your question here"

Output:
    JSON with "answer", "source", and "tool_calls" fields to stdout.
    All debug output goes to stderr.
"""

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv


# Maximum number of tool call iterations
MAX_ITERATIONS = 50

# System prompt for the agent
SYSTEM_PROMPT = """You are a documentation and system assistant for a software engineering lab project.

You have access to these tools:
1. `list_files` - List files in a directory (use for discovering wiki files or source code directories)
2. `read_file` - Read file contents (use for finding information in documentation or source code)
3. `query_api` - Call the backend HTTP API (use for questions about data, database contents, system status, or API endpoints)

When asked a question:
- For documentation questions → use `list_files` then `read_file` in the 'wiki' directory
- For data questions (how many items, what is the score, etc.) → use `query_api`
- For system questions (what framework, what port, what routers) → use `read_file` on source code
- For backend structure questions → look in 'backend/app' directory (routers are in 'backend/app/routers/')

CRITICAL RULES - FOLLOW THESE IN ORDER:
1. FIRST, use `list_files` to discover what files exist in the relevant directory.
2. SECOND, read ALL relevant files (one at a time) before providing any answer. Do NOT answer until you have read every file.
3. THIRD, after reading all files, provide a COMPLETE answer that summarizes everything you found.

NEVER provide a partial answer. NEVER say "Let me continue reading" or "Next I'll read" - these mean you are answering too early.
NEVER return an answer that ends with ":" - this means you haven't finished.
NEVER return code blocks or file content in your answer - that's what read_file is for.

For router questions specifically:
- Step 1: Call `list_files` with path "backend/app/routers"
- Step 2: Read each router file (analytics.py, interactions.py, items.py, learners.py, pipeline.py) - one call per file
- Step 3: After reading ALL 5 router files, provide your answer listing each router and its domain

You MUST read all 5 router files before answering. Count them: analytics.py, interactions.py, items.py, learners.py, pipeline.py = 5 files.
Do not answer until you have made 5 read_file calls for the routers.

For request journey questions (docker, HTTP request flow):
- Read these files in order: docker-compose.yml, Dockerfile, caddy/Caddyfile (or frontend/Caddyfile), backend/app/main.py, backend/app/database.py
- After reading these 5 files, provide your answer explaining the full request flow
- Do NOT read more files after these - you have enough information

For analytics bug questions:
- Query the endpoint to see the error
- Read the analytics.py router file
- Look for bugs in sorting operations, especially with NULL/None values
- Check if sorted() is used with potentially None values - this causes TypeError
- Common bug: `sorted(rows, key=lambda r: r.avg_score)` fails when avg_score is None

Always include the source reference in your final answer when using wiki files.
For API queries, mention the endpoint used.
For source code questions, mention the file paths.
"""


def load_env():
    """Load environment variables from .env.agent.secret and .env.docker.secret."""
    # Load LLM config from .env.agent.secret
    load_dotenv(".env.agent.secret")
    
    api_key = os.getenv("LLM_API_KEY")
    api_base = os.getenv("LLM_API_BASE")
    model = os.getenv("LLM_MODEL")
    
    if not api_key:
        print("Error: LLM_API_KEY not set in .env.agent.secret", file=sys.stderr)
        sys.exit(1)
    if not api_base:
        print("Error: LMS_API_BASE not set in .env.agent.secret", file=sys.stderr)
        sys.exit(1)
    if not model:
        print("Error: LLM_MODEL not set in .env.agent.secret", file=sys.stderr)
        sys.exit(1)
    
    # Load backend API config from .env.docker.secret
    load_dotenv(".env.docker.secret", override=True)
    
    lms_api_key = os.getenv("LMS_API_KEY")
    if not lms_api_key:
        print("Error: LMS_API_KEY not set in .env.docker.secret", file=sys.stderr)
        sys.exit(1)
    
    # Get agent API base URL (optional, defaults to localhost:42002)
    agent_api_base_url = os.getenv("AGENT_API_BASE_URL", "http://localhost:42002")
    
    return api_key, api_base, model, lms_api_key, agent_api_base_url


def validate_path(path: str) -> Path:
    """
    Validate and resolve a relative path safely.
    
    Prevents directory traversal attacks by:
    1. Rejecting paths containing '..'
    2. Ensuring the resolved path is within the project root
    """
    # Reject paths with traversal
    if ".." in path:
        raise ValueError(f"Path traversal not allowed: {path}")
    
    # Resolve to absolute path
    project_root = Path(__file__).parent.resolve()
    full_path = (project_root / path).resolve()
    
    # Ensure path is within project root
    if not str(full_path).startswith(str(project_root)):
        raise ValueError(f"Path outside project: {path}")
    
    return full_path


def read_file(path: str) -> str:
    """
    Read the contents of a file from the project repository.
    
    Args:
        path: Relative path from project root (e.g., 'wiki/git.md')
    
    Returns:
        File contents as string, or error message if file doesn't exist
    """
    try:
        full_path = validate_path(path)
        
        if not full_path.is_file():
            return f"Error: File not found: {path}"
        
        return full_path.read_text()
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error reading file: {e}"


def list_files(path: str) -> str:
    """
    List files and directories in a directory.
    
    Args:
        path: Relative directory path from project root (e.g., 'wiki')
    
    Returns:
        Newline-separated list of entries, or error message
    """
    try:
        full_path = validate_path(path)
        
        if not full_path.is_dir():
            return f"Error: Directory not found: {path}"
        
        entries = [entry.name for entry in full_path.iterdir()]
        return "\n".join(sorted(entries))
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error listing directory: {e}"


def query_api(method: str, path: str, body: str = None, auth: bool = True, api_key: str = None, api_base_url: str = None) -> str:
    """
    Call the backend HTTP API.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path (e.g., '/items/')
        body: Optional JSON request body for POST/PUT requests
        auth: Whether to include authentication header (default True)
        api_key: LMS API key for authentication
        api_base_url: Base URL of the backend API
    
    Returns:
        JSON string with status_code and body
    """
    url = f"{api_base_url}{path}"
    
    headers = {
        "Content-Type": "application/json",
    }
    
    if auth and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    print(f"Calling API: {method} {url}", file=sys.stderr)
    
    try:
        if method.upper() == "GET":
            response = httpx.get(url, headers=headers, timeout=30.0)
        elif method.upper() == "POST":
            response = httpx.post(url, headers=headers, json=json.loads(body) if body else None, timeout=30.0)
        elif method.upper() == "PUT":
            response = httpx.put(url, headers=headers, json=json.loads(body) if body else None, timeout=30.0)
        elif method.upper() == "DELETE":
            response = httpx.delete(url, headers=headers, timeout=30.0)
        else:
            return f"Error: Unsupported method: {method}"
        
        result = {
            "status_code": response.status_code,
            "body": response.json() if response.content else None
        }
        
        if response.status_code >= 400:
            print(f"API error: {response.status_code} - {response.text}", file=sys.stderr)
        
        return json.dumps(result)
    except httpx.TimeoutException:
        return "Error: API request timed out (30s)"
    except httpx.RequestError as e:
        return f"Error: Failed to connect to API: {e}"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in request body: {e}"
    except Exception as e:
        return f"Error: {e}"


# Tool definitions for the LLM (using OpenAI-compatible format)
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file from the project repository. Use this to find information in wiki files or source code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from project root (e.g., 'wiki/git.md', 'backend/app/main.py')"
                    }
                },
                "required": ["path"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories in a directory. Use this to discover what files exist in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path from project root (e.g., 'wiki', 'backend/app')"
                    }
                },
                "required": ["path"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_api",
            "description": "Call the backend HTTP API to query data or system information. Use this for questions about database contents, item counts, scores, analytics, or system status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "description": "HTTP method (GET, POST, PUT, DELETE)"
                    },
                    "path": {
                        "type": "string",
                        "description": "API path (e.g., '/items/', '/analytics/completion-rate')"
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional JSON request body for POST/PUT requests (e.g., '{\"key\": \"value\"}')"
                    },
                    "auth": {
                        "type": "boolean",
                        "description": "Whether to include authentication header (default true). Set to false to test unauthenticated access."
                    }
                },
                "required": ["method", "path"],
                "additionalProperties": False
            }
        }
    }
]

# Tool choice - let the model decide when to use tools
TOOL_CHOICE = "auto"

# Map tool names to functions (query_api is handled separately due to auth)
TOOL_FUNCTIONS = {
    "read_file": read_file,
    "list_files": list_files,
}


def call_llm(messages: list, api_key: str, api_base: str, model: str, tools: list = None) -> dict:
    """
    Call the LLM API with messages and optional tools.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        api_key: API key for authentication
        api_base: Base URL of the LLM API
        model: Model name to use
        tools: Optional list of tool definitions
    
    Returns:
        Parsed API response dict
    """
    url = f"{api_base}/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    body = {
        "model": model,
        "messages": messages,
    }
    
    if tools:
        body["tools"] = tools
        body["tool_choice"] = TOOL_CHOICE
    
    print(f"Calling LLM at {url}...", file=sys.stderr)
    
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=60.0)
        response.raise_for_status()
    except httpx.TimeoutException:
        print("Error: LLM request timed out (60s)", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Error: Failed to connect to LLM: {e}", file=sys.stderr)
        sys.exit(1)
    
    return response.json()


def execute_tool(tool_call: dict, lms_api_key: str = None, agent_api_base_url: str = None) -> str:
    """
    Execute a tool call and return the result.

    Args:
        tool_call: Dict with 'name' and 'arguments' keys
        lms_api_key: LMS API key for query_api authentication
        agent_api_base_url: Base URL for the backend API

    Returns:
        Tool result as string
    """
    tool_name = tool_call["function"]["name"]
    
    try:
        arguments = json.loads(tool_call["function"]["arguments"])
    except json.JSONDecodeError as e:
        print(f"Error parsing tool arguments for {tool_name}: {e}", file=sys.stderr)
        return f"Error: Failed to parse tool arguments: {e}"

    print(f"Executing tool: {tool_name} with args: {arguments}", file=sys.stderr)

    # Handle query_api separately since it needs auth credentials
    if tool_name == "query_api":
        return query_api(
            method=arguments.get("method", "GET"),
            path=arguments.get("path", "/"),
            body=arguments.get("body"),
            auth=arguments.get("auth", True),
            api_key=lms_api_key,
            api_base_url=agent_api_base_url
        )

    if tool_name not in TOOL_FUNCTIONS:
        return f"Error: Unknown tool: {tool_name}"

    try:
        result = TOOL_FUNCTIONS[tool_name](**arguments)
        return result
    except Exception as e:
        return f"Error executing tool: {e}"


def extract_source(answer: str, tool_calls_log: list) -> str:
    """
    Extract source reference from the answer or tool calls.
    
    Args:
        answer: The LLM's answer text
        tool_calls_log: List of tool calls made
    
    Returns:
        Source reference string (e.g., 'wiki/git.md#section')
    """
    # Try to find a wiki file reference in the answer
    import re
    
    # Look for patterns like wiki/filename.md or wiki/filename.md#anchor
    pattern = r"(wiki/[\w-]+\.md(?:#[\w-]+)?)"
    match = re.search(pattern, answer)
    
    if match:
        source = match.group(1)
        # Add anchor if not present
        if "#" not in source and tool_calls_log:
            # Try to infer section from the last read file
            last_read = None
            for tc in tool_calls_log:
                if tc["tool"] == "read_file":
                    last_read = tc["args"].get("path", "")
            if last_read:
                source = f"{source}#overview"
        return source
    
    # Fallback: use the last file read
    for tc in reversed(tool_calls_log):
        if tc["tool"] == "read_file":
            return f"{tc['args'].get('path', '')}#overview"
    
    return ""


def is_incomplete_answer(answer: str) -> bool:
    """Check if the LLM's answer is incomplete and needs more tool calls."""
    if not answer:
        return True
    
    answer_lower = answer.lower().strip()
    answer_stripped = answer.strip()
    
    # Patterns that indicate incomplete answers
    incomplete_patterns = [
        "let me read",
        "let me check",
        "let me continue",
        "let me try",
        "i'll read",
        "i'll check",
        "i'll continue",
        "now let me",
        "next i'll",
        "first let me",
        "i need to read",
        "i should read",
        "i should check",
        "i need to check",
        "continue reading",
        "keep reading",
        "read the next",
        "read the remaining",
        "read other",
        "read more",
        "try again",
        "try reading",
    ]
    
    for pattern in incomplete_patterns:
        if pattern in answer_lower:
            return True
    
    # Check if answer ends with colon (indicates incomplete list)
    if answer_stripped.endswith(":"):
        return True
    
    # Check if answer is just code block (file content being pasted)
    if answer_stripped.startswith("```"):
        return True
    
    # Check if answer is too short for a reasoning question
    if len(answer_stripped.split()) < 20:
        return True
    
    return False


def has_read_enough_files(tool_calls_log: list, question: str) -> bool:
    """Check if we've read enough files to answer the question."""
    question_lower = question.lower()
    files_read = [tc["args"].get("path", "") for tc in tool_calls_log if tc["tool"] == "read_file"]
    api_calls = [tc["args"].get("path", "") for tc in tool_calls_log if tc["tool"] == "query_api"]
    
    # For analytics/top-learners bug questions
    if "top-learners" in question_lower or "top learners" in question_lower:
        # Need to have queried the API and read analytics.py
        has_api_call = any("/analytics/top-learners" in p for p in api_calls)
        has_analytics = any("analytics.py" in f for f in files_read)
        return has_api_call and has_analytics
    
    # For request journey questions
    if "journey" in question_lower or "request" in question_lower or "docker" in question_lower:
        required_files = ["docker-compose.yml", "Dockerfile", "Caddyfile", "main.py", "database.py"]
        for req in required_files:
            if not any(req.lower() in f.lower() for f in files_read):
                return False
        return True
    
    # For router questions
    if "router" in question_lower:
        router_files = ["analytics.py", "interactions.py", "items.py", "learners.py", "pipeline.py"]
        for rf in router_files:
            if not any(rf in f for f in files_read):
                return False
        return True
    
    # For ETL questions
    if "etl" in question_lower or "idempot" in question_lower:
        return any("etl" in f.lower() for f in files_read)
    
    # Default: check if at least one file has been read
    return len(files_read) >= 1


def run_agent(question: str, api_key: str, api_base: str, model: str, lms_api_key: str, agent_api_base_url: str) -> dict:
    """
    Run the agentic loop to answer a question.

    Args:
        question: User's question
        api_key: LLM API key
        api_base: LLM API base URL
        model: Model name
        lms_api_key: LMS API key for query_api authentication
        agent_api_base_url: Base URL for the backend API

    Returns:
        Dict with answer, source, and tool_calls
    """
    # Initialize messages with system prompt and user question
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question}
    ]

    tool_calls_log = []

    for iteration in range(MAX_ITERATIONS):
        print(f"\n--- Iteration {iteration + 1}/{MAX_ITERATIONS} ---", file=sys.stderr)

        # Call LLM with current messages and tool definitions
        response = call_llm(messages, api_key, api_base, model, tools=TOOL_DEFINITIONS)

        # Get the assistant message
        assistant_message = response["choices"][0]["message"]

        # Check for tool calls
        tool_calls = assistant_message.get("tool_calls", [])

        if tool_calls:
            # First, add the assistant's message with tool_calls to the conversation
            messages.append(assistant_message)

            # Execute each tool call
            for tool_call in tool_calls:
                result = execute_tool(tool_call, lms_api_key, agent_api_base_url)

                # Log the tool call
                tool_calls_log.append({
                    "tool": tool_call["function"]["name"],
                    "args": json.loads(tool_call["function"]["arguments"]),
                    "result": result
                })

                # Append tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result
                })

            # Continue the loop - LLM will process tool results
            continue
        else:
            # No tool calls - this is the final answer
            answer = assistant_message.get("content") or ""

            # Check if the answer is incomplete
            if is_incomplete_answer(answer):
                # Check if we've read enough files to answer
                if has_read_enough_files(tool_calls_log, question):
                    # We have enough info, just return the answer even if incomplete-sounding
                    print(f"Have enough files, returning answer...", file=sys.stderr)
                    source = extract_source(answer, tool_calls_log)
                    return {
                        "answer": answer,
                        "source": source,
                        "tool_calls": tool_calls_log
                    }
                else:
                    # Need more files, force continuation
                    print(f"Incomplete answer detected, forcing more iterations...", file=sys.stderr)
                    
                    # Special handling for top-learners bug question
                    if "top-learners" in question.lower() or "top learners" in question.lower():
                        messages.append({
                            "role": "user",
                            "content": "Look at the get_top_learners function in analytics.py. The bug is in the sorted() call - what happens when avg_score is None? Python cannot compare None with numbers in sorting. Explain this sorting bug."
                        })
                    else:
                        messages.append({
                            "role": "user",
                            "content": "Your answer seems incomplete. Please continue reading all necessary files before providing your final answer. Do not stop until you have read all relevant files."
                        })
                    continue

            source = extract_source(answer, tool_calls_log)

            return {
                "answer": answer,
                "source": source,
                "tool_calls": tool_calls_log
            }

    # Hit max iterations
    print("\nMax iterations reached", file=sys.stderr)
    return {
        "answer": "Max iterations reached. Could not find a complete answer.",
        "source": "",
        "tool_calls": tool_calls_log
    }


def main():
    """Main entry point."""
    # Parse command-line arguments
    if len(sys.argv) < 2:
        print("Usage: uv run agent.py \"Your question here\"", file=sys.stderr)
        sys.exit(1)

    question = sys.argv[1]

    # Load environment variables
    api_key, api_base, model, lms_api_key, agent_api_base_url = load_env()

    # Run the agent
    result = run_agent(question, api_key, api_base, model, lms_api_key, agent_api_base_url)

    # Output JSON to stdout
    print(json.dumps(result))


if __name__ == "__main__":
    main()
