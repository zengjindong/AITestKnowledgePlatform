"""
Backend Engineer (BE) Agent for API and backend logic analysis.

This agent is responsible for:
- Designing/modifying API interfaces
- Evaluating database changes
- Analyzing business logic implementation
- Providing backend testing focus areas
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent, AgentRole, AgentOutput, AgentState
from src.agents.evidence_chain import EvidenceChain, EvidenceChainBuilder
from src.config import CODE_ANALYSIS_CONFIG
from src.knowledge.be_knowledge import BackendKnowledgeBase, get_backend_knowledge_base

logger = logging.getLogger(__name__)


class BEAnalysisResult:
    """Result of backend analysis."""

    def __init__(self):
        self.api_definitions: List[Dict[str, Any]] = []
        self.database_changes: List[Dict[str, str]] = []
        self.business_logic_files: List[str] = []
        self.testing_focus_areas: List[str] = []
        self.code_references: Dict[str, str] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "api_definitions": self.api_definitions,
            "database_changes": self.database_changes,
            "business_logic_files": self.business_logic_files,
            "testing_focus_areas": self.testing_focus_areas,
            "code_references": self.code_references
        }


class BackendEngineerAgent(BaseAgent):
    """
    Backend Engineer Agent responsible for backend analysis.

    This agent analyzes the backend codebase to understand API
    structures, database schemas, and business logic.
    """

    def __init__(
        self,
        llm_adapter=None,
        config: Dict[str, Any] = None,
        codebase_path: Optional[str] = None,
        knowledge_base_path: Optional[str] = None
    ):
        super().__init__(role=AgentRole.BE, llm_adapter=llm_adapter, config=config)
        self.codebase_path = codebase_path or (config.get("codebase_path", ".") if config else ".")
        self.knowledge_base_path = knowledge_base_path or config.get("backend_knowledge_base_path") if config else None
        self.analysis_result: Optional[BEAnalysisResult] = None
        self._kb: Optional[BackendKnowledgeBase] = None

    @property
    def knowledge_base(self) -> BackendKnowledgeBase:
        """Get or create knowledge base instance."""
        if self._kb is None:
            self._kb = get_backend_knowledge_base(self.knowledge_base_path)
        return self._kb

    def _find_api_files(self, requirement: Dict[str, Any]) -> List[str]:
        """
        Find backend files that might contain API endpoints.

        Args:
            requirement: Parsed requirement from PM

        Returns:
            List of file paths
        """
        # Try knowledge base first
        kb_results = self._search_knowledge_base(requirement)
        if kb_results:
            logger.info(f"Found {len(kb_results)} APIs via knowledge base")
            return [r["api"]["file_path"] for r in kb_results]

        # Fallback to filesystem scan
        api_files = []
        exclude_dirs = CODE_ANALYSIS_CONFIG.get("exclude_dirs", [])

        # Search for API patterns in common backend file locations
        search_dirs = ["api", "routes", "endpoints", "controllers", "services", "handlers"]

        for search_dir in search_dirs:
            dir_path = Path(self.codebase_path) / search_dir
            if dir_path.exists():
                for ext in ["*.py", "*.js", "*.ts", "*.go", "*.java"]:
                    api_files.extend(dir_path.glob(ext))

        # Also look for route definitions in main app files
        for pattern in ["*route*", "*api*", "*app*"]:
            for ext in ["*.py", "*.js", "*.ts"]:
                api_files.extend(Path(self.codebase_path).glob(f"{pattern}.{ext}"))

        return [str(f) for f in api_files]

    def _search_knowledge_base(self, requirement: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Search knowledge base for relevant APIs.

        Args:
            requirement: Parsed requirement from PM

        Returns:
            List of matching APIs with metadata
        """
        try:
            # Extract search terms
            search_terms = []

            if requirement.get("title"):
                search_terms.append(requirement["title"])
            if requirement.get("description"):
                search_terms.append(requirement["description"])

            for entity in requirement.get("entities", []):
                search_terms.append(entity.get("name", ""))

            for us in requirement.get("user_stories", []):
                search_terms.extend([us.get("as_a", ""), us.get("i_want", ""), us.get("so_that", "")])

            # Search each term
            all_results = []
            seen = set()

            for term in search_terms:
                if not term:
                    continue
                results = self.knowledge_base.search_apis(term, limit=10)
                for r in results:
                    key = r["api"]["file_path"]
                    if key not in seen:
                        seen.add(key)
                        all_results.append(r)

            all_results.sort(key=lambda x: x["score"], reverse=True)
            return all_results[:20]

        except Exception as e:
            logger.warning(f"Backend knowledge base search failed: {e}")
            return []

    def _analyze_api_file(self, file_path: str) -> Dict[str, Any]:
        """
        Analyze a backend file for API definitions.

        Args:
            file_path: Path to the file

        Returns:
            Analysis result
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Look for common API patterns
            endpoints = []

            # Python Flask/FastAPI patterns
            if "@app.route" in content or "@router" in content:
                routes = re.findall(r'@(?:app|router)\.route\(["\']([^"\']+)["\']\)\s*(?:def\s+(\w+))?', content)
                for path, func_name in routes:
                    methods = re.findall(r'@(?:app|router)\.route\(["\'][^"\']+["\']\).*?\n\s*def\s+(\w+)\(', content)
                    endpoints.append({
                        "path": path,
                        "function": func_name or "anonymous",
                        "file": file_path
                    })

            # Node.js Express patterns
            if "express" in content.lower() or "router." in content:
                routes = re.findall(r'(?:app|router)\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']', content)
                for method, path in routes:
                    endpoints.append({
                        "path": path,
                        "method": method.upper(),
                        "file": file_path
                    })

            # Look for database models
            db_operations = []
            if "CREATE TABLE" in content.upper() or "CREATE TABLE" in content:
                db_operations.append("DDL found")
            if re.search(r'SELECT|INSERT|UPDATE|DELETE', content, re.IGNORECASE):
                db_operations.append("DML found")

            return {
                "file": file_path,
                "endpoints": endpoints,
                "db_operations": db_operations
            }
        except Exception as e:
            logger.warning(f"Could not analyze {file_path}: {e}")
            return {"file": file_path, "error": str(e)}

    def _think_impl(self, input_data: Any) -> Dict[str, Any]:
        """
        Analyze requirements and plan backend analysis.

        Args:
            input_data: Parsed requirements from PM

        Returns:
            Analysis plan
        """
        thoughts = {
            "input_type": type(input_data).__name__,
            "action_plan": ["analyze_backend"],
            "apis_to_find": [],
            "db_changes_needed": [],
            "testing_considerations": []
        }

        if isinstance(input_data, dict):
            thoughts["requirement_id"] = input_data.get("requirement_id", "unknown")
            thoughts["business_rules"] = input_data.get("business_rules", [])

        return thoughts

    def act(self, input_data: Any) -> AgentOutput:
        """
        Analyze backend codebase and generate technical output.

        Args:
            input_data: Parsed requirements from PM

        Returns:
            AgentOutput with backend analysis
        """
        self.state = AgentState.ACTING
        self.output = AgentOutput(role=self.role, state=AgentState.ACTING)
        self.analysis_result = BEAnalysisResult()

        try:
            thoughts = self._think_impl(input_data)

            # Find API files (from knowledge base or filesystem)
            kb_results = []
            if isinstance(input_data, dict):
                kb_results = self._search_knowledge_base(input_data)

            api_files = self._find_api_files(input_data if isinstance(input_data, dict) else {})

            # Process knowledge base results
            for kb_result in kb_results:
                api = kb_result["api"]
                self.analysis_result.api_definitions.append({
                    "path": api.get("path", ""),
                    "method": api.get("method", ""),
                    "class_name": api.get("class_name", ""),
                    "method_name": api.get("method_name", ""),
                    "parameters": api.get("parameters", []),
                    "request_body": api.get("request_body"),
                    "response_type": api.get("response_type"),
                    "file_path": api.get("file_path", ""),
                    "match_score": kb_result.get("score", 0)
                })
                file_path = api.get("file_path", "")
                if file_path:
                    self.analysis_result.business_logic_files.append(file_path)
                    self.analysis_result.code_references[file_path] = file_path

            # Also analyze files from filesystem not in KB
            for file_path in api_files:
                if not any(file_path == kb_result["api"].get("file_path") for kb_result in kb_results):
                    analysis = self._analyze_api_file(file_path)
                    if "error" not in analysis:
                        self.analysis_result.business_logic_files.append(file_path)
                        self.analysis_result.code_references[file_path] = file_path

                        for endpoint in analysis.get("endpoints", []):
                            self.analysis_result.api_definitions.append(endpoint)

            # Use LLM to enhance analysis
            user_message = self._format_for_analysis(input_data, thoughts)
            response = self.llm_adapter.generate_structured(
                system_prompt=self._get_analysis_prompt(),
                user_message=user_message
            )

            if response:
                self.analysis_result.api_definitions.extend(response.get("api_definitions", []))
                self.analysis_result.database_changes = response.get("database_changes", [])
                self.analysis_result.testing_focus_areas = response.get("testing_focus_areas", [])

            # Build evidence chain
            self._build_evidence_chain(input_data, thoughts)

            self.output.content = self.analysis_result.to_dict()
            self.output.state = AgentState.DONE

        except Exception as e:
            logger.error(f"BE Agent error: {e}")
            self.output.error = str(e)
            self.output.state = AgentState.ERROR

        return self.output

    def _get_analysis_prompt(self) -> str:
        return """Analyze the backend requirements and identify:

1. API Definitions: What APIs need to be created or modified?
   Format: {endpoint, method, purpose, request_schema, response_schema}
2. Database Changes: What database schema changes are needed?
3. Testing Focus Areas: What should QA focus on testing in the backend?

Provide your analysis in JSON format:
{
    "api_definitions": [
        {
            "endpoint": "/api/example",
            "method": "POST",
            "purpose": "description",
            "request_schema": {"field": "type"},
            "response_schema": {"field": "type"}
        }
    ],
    "database_changes": [
        {
            "table": "users",
            "change": "ADD COLUMN phone VARCHAR(20)",
            "purpose": "Store user phone number"
        }
    ],
    "testing_focus_areas": [
        "API validation logic",
        "Database transaction handling",
        "Error response formats"
    ]
}"""

    def _format_for_analysis(self, input_data: Any, thoughts: Dict[str, Any]) -> str:
        """Format input for LLM analysis."""
        # Include knowledge base context
        kb_context = {
            "total_apis_found": len(self.analysis_result.api_definitions),
            "apis_from_kb": [
                {
                    "path": a.get("path", ""),
                    "method": a.get("method", ""),
                    "class_name": a.get("class_name", ""),
                    "method_name": a.get("method_name", ""),
                    "request_body": a.get("request_body"),
                    "response_type": a.get("response_type")
                }
                for a in self.analysis_result.api_definitions
                if a.get("match_score")  # From KB has match_score
            ]
        }

        return json.dumps({
            "requirement": input_data if isinstance(input_data, dict) else {"raw": str(input_data)},
            "existing_apis": self.analysis_result.api_definitions,
            "business_rules": thoughts.get("business_rules", []),
            "knowledge_base_context": kb_context
        }, ensure_ascii=False, indent=2)

    def _build_evidence_chain(self, requirement: Any, thoughts: Dict[str, Any]) -> None:
        """Build evidence chain for backend analysis."""
        builder = EvidenceChainBuilder(f"be_{thoughts.get('requirement_id', 'unknown')}")

        # Add API definitions
        for api in self.analysis_result.api_definitions:
            path = api.get("path", api.get("endpoint", ""))
            builder.add_api(
                ref_id=f"{api.get('method', 'GET')}_{path}",
                content=f"{api.get('method', 'GET')} {path} - Class: {api.get('class_name', 'N/A')} Method: {api.get('method_name', 'N/A')}"
            )

        # Add database changes
        for db_change in self.analysis_result.database_changes:
            builder.add_code_analysis(
                ref_id=db_change.get("table", "unknown_table"),
                content=f"Table: {db_change.get('table', '')}\nChange: {db_change.get('change', '')}\nPurpose: {db_change.get('purpose', '')}"
            )

        # Add code references
        for file_path in self.analysis_result.business_logic_files:
            builder.add_code_analysis(
                ref_id=file_path,
                content=f"Backend file: {file_path}",
                source=file_path
            )

        self.output.evidence_chain = builder.build()

    def get_analysis_result(self) -> Optional[BEAnalysisResult]:
        """Get the analysis result."""
        return self.analysis_result