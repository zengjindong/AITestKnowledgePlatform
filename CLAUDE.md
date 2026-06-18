# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-Agent AI Test Engineer System — a Python application that turns natural-language requirements into traceable test cases by coordinating four specialized agents (PM, FE, BE, QA) through a multi-stage workflow. Every test case carries an "evidence chain" linking its steps back to the requirement, business rule, API definition, code reference, or user clarification that justified it. Local-first by design: it shells out to a local Claude CLI / Ollama via subprocess, persists state to SQLite, and stores embeddings for semantic memory search.

The full product requirements doc is `AI 测试工程师系统.md` (Chinese PRD); `QUICKSTART.md` mirrors the README.

## Common Commands

All commands assume the repo root (`D:\code\AITestKnowledgePlatform`) and the existing `.venv` (a venv lives at `.venv/`). There is no `requirements.txt` / `pyproject.toml` checked in — dependencies (sqlite3, sentence-transformers, sklearn, flask, playwright) are presumed installed in `.venv`. Add new deps manually if you introduce them.

```bash
# Activate the venv
source .venv/Scripts/activate          # bash on Windows
# or
.venv\Scripts\activate                 # cmd / PowerShell

# Run a single requirement through the pipeline
python -m src --requirement "用户登录系统时，需要输入用户名和密码"

# Run the bundled demo (Chinese login requirement with lockout rule)
python -m src --demo

# Interactive REPL
python -m src --interactive

# Run with mock LLM (no Claude CLI / Ollama required) — fastest way to verify wiring
python -m src --mock --demo

# Inspect SQLite memory contents
python -m src --stats

# Reset workflow + memory state
python -m src --reset

# Run all unit tests
python -m unittest discover -s tests -v

# Run a single test class / method
python -m unittest tests.test_core.TestEvidenceChain.test_add_evidence -v
```

Tests live in `tests/test_core.py`; the entry point is `src/__main__.py` → `src.cli:main()`.

## Architecture

```
                ┌────────────────────────────────────────────┐
                │  src/cli.py  (argparse: --requirement /    │
                │              --interactive / --demo /     │
                │              --mock / --stats / --reset)   │
                └────────────────────┬───────────────────────┘
                                     │
                ┌────────────────────▼───────────────────────┐
                │  src/orchestrator/workflow.py              │
                │   Orchestrator  · MockOrchestrator         │
                │   WorkflowStage FSM (PM_PARSING →           │
                │     PM_CLARIFICATION → FE_BE_ANALYSIS →    │
                │     QA_REVIEW ↔ QA_CHALLENGE ↔             │
                │     CHALLENGE_RESPONSE → GENERATING_… →    │
                │     DONE)                                  │
                └─┬───────────┬────────────┬────────────┬────┘
                  │           │            │            │
       src/agents/   │           │            │            │
        pm_agent.py  │ fe_agent.py│ be_agent.py│ qa_agent.py
                  │           │            │            │
                  └───────── src/agents/base_agent.py ────┘
                              (think / act / respond_to_challenge)
                                       │
                ┌──────────────────────┴──────────────────────┐
                │  src/adapters/llm_adapter.py                │
                │   LLMAdapter  (subprocess → claude CLI /    │
                │                 ollama)                     │
                │   MockLLMAdapter (returns scripted JSON)    │
                └─────────────────────────────────────────────┘
                                       │
   ┌───────────────────┐  ┌────────────┴────────────┐  ┌─────────────────────┐
   │ src/memory/       │  │ src/agents/             │  │ src/knowledge/      │
   │  storage.py       │  │  evidence_chain.py      │  │  indexer.py         │
   │  vector_store.py  │  │  (EvidenceType enum,    │  │  explorer.py        │
   │  (SQLite + embed) │  │   EvidenceChainBuilder) │  │  fe_knowledge.py    │
   │                   │  │                         │  │  be_knowledge.py    │
   │                   │  │                         │  │  be_indexer.py      │
   │                   │  │                         │  │  document_processor │
   │                   │  │                         │  │  impact_analyzer    │
   │                   │  │                         │  │  defect_report      │
   └───────────────────┘  └─────────────────────────┘  └─────────────────────┘
```

### Workflow SOP (see `Orchestrator.run` in `src/orchestrator/workflow.py`)

1. **PM stage** — `ProductManagerAgent.act(requirement)` returns structured requirements or, when it detects ambiguities, returns `output.questions` and the workflow halts with `status: "needs_clarification"`. Use `Orchestrator.provide_clarification(answers)` to resume; PM's `apply_clarifications` turns answers into `BIZ_RULE` evidence items.
2. **FE/BE stage** — both agents run in parallel against the parsed PM output. They lazy-load from a JSON knowledge base (see `data/frontend_knowledge_base.json`, `data/backend_knowledge_base.json`) and fall back to filesystem scans over `CODE_ANALYSIS_CONFIG["exclude_dirs"]` patterns.
3. **QA stage** — runs in a loop up to `WORKFLOW_CONFIG["max_iterations"]` (default 3). When QA emits `challenges` (structured dicts with `target` ∈ PM/FE/BE), the orchestrator routes each challenge to the target agent's `respond_to_challenge` and records the response. `_check_consensus` is satisfied when every challenge has a matching response.
4. **Test generation** — `QAEngineerAgent.act_with_context` is called with the full challenge/response history; QA builds per-test-case `built_evidence_chain` and the orchestrator persists everything via `MemoryStorage` (SQLite at `data/memory.db`).

### Key contracts

- **Agent output shape** (`AgentOutput` in `src/agents/base_agent.py`): every agent returns `role`, `state`, `content`, `thinking`, `questions[]`, `error`. `has_questions()` is the orchestrator's signal to stop the workflow.
- **Agent message passing** (`AgentMessage` dataclass): typed messages between agents with `sender`, `receiver`, `content`, `message_type`, and `metadata`.
- **Evidence chain types** live in two places that must stay in sync: the `EVIDENCE_TYPES` dict in `src/config.py` and the `EvidenceType` enum in `src/agents/evidence_chain.py`. PRD Section 5.2.1 lists the canonical names: `REQ_RAW`, `REQ_STRUCT`, `BIZ_RULE`, `QA_PAIR`, `FE_PLAN`, `BE_PLAN`, `API_DEF`, `CODE_ANALYZE`, `MEMORY`, `KB`, `QA_REVIEW`, `USER_ANSWER`. Legacy aliases `FE_ANALYSIS` / `BE_ANALYSIS` are kept for compatibility.
- **LLM calls** are exclusively through `LLMAdapter.generate` / `generate_structured` (subprocess to `claude -p <prompt>` or `ollama run <model>`). `MockLLMAdapter` is the only way to exercise the pipeline offline; `MockOrchestrator` wires it into all four agents.
- **Memory** (`src/memory/storage.py`) is the only place that knows about SQLite. `MemoryStorage` exposes typed dataclasses (`MemoryUnit`, `QARecord`, `TestCaseRecord`); `vector_store.py` layers embeddings on top with a sentence-transformers → sklearn TF-IDF → hash fallback chain.
- **Knowledge modules** under `src/knowledge/` build the code index (`indexer.py`, `be_indexer.py`), drive system exploration (`explorer.py`, `document_processor.py`), and produce impact / defect analyses.

### Configuration surface

`src/config.py` is the single source of truth for:

- `LLM_CONFIG` — provider, model, `max_tokens`, `temperature`, `timeout`.
- `CLAUDE_CLI_CONFIG` — CLI command and `CLAUDE_API_KEY` env var.
- `DB_CONFIG` / `STORAGE_CONFIG` — paths under `data/`.
- `CODE_ANALYSIS_CONFIG` — supported languages, `max_file_size`, `exclude_dirs`, knowledge-base JSON paths.
- `AGENT_CONFIG` — per-agent `name` and `system_prompt`. These are loaded by `BaseAgent.__init__` and shipped to the LLM on every call; edit them here rather than hardcoding in agent files.
- `EVIDENCE_TYPES`, `WORKFLOW_CONFIG` (`stages`, `max_iterations`, `consensus_required`), `LOG_CONFIG`.

### Python API Usage

```python
from src.orchestrator.workflow import Orchestrator
from src.memory.storage import MemoryStorage

# Initialize
storage = MemoryStorage()  # Use ":memory:" for in-memory DB in tests
orchestrator = Orchestrator(memory_storage=storage)

# Run workflow
result = orchestrator.run("Your requirement here")

if result["status"] == "success":
    test_cases = result["test_cases"]
elif result["status"] == "needs_clarification":
    questions = result["questions"]
    # Provide answers via orchestrator.provide_clarification(answers)
```

### What to read first when changing behavior

- Adding / changing an agent → `src/agents/base_agent.py` (think/act contract), then the specific agent, then `AGENT_CONFIG` prompts in `src/config.py`.
- Changing the SOP or the challenge loop → `src/orchestrator/workflow.py` only; agents stay passive.
- Adding a new evidence type → add to `EVIDENCE_TYPES` + `EvidenceType` enum + the relevant agent's `_build_evidence_chain` (or QA's `_build_test_case_evidence_chains[_with_responses]`).
- Swapping the LLM backend → extend `LLMAdapter` in `src/adapters/llm_adapter.py`; mirror the contract in `MockLLMAdapter` so tests keep passing.
- Touching persistence → `src/memory/storage.py` (schema) and `src/memory/vector_store.py` (embeddings).
