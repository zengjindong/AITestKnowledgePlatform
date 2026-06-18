# Multi-Agent AI Test Engineer System

A collaborative multi-agent system for generating high-quality test cases through PM, FE, BE, and QA agent collaboration with evidence chain tracking.

## Quick Start

```bash
# Run with mock agents (no LLM setup required)
python -m src --mock --demo
```

## Project Structure

```
src/
├── __init__.py           # Package init
├── __main__.py           # Entry point
├── config.py             # Configuration
├── cli.py                # CLI interface
├── adapters/
│   ├── __init__.py
│   └── llm_adapter.py    # LLM integration
├── agents/
│   ├── __init__.py
│   ├── base_agent.py     # Base Agent class
│   ├── evidence_chain.py # Evidence chain tracking
│   ├── pm_agent.py       # Product Manager
│   ├── fe_agent.py       # Frontend Engineer
│   ├── be_agent.py       # Backend Engineer
│   └── qa_agent.py       # QA Engineer
├── memory/
│   ├── __init__.py
│   └── storage.py        # SQLite storage
└── orchestrator/
    ├── __init__.py
    └── workflow.py       # Workflow coordinator
```