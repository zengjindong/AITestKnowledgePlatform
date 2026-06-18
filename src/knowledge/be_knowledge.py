"""
Backend Knowledge Base for BE Agent.

Loads the pre-built knowledge base and provides search capabilities
for the BE agent to find relevant APIs, services, and entities.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BackendKnowledgeBase:
    """
    Knowledge base for backend code.

    Provides methods to search for APIs, services, entities, and understand
    the backend codebase structure.
    """

    def __init__(self, kb_path: str = None):
        """
        Initialize the knowledge base.

        Args:
            kb_path: Path to the knowledge base JSON file
        """
        self.kb_path = kb_path or "data/backend_knowledge_base.json"
        self.data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load knowledge base from file."""
        try:
            kb_file = Path(self.kb_path)
            if kb_file.exists():
                with open(kb_file, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                logger.info(f"Loaded backend knowledge base with {len(self.data.get('apis', []))} APIs, {len(self.data.get('services', []))} services")
            else:
                logger.warning(f"Backend knowledge base not found at {self.kb_path}")
        except Exception as e:
            logger.error(f"Error loading backend knowledge base: {e}")

    def search_apis(
        self,
        query: str,
        method: str = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search APIs by path, class name, or method name.

        Args:
            query: Search query
            method: Optional HTTP method filter (GET, POST, etc.)
            limit: Maximum results

        Returns:
            List of matching APIs
        """
        results = []
        query_lower = query.lower()

        # Search Java/Spring APIs
        for api in self.data.get("apis", []):
            score = 0
            matched_fields = []

            # Path match
            if query_lower in api.get("path", "").lower():
                score += 10
                matched_fields.append("path")

            # Class name match
            if query_lower in api.get("class_name", "").lower():
                score += 5
                matched_fields.append("class_name")

            # Method name match
            if query_lower in api.get("method_name", "").lower():
                score += 5
                matched_fields.append("method_name")

            # HTTP method filter
            if method and api.get("method", "").upper() != method.upper():
                continue

            if score > 0:
                results.append({
                    "api": api,
                    "score": score,
                    "matched_fields": list(set(matched_fields)),
                    "language": "java"
                })

        # Search Python APIs (FastAPI/Flask)
        for api in self.data.get("python_apis", []):
            score = 0
            matched_fields = []

            # Path match
            if query_lower in api.get("path", "").lower():
                score += 10
                matched_fields.append("path")

            # Function name match
            if query_lower in api.get("function_name", "").lower():
                score += 5
                matched_fields.append("function_name")

            # HTTP method filter
            if method and api.get("method", "").upper() != method.upper():
                continue

            if score > 0:
                results.append({
                    "api": api,
                    "score": score,
                    "matched_fields": list(set(matched_fields)),
                    "language": "python"
                })

        # Search Go APIs
        for api in self.data.get("go_apis", []):
            score = 0
            matched_fields = []

            # Path match
            if query_lower in api.get("path", "").lower():
                score += 10
                matched_fields.append("path")

            # Handler name match
            if query_lower in api.get("handler_name", "").lower():
                score += 5
                matched_fields.append("handler_name")

            # HTTP method filter
            if method and api.get("method", "").upper() != method.upper():
                continue

            if score > 0:
                results.append({
                    "api": api,
                    "score": score,
                    "matched_fields": list(set(matched_fields)),
                    "language": "go"
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def search_services(
        self,
        query: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search services by name or methods.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching services
        """
        results = []
        query_lower = query.lower()

        for service in self.data.get("services", []):
            score = 0
            matched_fields = []

            # Name match
            if query_lower in service.get("name", "").lower():
                score += 10
                matched_fields.append("name")

            # Method match
            for method in service.get("methods", []):
                if query_lower in method.lower():
                    score += 3
                    matched_fields.append("method")

            # Dependency match
            for dep in service.get("dependencies", []):
                if query_lower in dep.lower():
                    score += 2
                    matched_fields.append("dependency")

            if score > 0:
                results.append({
                    "service": service,
                    "score": score,
                    "matched_fields": list(set(matched_fields))
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def search_entities(
        self,
        query: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search entities by name or table name.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching entities
        """
        results = []
        query_lower = query.lower()

        for entity in self.data.get("entities", []):
            score = 0
            matched_fields = []

            # Name match
            if query_lower in entity.get("name", "").lower():
                score += 10
                matched_fields.append("name")

            # Table name match
            if query_lower in entity.get("table_name", "").lower():
                score += 5
                matched_fields.append("table_name")

            # Field match
            for field in entity.get("fields", []):
                if query_lower in field.get("name", "").lower():
                    score += 3
                    matched_fields.append("field")

            if score > 0:
                results.append({
                    "entity": entity,
                    "score": score,
                    "matched_fields": list(set(matched_fields))
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def get_apis_by_entity(
        self,
        entity_name: str
    ) -> List[Dict[str, Any]]:
        """
        Find APIs that work with a specific entity.

        Args:
            entity_name: The entity name

        Returns:
            List of related APIs
        """
        entity_lower = entity_name.lower()
        results = []

        for api in self.data.get("apis", []):
            # Check request/response types
            request_body = api.get("request_body", "") or ""
            response_type = api.get("response_type", "") or ""

            if (entity_lower in request_body.lower() or
                entity_lower in response_type.lower() or
                entity_lower in api.get("class_name", "").lower()):
                results.append({"api": api})

        return results

    def get_api_dependencies(
        self,
        api_path: str,
        method: str = None
    ) -> Dict[str, Any]:
        """
        Get full details about an API endpoint.

        Args:
            api_path: The API path
            method: Optional HTTP method

        Returns:
            API details with related services and entities
        """
        apis = self.search_apis(api_path, method=method, limit=1)
        if apis:
            api = apis[0]["api"]
            return {
                "api": api,
                "related_services": self._find_related_services(api),
                "related_entities": self._find_related_entities(api)
            }
        return {}

    def _find_related_services(self, api: Dict) -> List[Dict]:
        """Find services used by this API's controller."""
        class_name = api.get("class_name", "")
        if not class_name:
            return []

        # Services are typically injected into controllers
        return self.search_services(class_name.replace("Controller", ""), limit=5)

    def _find_related_entities(self, api: Dict) -> List[Dict]:
        """Find entities used by this API."""
        request_body = api.get("request_body", "") or ""
        response_type = api.get("response_type", "") or ""

        entities = []
        for type_name in [request_body, response_type]:
            if type_name and type_name != "ResponseEntity" and type_name != "Object":
                entity_results = self.search_entities(type_name, limit=1)
                if entity_results:
                    entities.append(entity_results[0])

        return entities

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of the knowledge base."""
        return {
            "total_apis": len(self.data.get("apis", [])),
            "total_python_apis": len(self.data.get("python_apis", [])),
            "total_go_apis": len(self.data.get("go_apis", [])),
            "total_services": len(self.data.get("services", [])),
            "total_entities": len(self.data.get("entities", [])),
            "total_repositories": len(self.data.get("repositories", []))
        }


# Singleton instance
_kb_instance: Optional[BackendKnowledgeBase] = None


def get_backend_knowledge_base(kb_path: str = None) -> BackendKnowledgeBase:
    """Get singleton knowledge base instance."""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = BackendKnowledgeBase(kb_path)
    return _kb_instance