"""
Frontend Knowledge Base for FE Agent.

Loads the pre-built knowledge base and provides search capabilities
for the FE agent to find relevant components and APIs.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FrontendKnowledgeBase:
    """
    Knowledge base for frontend code.

    Provides methods to search for components, APIs, and understand
    the codebase structure.
    """

    def __init__(self, kb_path: str = None):
        """
        Initialize the knowledge base.

        Args:
            kb_path: Path to the knowledge base JSON file
        """
        self.kb_path = kb_path or "data/frontend_knowledge_base.json"
        self.data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load knowledge base from file."""
        try:
            kb_file = Path(self.kb_path)
            if kb_file.exists():
                with open(kb_file, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                logger.info(f"Loaded knowledge base with {self.data.get('total_components', 0)} components")
            else:
                logger.warning(f"Knowledge base not found at {self.kb_path}")
        except Exception as e:
            logger.error(f"Error loading knowledge base: {e}")

    def search_components(
        self,
        query: str,
        project: str = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search components by name, props, or imports.

        Args:
            query: Search query
            project: Optional project filter
            limit: Maximum results

        Returns:
            List of matching components
        """
        if not self.data.get("projects"):
            return []

        query_lower = query.lower()
        results = []

        projects = (
            {project: self.data["projects"][project]}
            if project and project in self.data["projects"]
            else self.data["projects"]
        )

        for proj_name, proj_data in projects.items():
            for component in proj_data.get("components", []):
                score = 0
                matched_fields = []

                # Name match (highest priority)
                if query_lower in component.get("name", "").lower():
                    score += 10
                    matched_fields.append("name")

                # Props match
                for prop in component.get("props", []):
                    if query_lower in prop.lower():
                        score += 5
                        matched_fields.append("props")

                # Imports match
                for imp in component.get("imports", []):
                    if query_lower in imp.lower():
                        score += 3
                        matched_fields.append("imports")

                if score > 0:
                    results.append({
                        "component": component,
                        "project": proj_name,
                        "score": score,
                        "matched_fields": list(set(matched_fields))
                    })

        # Sort by score
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def find_components_by_entity(
        self,
        entity_name: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Find components related to an entity (e.g., 'user', 'order', 'login').

        Args:
            entity_name: The entity name to search for
            limit: Maximum results

        Returns:
            List of related components
        """
        # Search in component names and their context
        return self.search_components(entity_name, limit=limit)

    def get_component_details(
        self,
        component_name: str,
        project: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific component.

        Args:
            component_name: Name of the component
            project: Optional project filter

        Returns:
            Component details or None
        """
        results = self.search_components(component_name, project=project, limit=1)
        if results and results[0]["component"]["name"].lower() == component_name.lower():
            return results[0]
        return None

    def get_api_dependencies(
        self,
        component_name: str,
        project: str = None
    ) -> List[str]:
        """
        Get API dependencies for a component.

        Args:
            component_name: Name of the component
            project: Optional project filter

        Returns:
            List of API endpoints used by the component
        """
        details = self.get_component_details(component_name, project)
        if details:
            return details["component"].get("api_calls", [])
        return []

    def get_components_by_api(
        self,
        api_pattern: str
    ) -> List[Dict[str, Any]]:
        """
        Find components that use a specific API pattern.

        Args:
            api_pattern: API pattern to search for

        Returns:
            List of components using this API
        """
        results = []
        api_lower = api_pattern.lower()

        for proj_name, proj_data in self.data.get("projects", {}).items():
            for component in proj_data.get("components", []):
                for api_call in component.get("api_calls", []):
                    if api_lower in api_call.lower():
                        results.append({
                            "component": component,
                            "project": proj_name,
                            "api_call": api_call
                        })

        return results

    def get_project_summary(self, project: str = None) -> Dict[str, Any]:
        """
        Get summary of a project or all projects.

        Args:
            project: Optional project name

        Returns:
            Project summary
        """
        if project:
            return self.data.get("projects", {}).get(project, {})
        else:
            return {
                "projects": list(self.data.get("projects", {}).keys()),
                "total_components": self.data.get("total_components", 0),
                "total_apis": self.data.get("total_apis", 0)
            }

    def get_all_components(self, project: str = None) -> List[Dict[str, Any]]:
        """
        Get all components, optionally filtered by project.

        Args:
            project: Optional project filter

        Returns:
            List of all components
        """
        results = []
        projects = (
            {project: self.data["projects"][project]}
            if project
            else self.data.get("projects", {})
        )

        for proj_name, proj_data in projects.items():
            for component in proj_data.get("components", []):
                results.append({
                    "component": component,
                    "project": proj_name
                })

        return results


# Singleton instance
_kb_instance: Optional[FrontendKnowledgeBase] = None


def get_knowledge_base(kb_path: str = None) -> FrontendKnowledgeBase:
    """Get singleton knowledge base instance."""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = FrontendKnowledgeBase(kb_path)
    return _kb_instance