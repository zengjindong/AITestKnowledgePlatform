"""
Code Indexer for building knowledge base from source code.

This module scans source code directories and builds an index of:
- Components (React/Vue)
- API endpoints
- Routes
- Business logic
- File dependencies
"""
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ComponentInfo:
    """Information about a UI component."""
    name: str
    file_path: str
    component_type: str  # "vue", "react", "jsx", "tsx"
    props: List[str] = field(default_factory=list)
    api_calls: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class APIEndpoint:
    """Information about an API endpoint."""
    path: str
    method: str
    file_path: str
    function_name: str
    parameters: List[str] = field(default_factory=list)


@dataclass
class RouteInfo:
    """Information about a route."""
    path: str
    component: str
    file_path: str
    guards: List[str] = field(default_factory=list)


@dataclass
class ProjectIndex:
    """Complete index of a project."""
    project_name: str
    project_path: str
    components: List[ComponentInfo] = field(default_factory=list)
    apis: List[APIEndpoint] = field(default_factory=list)
    routes: List[RouteInfo] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert index to dictionary."""
        return {
            "project_name": self.project_name,
            "project_path": self.project_path,
            "components": [
                {
                    "name": c.name,
                    "file_path": c.file_path,
                    "type": c.component_type,
                    "props": c.props,
                    "api_calls": c.api_calls,
                    "imports": c.imports,
                    "exports": c.exports
                }
                for c in self.components
            ],
            "apis": [
                {
                    "path": a.path,
                    "method": a.method,
                    "file_path": a.file_path,
                    "function_name": a.function_name
                }
                for a in self.apis
            ],
            "routes": [
                {
                    "path": r.path,
                    "component": r.component,
                    "file_path": r.file_path
                }
                for r in self.routes
            ],
            "file_count": len(self.files),
            "created_at": self.created_at
        }


class CodeIndexer:
    """
    Scans source code directories and builds searchable indexes.

    Supports:
    - Vue.js (.vue files)
    - React (.jsx, .tsx files)
    - JavaScript/TypeScript
    - API definitions
    """

    # File patterns to index
    COMPONENT_PATTERNS = {
        "vue": ["*.vue"],
        "react": ["*.jsx", "*.tsx"],
    }

    # Directories to exclude
    EXCLUDE_DIRS = {
        "node_modules", ".git", ".svn", "dist", "build", ".venv",
        "__pycache__", ".idea", ".vscode", "coverage", "test",
        "tests", ".temp", "temp"
    }

    def __init__(self, project_path: str, project_name: str = None):
        self.project_path = Path(project_path)
        self.project_name = project_name or project_path.split("/")[-1]
        self.index: Optional[ProjectIndex] = None

    def scan(self) -> ProjectIndex:
        """Scan the project and build index."""
        logger.info(f"Scanning project: {self.project_name} at {self.project_path}")

        index = ProjectIndex(
            project_name=self.project_name,
            project_path=str(self.project_path)
        )

        # Collect all relevant files
        all_files = self._collect_files()
        index.files = [str(f) for f in all_files]

        logger.info(f"Found {len(all_files)} files to analyze")

        # Analyze each file
        for file_path in all_files:
            self._analyze_file(file_path, index)

        self.index = index
        logger.info(f"Index complete: {len(index.components)} components, {len(index.apis)} APIs")
        return index

    def _collect_files(self) -> List[Path]:
        """Collect all relevant source files."""
        files = []
        for root, dirs, filenames in os.walk(self.project_path):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS]

            for filename in filenames:
                if self._is_relevant_file(filename):
                    files.append(Path(root) / filename)

        return files

    def _is_relevant_file(self, filename: str) -> bool:
        """Check if file is relevant for indexing."""
        relevant_ext = {
            ".vue", ".jsx", ".tsx", ".js", ".ts",
            ".py", ".go", ".java"
        }
        return any(filename.endswith(ext) for ext in relevant_ext)

    def _analyze_file(self, file_path: Path, index: ProjectIndex) -> None:
        """Analyze a single file and extract information."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            suffix = file_path.suffix.lower()

            if suffix == ".vue":
                self._analyze_vue_file(file_path, content, index)
            elif suffix in [".jsx", ".tsx"]:
                self._analyze_react_file(file_path, content, index)
            elif suffix == ".js":
                self._analyze_js_file(file_path, content, index)

        except Exception as e:
            logger.debug(f"Could not analyze {file_path}: {e}")

    def _analyze_vue_file(self, file_path: Path, content: str, index: ProjectIndex) -> None:
        """Analyze Vue component file."""
        # Extract component name from filename
        component_name = file_path.stem

        # Extract <script> content
        script_match = re.search(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
        script_content = script_match.group(1) if script_match else ""

        # Extract <template> content
        template_match = re.search(r'<template[^>]*>(.*?)</template>', content, re.DOTALL)
        template_content = template_match.group(1) if template_match else ""

        # Extract props
        props = re.findall(r'props\s*:\s*\{([^}]+)\}', script_content)
        prop_names = []
        for prop_block in props:
            prop_names.extend(re.findall(r'(\w+)\s*:', prop_block))

        # Extract API calls (axios, fetch, etc.)
        api_calls = re.findall(r'(?:axios|fetch|\$http)\.(?:get|post|put|delete|patch)\([\'"`]([^\'"`]+)', content)
        api_calls.extend(re.findall(r'api\.(\w+)\(', content))

        # Extract imports
        imports = re.findall(r'import\s+(?:\{[^}]+\}|[\w]+)\s+from\s+[\'"]([^\'"]+)', content)

        # Extract exports
        exports = re.findall(r'(?:export\s+(?:default|const|function|class)\s+)(\w+)', content)

        component = ComponentInfo(
            name=component_name,
            file_path=str(file_path),
            component_type="vue",
            props=prop_names,
            api_calls=api_calls,
            imports=[i for i in imports if not i.startswith('.') or i.startswith('@')],
            exports=exports[:5]  # Limit to first 5
        )

        index.components.append(component)

    def _analyze_react_file(self, file_path: Path, content: str, index: ProjectIndex) -> None:
        """Analyze React component file."""
        component_name = file_path.stem

        # Extract props/parameters
        props = re.findall(r'(?:function\s+\w+|(?:const|let)\s+\w+)\s*\([^)]*(\w+)', content)
        props = list(set(props))[:20]  # Dedupe and limit

        # Extract API calls
        api_calls = re.findall(r'(?:fetch|axios)\([\'"`]([^\'"`]+)', content)

        # Extract imports
        imports = re.findall(r'import\s+(?:\{[^}]+\}|[\w]+)\s+from\s+[\'"]([^\'"]+)', content)

        # Extract hooks usage
        hooks = re.findall(r'use(?:State|Effect|Context|Ref|Callback|Memo)\b', content)

        component = ComponentInfo(
            name=component_name,
            file_path=str(file_path),
            component_type="react",
            props=props,
            api_calls=api_calls,
            imports=[i for i in imports if not i.startswith('./') and not i.startswith('../')],
            exports=[component_name]
        )

        index.components.append(component)

    def _analyze_js_file(self, file_path: Path, content: str, index: ProjectIndex) -> None:
        """Analyze JavaScript file for APIs and routes."""
        # Skip if it's not an API file
        filename_lower = file_path.name.lower()
        if 'api' not in filename_lower and 'route' not in filename_lower:
            return

        # Extract API endpoints
        # Pattern: router.get('/path', handler)
        api_patterns = [
            r'(?:router|app)\.(get|post|put|delete|patch)\([\'"`]([^\'"`]+)',
            r'@.*\.(get|post|put|delete|patch)\([\'"`]([^\'"`]+)',
        ]

        for pattern in api_patterns:
            matches = re.findall(pattern, content)
            for method, path in matches:
                api = APIEndpoint(
                    path=path,
                    method=method.upper(),
                    file_path=str(file_path),
                    function_name="handler"
                )
                index.apis.append(api)

    def to_dict(self) -> Dict[str, Any]:
        """Convert index to dictionary."""
        if self.index is None:
            return {}

        return {
            "project_name": self.index.project_name,
            "project_path": self.index.project_path,
            "components": [
                {
                    "name": c.name,
                    "file_path": c.file_path,
                    "type": c.component_type,
                    "props": c.props,
                    "api_calls": c.api_calls,
                    "imports": c.imports,
                    "exports": c.exports
                }
                for c in self.index.components
            ],
            "apis": [
                {
                    "path": a.path,
                    "method": a.method,
                    "file_path": a.file_path,
                    "function_name": a.function_name
                }
                for a in self.index.apis
            ],
            "routes": [
                {
                    "path": r.path,
                    "component": r.component,
                    "file_path": r.file_path
                }
                for r in self.index.routes
            ],
            "file_count": len(self.index.files),
            "created_at": self.index.created_at
        }

    def save_to_file(self, output_path: str) -> None:
        """Save index to JSON file."""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"Index saved to {output_path}")


class MultiProjectIndexer:
    """Indexes multiple projects into a unified knowledge base."""

    def __init__(self):
        self.projects: Dict[str, ProjectIndex] = {}

    def add_project(self, project_path: str, project_name: str = None) -> ProjectIndex:
        """Add and index a project."""
        indexer = CodeIndexer(project_path, project_name)
        index = indexer.scan()
        self.projects[project_name or project_path] = index
        return index

    def get_all_components(self) -> List[ComponentInfo]:
        """Get all components from all projects."""
        components = []
        for project_index in self.projects.values():
            components.extend(project_index.components)
        return components

    def search_components(self, query: str) -> List[ComponentInfo]:
        """Search components by name or props."""
        query_lower = query.lower()
        results = []

        for component in self.get_all_components():
            if (query_lower in component.name.lower() or
                any(query_lower in prop.lower() for prop in component.props) or
                any(query_lower in imp.lower() for imp in component.imports)):
                results.append(component)

        return results

    def to_dict(self) -> Dict[str, Any]:
        """Convert all indexes to dictionary."""
        return {
            "projects": {
                name: project.to_dict()
                for name, project in self.projects.items()
            },
            "total_components": sum(len(p.components) for p in self.projects.values()),
            "total_apis": sum(len(p.apis) for p in self.projects.values())
        }

    def save_to_file(self, output_path: str) -> None:
        """Save unified index to JSON file."""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"Unified index saved to {output_path}")


if __name__ == "__main__":
    # Example usage
    indexer = MultiProjectIndexer()

    # Index yiye-landingpage-editor
    indexer.add_project(
        "D:/code/yiye-landingpage-editor/src",
        "yiye-landingpage-editor"
    )

    # Save to file
    output_path = "D:/code/AITestKnowledgePlatform/data/frontend_knowledge_base.json"
    indexer.save_to_file(output_path)

    print(f"Indexed {len(indexer.projects)} projects")
    print(f"Total components: {len(indexer.get_all_components())}")