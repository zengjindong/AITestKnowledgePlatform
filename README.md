# Multi-Agent AI Test Engineer System

A collaborative multi-agent system for generating high-quality test cases through PM, FE, BE, and QA agent collaboration with evidence chain tracking.

## Features

- **Multi-Agent Collaboration**: Four specialized agents (PM, FE, BE, QA) work together
- **Evidence Chain Tracking**: Every test case is traceable to its source requirements
- **Requirement Parsing**: Natural language requirements → structured documentation
- **Local-First**: Works with local LLM deployment (Claude CLI, Ollama)
- **Memory Persistence**: SQLite-based storage for business rules and test cases

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐   │
│  │   PM    │  │   FE    │  │   BE    │  │   QA    │   │
│  │ Agent   │  │ Agent   │  │ Agent   │  │ Agent   │   │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘   │
│       │            │            │            │         │
│       └────────────┴────────────┴────────────┘         │
│                          │                             │
│                    ┌─────┴─────┐                       │
│                    │  Memory   │                       │
│                    │ Storage   │                       │
│                    └───────────┘                       │
└─────────────────────────────────────────────────────────┘
```

## Agents

### Product Manager (PM)
- Parses natural language requirements
- Extracts business rules and user stories
- Identifies ambiguous requirements

### Frontend Engineer (FE)
- Analyzes affected UI components
- Identifies API dependencies
- Provides frontend testing focus

### Backend Engineer (BE)
- Analyzes API structures
- Identifies database changes
- Provides backend testing focus

### Quality Assurance (QA)
- Reviews all agent outputs
- Challenges assumptions
- Generates test cases with evidence chains

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### CLI

```bash
# Process a single requirement
python -m src --requirement "用户登录系统时，需要输入用户名和密码"

# Interactive mode
python -m src --interactive

# Demo mode
python -m src --demo

# Use mock agents (no LLM calls)
python -m src --mock --demo

# Show memory statistics
python -m src --stats
```

### Python API

```python
from src.orchestrator.workflow import Orchestrator
from src.memory.storage import MemoryStorage

# Initialize
storage = MemoryStorage()
orchestrator = Orchestrator(memory_storage=storage)

# Run workflow
result = orchestrator.run("Your requirement here")

if result["status"] == "success":
    test_cases = result["test_cases"]
    # Use test cases...
elif result["status"] == "needs_clarification":
    # Present questions to user
    questions = result["questions"]
```

## Evidence Chain

Each test case includes an evidence chain that traces every test step back to:

- `REQ_STRUCT`: Structured requirements from PM
- `BIZ_RULE`: Business rules from requirements or memory
- `API_DEF`: API definitions from BE analysis
- `CODE_ANALYZE`: Code analysis results
- `USER_ANSWER`: User clarification answers

## Workflow

1. **Requirement Input**: User provides natural language requirement
2. **PM Parsing**: PM extracts structured requirements
3. **Clarification** (if needed): System asks for missing details
4. **FE/BE Analysis**: Frontend and backend agents analyze
5. **QA Review**: QA challenges and reviews all outputs
6. **Test Generation**: QA generates test cases with evidence chains

## Configuration

Edit `src/config.py` to configure:

- LLM provider and model
- Agent system prompts
- Evidence chain types
- Workflow settings

## License

MIT