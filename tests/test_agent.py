"""Regression tests for agent.py."""

import json
import subprocess


def test_agent_returns_valid_json():
    """Test that agent.py outputs valid JSON with required fields."""
    result = subprocess.run(
        ["uv", "run", "agent.py", "What is 2+2?"],
        capture_output=True,
        text=True,
    )
    
    # Check exit code
    assert result.returncode == 0, f"Agent failed: {result.stderr}"
    
    # Parse stdout as JSON
    output = json.loads(result.stdout)
    
    # Check required fields
    assert "answer" in output, "Missing 'answer' field in output"
    assert "tool_calls" in output, "Missing 'tool_calls' field in output"
    
    # Check field types
    assert isinstance(output["answer"], str), "'answer' should be a string"
    assert isinstance(output["tool_calls"], list), "'tool_calls' should be a list"
    
    # Check that answer is non-empty
    assert len(output["answer"]) > 0, "'answer' should not be empty"


def test_agent_uses_list_files_tool():
    """Test that agent uses list_files tool for wiki directory question."""
    result = subprocess.run(
        ["uv", "run", "agent.py", "What files are in the wiki?"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    
    # Check exit code
    assert result.returncode == 0, f"Agent failed: {result.stderr}"
    
    # Parse stdout as JSON
    output = json.loads(result.stdout)
    
    # Check that tool_calls is populated
    assert len(output["tool_calls"]) > 0, "Expected tool_calls to be populated"
    
    # Check that list_files was used
    tool_names = [tc["tool"] for tc in output["tool_calls"]]
    assert "list_files" in tool_names, "Expected list_files tool to be used"


def test_agent_uses_read_file_for_merge_conflict():
    """Test that agent uses read_file tool for merge conflict question."""
    result = subprocess.run(
        ["uv", "run", "agent.py", "How do you resolve a merge conflict?"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    
    # Check exit code
    assert result.returncode == 0, f"Agent failed: {result.stderr}"
    
    # Parse stdout as JSON
    output = json.loads(result.stdout)
    
    # Check that tool_calls is populated
    assert len(output["tool_calls"]) > 0, "Expected tool_calls to be populated"
    
    # Check that read_file was used
    tool_names = [tc["tool"] for tc in output["tool_calls"]]
    assert "read_file" in tool_names, "Expected read_file tool to be used"
    
    # Check that source contains wiki reference
    assert "wiki/" in output.get("source", ""), "Expected source to contain wiki/ reference"


def test_agent_uses_query_api_for_item_count():
    """Test that agent uses query_api tool for database count question."""
    result = subprocess.run(
        ["uv", "run", "agent.py", "How many items are in the database?"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    
    # Check exit code
    assert result.returncode == 0, f"Agent failed: {result.stderr}"
    
    # Parse stdout as JSON
    output = json.loads(result.stdout)
    
    # Check that tool_calls is populated
    assert len(output["tool_calls"]) > 0, "Expected tool_calls to be populated"
    
    # Check that query_api was used
    tool_names = [tc["tool"] for tc in output["tool_calls"]]
    assert "query_api" in tool_names, "Expected query_api tool to be used"
    
    # Verify the API call was made correctly
    api_call = next(tc for tc in output["tool_calls"] if tc["tool"] == "query_api")
    assert api_call["args"]["method"] == "GET", "Expected GET method for query_api"
    assert "/items" in api_call["args"]["path"], "Expected /items path for query_api"


def test_agent_uses_query_api_for_status():
    """Test that agent uses query_api tool for status question."""
    result = subprocess.run(
        ["uv", "run", "agent.py", "What is the API status?"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    
    # Check exit code
    assert result.returncode == 0, f"Agent failed: {result.stderr}"
    
    # Parse stdout as JSON
    output = json.loads(result.stdout)
    
    # Check that tool_calls is populated
    assert len(output["tool_calls"]) > 0, "Expected tool_calls to be populated"
    
    # Check that query_api was used
    tool_names = [tc["tool"] for tc in output["tool_calls"]]
    assert "query_api" in tool_names, "Expected query_api tool to be used"


if __name__ == "__main__":
    test_agent_returns_valid_json()
    test_agent_uses_list_files_tool()
    test_agent_uses_read_file_for_merge_conflict()
    test_agent_uses_query_api_for_item_count()
    test_agent_uses_query_api_for_status()
    print("All tests passed!")
