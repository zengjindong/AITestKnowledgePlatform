"""
Configuration for the Multi-Agent AI Test Engineer System.
"""
import os
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# LLM Configuration
LLM_CONFIG = {
    "provider": "claude",  # "claude" or "openai" or other
    "model": "claude-sonnet-4-20250514",  # Default model
    "max_tokens": 4096,
    "temperature": 0.7,
    "timeout": 120,  # seconds
}

# Claude CLI Configuration (for local deployment)
CLAUDE_CLI_CONFIG = {
    "command": "claude",  # CLI command
    "api_url": "http://localhost:8080",  # Local API endpoint
    "api_key": os.environ.get("CLAUDE_API_KEY", ""),
}

# Database Configuration
DB_CONFIG = {
    "type": "sqlite",
    "path": PROJECT_ROOT / "data" / "memory.db",
}

# Storage Configuration
STORAGE_CONFIG = {
    "type": "file",
    "base_path": PROJECT_ROOT / "data" / "storage",
    "document_path": PROJECT_ROOT / "data" / "documents",
    "snapshot_path": PROJECT_ROOT / "data" / "snapshots",
}

# Code Analysis Configuration
CODE_ANALYSIS_CONFIG = {
    "supported_languages": ["python", "javascript", "typescript", "java", "go", "rust"],
    "max_file_size": 1024 * 1024,  # 1MB
    "exclude_dirs": ["node_modules", ".venv", "__pycache__", ".git", "dist", "build"],
    "knowledge_base_path": str(Path(__file__).parent.parent / "data" / "frontend_knowledge_base.json"),
    "backend_knowledge_base_path": str(Path(__file__).parent.parent / "data" / "backend_knowledge_base.json"),
}

# Agent Configuration
AGENT_CONFIG = {
    "pm": {
        "name": "Product Manager",
        "role": "pm",
        "system_prompt": """You are a Product Manager (PM) Agent. Your responsibilities are:
1. Parse natural language requirements into structured documentation
2. Identify business rules and extract user stories
3. Define acceptance criteria
4. If requirements are ambiguous, you MUST output clarification questions

When you encounter unclear information, you MUST ask questions instead of guessing.
Always output valid JSON that conforms to the defined schemas.""",
    },
    "fe": {
        "name": "Frontend Engineer",
        "role": "fe",
        "system_prompt": """You are a Frontend Engineer (FE) Agent. Your responsibilities are:
1. Analyze UI/UX logic based on requirements
2. Identify affected frontend components
3. Determine API dependencies
4. Provide frontend testing focus areas

Analyze the local codebase to find relevant components. Always reference actual code.""",
    },
    "be": {
        "name": "Backend Engineer",
        "role": "be",
        "system_prompt": """You are a Backend Engineer (BE) Agent. Your responsibilities are:
1. Design/modify API interfaces (OpenAPI/Swagger format)
2. Evaluate database changes needed
3. Analyze business logic implementation
4. Provide backend testing focus areas

Analyze the local codebase to find relevant APIs and logic. Always reference actual code.""",
    },
    "qa": {
        "name": "Quality Assurance Engineer",
        "role": "qa",
        "system_prompt": """You are a Quality Assurance (QA) Engineer Agent. Your responsibilities are:
1. Review requirements and technical solutions from PM/FE/BE
2. Challenge assumptions and request clarifications
3. Generate test cases with evidence chains
4. Ensure quality gates are met

As the "Quality Gatekeeper", you must ensure ALL test cases have evidence chain support.
Do NOT generate test steps without proper evidence. Ask questions when information is missing.""",
    },
}

# Evidence Chain Types (Section 5.2.1 from PRD)
EVIDENCE_TYPES = {
    # Requirement evidence
    "REQ_RAW": "Raw requirement from user input",
    "REQ_STRUCT": "Structured requirement from PM Agent",
    # Business knowledge
    "BIZ_RULE": "Business rule from PM or memory",
    "QA_PAIR": "Question & Answer clarification pair",
    # Agent outputs
    "FE_PLAN": "Frontend implementation plan from FE Agent",
    "BE_PLAN": "Backend implementation plan from BE Agent",
    "API_DEF": "API definition from BE Agent (Swagger/OpenAPI)",
    "CODE_ANALYZE": "Code analysis result from FE/BE Agent",
    # Memory & Knowledge
    "MEMORY": "Retrieved from long-term memory",
    "KB": "Retrieved from knowledge base",
    # QA outputs
    "QA_REVIEW": "QA Agent review comments and confirmations",
    # User interactions
    "USER_ANSWER": "User clarification answer",
    # Legacy types for compatibility
    "FE_ANALYSIS": "Frontend analysis result",
    "BE_ANALYSIS": "Backend analysis result",
}

# SOP Workflow Configuration
WORKFLOW_CONFIG = {
    "stages": ["pm", "fe_be", "qa"],
    "max_iterations": 3,  # Max back-and-forth iterations per stage
    "consensus_required": True,
}

# Logging Configuration
LOG_CONFIG = {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "file": PROJECT_ROOT / "logs" / "system.log",
}