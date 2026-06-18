"""
Frontend Engineer (FE) Agent for UI/UX and frontend component analysis.

This agent is responsible for:
- Analyzing UI/UX logic based on requirements
- Identifying affected frontend components
- Determining API dependencies
- Providing frontend testing focus areas
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent, AgentRole, AgentOutput, AgentState
from src.agents.evidence_chain import EvidenceChain, EvidenceChainBuilder
from src.config import CODE_ANALYSIS_CONFIG
from src.knowledge.fe_knowledge import FrontendKnowledgeBase, get_knowledge_base

logger = logging.getLogger(__name__)


class FEAnalysisResult:
    """Result of frontend analysis."""

    def __init__(self):
        self.affected_components: List[Dict[str, Any]] = []
        self.api_dependencies: List[Dict[str, str]] = []
        self.testing_focus_areas: List[str] = []
        self.technical_considerations: List[str] = []
        self.code_references: Dict[str, str] = {}  # ref_id -> file_path

    def to_dict(self) -> Dict[str, Any]:
        return {
            "affected_components": self.affected_components,
            "api_dependencies": self.api_dependencies,
            "testing_focus_areas": self.testing_focus_areas,
            "technical_considerations": self.technical_considerations,
            "code_references": self.code_references
        }


class FrontendEngineerAgent(BaseAgent):
    """
    Frontend Engineer Agent responsible for frontend analysis.

    This agent analyzes the frontend codebase to understand how
    requirements affect UI components and user interactions.
    """

    def __init__(
        self,
        llm_adapter=None,
        config: Dict[str, Any] = None,
        codebase_path: Optional[str] = None,
        knowledge_base_path: Optional[str] = None
    ):
        super().__init__(role=AgentRole.FE, llm_adapter=llm_adapter, config=config)
        self.codebase_path = codebase_path or (config.get("codebase_path", ".") if config else ".")
        self.knowledge_base_path = knowledge_base_path or config.get("knowledge_base_path") if config else None
        self.analysis_result: Optional[FEAnalysisResult] = None
        self._kb: Optional[FrontendKnowledgeBase] = None

    @property
    def knowledge_base(self) -> FrontendKnowledgeBase:
        """Get or create knowledge base instance."""
        if self._kb is None:
            self._kb = get_knowledge_base(self.knowledge_base_path)
        return self._kb

    def _find_affected_files(self, requirement: Dict[str, Any]) -> List[str]:
        """
        Find frontend files that might be affected by the requirement.

        Args:
            requirement: Parsed requirement from PM

        Returns:
            List of file paths
        """
        # Try knowledge base first
        kb_results = self._search_knowledge_base(requirement)
        if kb_results:
            logger.info(f"Found {len(kb_results)} components via knowledge base")
            return [r["component"]["file_path"] for r in kb_results]

        # Fallback to filesystem scan
        affected = []
        exclude_dirs = CODE_ANALYSIS_CONFIG.get("exclude_dirs", [])

        # Search for common frontend file patterns
        patterns = ["*.tsx", "*.ts", "*.jsx", "*.js", "*.vue", "*.svelte"]

        for pattern in patterns:
            for exclude in exclude_dirs:
                # Skip excluded directories
                pass

        # Look for components mentioned in requirements
        entities = requirement.get("entities", [])
        for entity in entities:
            entity_name = entity.get("name", "").lower()
            # Search for matching component files
            for ext in ["tsx", "jsx", "js", "vue"]:
                potential_path = Path(self.codebase_path) / f"{entity_name}.{ext}"
                if potential_path.exists():
                    affected.append(str(potential_path))

        logger.info(f"Found {len(affected)} potentially affected frontend files")
        return affected

    def _search_knowledge_base(self, requirement: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Search knowledge base for relevant components.

        Args:
            requirement: Parsed requirement from PM

        Returns:
            List of matching components with metadata
        """
        try:
            # Extract search terms from requirement
            search_terms = []

            # From title/description
            if requirement.get("title"):
                search_terms.append(requirement["title"])
            if requirement.get("description"):
                search_terms.append(requirement["description"])

            # From entities
            for entity in requirement.get("entities", []):
                search_terms.append(entity.get("name", ""))

            # From user stories
            for us in requirement.get("user_stories", []):
                search_terms.extend([us.get("as_a", ""), us.get("i_want", ""), us.get("so_that", "")])

            # Search each term
            all_results = []
            seen = set()

            for term in search_terms:
                if not term:
                    continue
                results = self.knowledge_base.search_components(term, limit=10)
                for r in results:
                    key = r["component"]["file_path"]
                    if key not in seen:
                        seen.add(key)
                        all_results.append(r)

            # Sort by score and return top results
            all_results.sort(key=lambda x: x["score"], reverse=True)
            return all_results[:20]

        except Exception as e:
            logger.warning(f"Knowledge base search failed: {e}")
            return []

    def _analyze_component(self, file_path: str) -> Dict[str, Any]:
        """
        Analyze a single frontend component.

        Args:
            file_path: Path to the component file

        Returns:
            Analysis result for the component
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Basic analysis - look for API calls, state management, etc.
            api_calls = []
            state_hooks = []

            # Simple pattern matching for common patterns
            if "useState" in content or "useReducer" in content:
                state_hooks.append("useState or useReducer detected")
            if "useEffect" in content:
                state_hooks.append("useEffect detected")
            if "fetch(" in content or "axios" in content or "http" in content.lower():
                api_calls.append("API call detected")

            return {
                "file": file_path,
                "has_state": len(state_hooks) > 0,
                "has_api_calls": len(api_calls) > 0,
                "patterns_found": state_hooks + api_calls
            }
        except Exception as e:
            logger.warning(f"Could not analyze {file_path}: {e}")
            return {"file": file_path, "error": str(e)}

    def _think_impl(self, input_data: Any) -> Dict[str, Any]:
        """
        Analyze requirements and plan frontend analysis.

        Args:
            input_data: Parsed requirements from PM

        Returns:
            Analysis plan
        """
        thoughts = {
            "input_type": type(input_data).__name__,
            "action_plan": ["analyze_frontend"],
            "entities_to_find": [],
            "api_dependencies_identified": [],
            "testing_considerations": []
        }

        if isinstance(input_data, dict):
            thoughts["requirement_id"] = input_data.get("requirement_id", "unknown")
            thoughts["entities_to_find"] = [
                e.get("name", "") for e in input_data.get("entities", [])
            ]
            thoughts["user_stories"] = input_data.get("user_stories", [])

        return thoughts

    def act(self, input_data: Any) -> AgentOutput:
        """
        Analyze frontend codebase and generate technical output.

        Args:
            input_data: Parsed requirements from PM

        Returns:
            AgentOutput with frontend analysis
        """
        self.state = AgentState.ACTING
        self.output = AgentOutput(role=self.role, state=AgentState.ACTING)
        self.analysis_result = FEAnalysisResult()

        try:
            thoughts = self._think_impl(input_data)

            # Find affected files (from knowledge base or filesystem)
            kb_results = []
            if isinstance(input_data, dict):
                kb_results = self._search_knowledge_base(input_data)

            affected_files = self._find_affected_files(input_data if isinstance(input_data, dict) else {})

            # Analyze each file and combine with KB results
            for kb_result in kb_results:
                component = kb_result["component"]
                self.analysis_result.affected_components.append({
                    "name": component.get("name"),
                    "file": component.get("file_path"),
                    "type": component.get("type"),
                    "props": component.get("props", []),
                    "imports": component.get("imports", []),
                    "api_calls": component.get("api_calls", []),
                    "project": kb_result.get("project"),
                    "match_score": kb_result.get("score", 0),
                    "match_fields": kb_result.get("matched_fields", [])
                })
                self.analysis_result.code_references[component.get("file_path", "")] = component.get("file_path", "")

            # Also analyze files from filesystem that might not be in KB
            for file_path in affected_files:
                if not any(file_path == kb_result["component"].get("file_path") for kb_result in kb_results):
                    analysis = self._analyze_component(file_path)
                    if "error" not in analysis:
                        self.analysis_result.affected_components.append(analysis)
                        self.analysis_result.code_references[file_path] = file_path

            # Use LLM to enhance analysis
            user_message = self._format_for_analysis(input_data, thoughts)
            response = self.llm_adapter.generate_structured(
                system_prompt=self._get_analysis_prompt(),
                user_message=user_message
            )

            if response:
                self.analysis_result.api_dependencies = response.get("api_dependencies", [])
                self.analysis_result.testing_focus_areas = response.get("testing_focus_areas", [])
                self.analysis_result.technical_considerations = response.get("technical_considerations", [])

            # Build evidence chain
            self._build_evidence_chain(input_data, thoughts)

            self.output.content = self.analysis_result.to_dict()
            self.output.state = AgentState.DONE

        except Exception as e:
            logger.error(f"FE Agent error: {e}")
            self.output.error = str(e)
            self.output.state = AgentState.ERROR

        return self.output

    def _get_analysis_prompt(self) -> str:
        return """Analyze the frontend requirements and identify:

1. API Dependencies: What APIs does the frontend need to call?
2. Testing Focus Areas: What should QA focus on testing in the frontend?
3. Technical Considerations: Any special frontend considerations

Provide your analysis in JSON format:
{
    "api_dependencies": [
        {
            "endpoint": "/api/example",
            "method": "POST",
            "purpose": "description"
        }
    ],
    "testing_focus_areas": [
        "UI validation logic",
        "Error handling for API failures"
    ],
    "technical_considerations": [
        "Need to handle loading states",
        "Form validation required"
    ]
}"""

    def _format_for_analysis(self, input_data: Any, thoughts: Dict[str, Any]) -> str:
        """Format input for LLM analysis."""
        # Include knowledge base context if available
        kb_context = {
            "total_components_found": len(self.analysis_result.affected_components),
            "components_from_kb": [
                {
                    "name": c.get("name", ""),
                    "type": c.get("type", ""),
                    "props": c.get("props", [])[:10],  # Limit props
                    "imports": c.get("imports", [])[:10],  # Limit imports
                    "project": c.get("project", "")
                }
                for c in self.analysis_result.affected_components
                if c.get("project")  # From KB has project field
            ]
        }

        return json.dumps({
            "requirement": input_data if isinstance(input_data, dict) else {"raw": str(input_data)},
            "affected_components": [c.get("file", c.get("name", "")) for c in self.analysis_result.affected_components],
            "entities": thoughts.get("entities_to_find", []),
            "knowledge_base_context": kb_context
        }, ensure_ascii=False, indent=2)

    def _build_evidence_chain(self, requirement: Any, thoughts: Dict[str, Any]) -> None:
        """Build evidence chain for frontend analysis."""
        builder = EvidenceChainBuilder(f"fe_{thoughts.get('requirement_id', 'unknown')}")

        # Add component references
        for component in self.analysis_result.affected_components:
            file_path = component.get("file", component.get("file_path", ""))
            component_name = component.get("name", file_path)

            builder.add_code_analysis(
                ref_id=file_path or component_name,
                content=f"Component: {component_name}\nType: {component.get('type', 'unknown')}\nProps: {component.get('props', [])}\nProject: {component.get('project', 'N/A')}",
                source=file_path
            )

        # Add API dependencies
        for api in self.analysis_result.api_dependencies:
            builder.add_api(
                ref_id=api.get("endpoint", "unknown"),
                content=f"{api.get('method', 'GET')} {api.get('endpoint', '')} - {api.get('purpose', '')}"
            )

        self.output.evidence_chain = builder.build()

    def get_analysis_result(self) -> Optional[FEAnalysisResult]:
        """Get the analysis result."""
        return self.analysis_result