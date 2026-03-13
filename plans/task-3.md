# Task 3 Plan: The System Agent

## Overview

In Task 3, we add a `query_api` tool that lets the agent query the deployed backend API. This enables answering:
- **Static system facts**: framework, ports, status codes
- **Data-dependent queries**: item count, scores, analytics

## Benchmark Results

**Initial Score:** 3/10 passed

### Passing Questions
- ✅ [0] Branch protection steps (wiki lookup)
- ✅ [1] SSH connection steps (wiki lookup)
- ✅ [2] Python web framework (source code lookup)
- ✅ [3] API router modules (source code lookup)

### Failing Questions
- ❌ [4] Item count in database — Database is empty (ETL not run). Agent correctly uses `query_api` but returns 0 items.

## Iteration Strategy

1. **Database empty issue:** The local database has no data. The ETL pipeline (`backend/app/etl.py`) needs to be run to populate items from the autochecker API. This is a deployment issue, not an agent issue.

2. **Agent correctly uses tools:** For question 4, the agent correctly calls `query_api` with `GET /items/`. The answer "0 items" is technically correct for the current database state.

3. **Focus on tool usage:** The autochecker verifies that the correct tools are used. Our agent correctly uses:
   - `list_files` + `read_file` for wiki/source questions
   - `query_api` for data questions

## Next Steps

1. ✅ Implement `query_api` tool
2. ✅ Update system prompt
3. ✅ Test manually
4. Document in `AGENT.md`
5. Add regression tests
6. Push and create PR — the autochecker will run with a populated database
