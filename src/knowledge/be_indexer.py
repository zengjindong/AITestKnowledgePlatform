"""
Backend Code Indexer for building knowledge base from source code.

This module scans source code directories and builds an index of:
- API endpoints (REST controllers) - Java/Spring, Python/FastAPI/Flask, Go
- Services
- Repositories
- Entities/Models
- Database tables
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
class APIEndpoint:
    """Information about a REST API endpoint."""
    path: str
    method: str  # GET, POST, PUT, DELETE, PATCH
    class_name: str
    method_name: str
    file_path: str
    parameters: List[str] = field(default_factory=list)
    request_body: Optional[str] = None
    response_type: Optional[str] = None


@dataclass
class ServiceInfo:
    """Information about a service class."""
    name: str
    file_path: str
    methods: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class RepositoryInfo:
    """Information about a repository/DAO."""
    name: str
    file_path: str
    entity_type: str = ""
    table_name: str = ""


@dataclass
class EntityInfo:
    """Information about an entity/model."""
    name: str
    file_path: str
    table_name: str
    fields: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class PythonAPIEndpoint:
    """Information about a Python FastAPI/Flask endpoint."""
    path: str
    method: str  # GET, POST, PUT, DELETE, PATCH
    function_name: str
    file_path: str
    parameters: List[str] = field(default_factory=list)
    request_body: Optional[str] = None
    response_type: Optional[str] = None


@dataclass
class GoAPIEndpoint:
    """Information about a Go net/http endpoint."""
    path: str
    method: str  # GET, POST, PUT, DELETE, PATCH
    handler_name: str
    file_path: str
    parameters: List[str] = field(default_factory=list)


@dataclass
class BackendIndex:
    """Complete index of a backend project."""
    project_name: str
    project_path: str
    apis: List[APIEndpoint] = field(default_factory=list)
    services: List[ServiceInfo] = field(default_factory=list)
    repositories: List[RepositoryInfo] = field(default_factory=list)
    entities: List[EntityInfo] = field(default_factory=list)
    python_apis: List[PythonAPIEndpoint] = field(default_factory=list)
    go_apis: List[GoAPIEndpoint] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "project_path": self.project_path,
            "apis": [
                {
                    "path": a.path,
                    "method": a.method,
                    "class_name": a.class_name,
                    "method_name": a.method_name,
                    "file_path": a.file_path,
                    "parameters": a.parameters,
                    "request_body": a.request_body,
                    "response_type": a.response_type
                }
                for a in self.apis
            ],
            "services": [
                {
                    "name": s.name,
                    "file_path": s.file_path,
                    "methods": s.methods,
                    "dependencies": s.dependencies
                }
                for s in self.services
            ],
            "repositories": [
                {
                    "name": r.name,
                    "file_path": r.file_path,
                    "entity_type": r.entity_type,
                    "table_name": r.table_name
                }
                for r in self.repositories
            ],
            "entities": [
                {
                    "name": e.name,
                    "file_path": e.file_path,
                    "table_name": e.table_name,
                    "fields": e.fields
                }
                for e in self.entities
            ],
            "python_apis": [
                {
                    "path": a.path,
                    "method": a.method,
                    "function_name": a.function_name,
                    "file_path": a.file_path,
                    "parameters": a.parameters,
                    "request_body": a.request_body,
                    "response_type": a.response_type
                }
                for a in self.python_apis
            ],
            "go_apis": [
                {
                    "path": a.path,
                    "method": a.method,
                    "handler_name": a.handler_name,
                    "file_path": a.file_path,
                    "parameters": a.parameters
                }
                for a in self.go_apis
            ],
            "file_count": len(self.files),
            "created_at": self.created_at
        }


class BackendIndexer:
    """
    Scans source code directories and builds searchable indexes.

    Supports:
    - Java/Spring (@GetMapping, @PostMapping, etc.)
    - Python/FastAPI (@app.get, @router.post, etc.)
    - Python/Flask (@app.route)
    - Go/net/http (http.HandleFunc, http.HandlerFunc)

    Extracts:
    - REST API endpoints
    - Service classes
    - Repositories
    - Entities
    """

    EXCLUDE_DIRS = {
        "target", ".git", ".svn", ".idea", ".vscode",
        "node_modules", "test", "tests", "generated", ".venv", "venv"
    }

    # Language patterns
    LANG_EXTENSIONS = {
        "java": [".java"],
        "python": [".py"],
        "go": [".go"]
    }

    def __init__(self, project_path: str, project_name: str = None):
        self.project_path = Path(project_path)
        self.project_name = project_name or project_path.split("/")[-1]
        self.index: Optional[BackendIndex] = None

    def scan(self) -> BackendIndex:
        """Scan the project and build index."""
        logger.info(f"Scanning backend project: {self.project_name} at {self.project_path}")

        index = BackendIndex(
            project_name=self.project_name,
            project_path=str(self.project_path)
        )

        # Collect files by language
        java_files = self._collect_files(".java")
        python_files = self._collect_files(".py")
        go_files = self._collect_files(".go")

        index.files = [str(f) for f in java_files + python_files + go_files]

        logger.info(f"Found {len(java_files)} Java, {len(python_files)} Python, {len(go_files)} Go files")

        # Analyze each file by language
        for file_path in java_files:
            self._analyze_java_file(file_path, index)
        for file_path in python_files:
            self._analyze_python_file(file_path, index)
        for file_path in go_files:
            self._analyze_go_file(file_path, index)

        self.index = index
        logger.info(f"Index complete: {len(index.apis)} Java APIs, {len(index.python_apis)} Python APIs, {len(index.go_apis)} Go APIs")
        return index

    def _collect_files(self, extension: str) -> List[Path]:
        """Collect all source files with given extension."""
        files = []
        for root, dirs, filenames in os.walk(self.project_path):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS]

            for filename in filenames:
                if filename.endswith(extension):
                    files.append(Path(root) / filename)

        return files

    def _analyze_java_file(self, file_path: Path, index: BackendIndex) -> None:
        """Analyze a single Java file."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Determine file type by annotations
            if "@RestController" in content or "@Controller" in content and "@RequestMapping" in content:
                self._analyze_controller(file_path, content, index)
            elif "@Service" in content:
                self._analyze_service(file_path, content, index)
            elif "@Repository" in content or "extends JpaRepository" in content or "extends CrudRepository" in content:
                self._analyze_repository(file_path, content, index)
            elif "@Entity" in content or "@Table" in content:
                self._analyze_entity(file_path, content, index)

        except Exception as e:
            logger.debug(f"Could not analyze {file_path}: {e}")

    def _analyze_controller(self, file_path: Path, content: str, index: BackendIndex) -> None:
        """Analyze a REST controller."""
        class_name = file_path.stem

        # Extract class-level request mapping
        class_mapping = ""
        class_mapping_match = re.search(r'@RequestMapping\(["\']([^"\']+)["\']\)', content)
        if class_mapping_match:
            class_mapping = class_mapping_match.group(1)

        # Extract method-level mappings
        method_patterns = [
            (r'@GetMapping\(["\']([^"\']+)["\']\)', 'GET'),
            (r'@PostMapping\(["\']([^"\']+)["\']\)', 'POST'),
            (r'@PutMapping\(["\']([^"\']+)["\']\)', 'PUT'),
            (r'@DeleteMapping\(["\']([^"\']+)["\']\)', 'DELETE'),
            (r'@PatchMapping\(["\']([^"\']+)["\']\)', 'PATCH'),
            (r'@RequestMapping\(.*?method\s*=\s*RequestMethod\.(\w+)', 'GET'),  # Generic RequestMapping
        ]

        for pattern, method in method_patterns:
            for match in re.finditer(pattern, content):
                path = match.group(1) if match.lastindex >= 1 else ""
                full_path = class_mapping + path if path.startswith("/") else class_mapping + "/" + path

                # Find method name
                method_match = re.search(r'public\s+\w+(?:<[^>]+>)?\s+(\w+)\s*\([^)]*\)', content[match.start():match.start()+500])
                method_name = method_match.group(1) if method_match else "anonymous"

                # Extract parameters
                params = re.findall(r'@(\w+)\s+(?:\w+\s+)?(\w+)', content[match.start():match.start()+1000])
                param_names = [p[1] for p in params if p[0] not in ["RequestMapping", "GetMapping", "PostMapping", "PutMapping", "DeleteMapping", "PatchMapping"]]

                # Extract request/response types
                request_body = None
                if "@RequestBody" in content[match.start():match.start()+1000]:
                    request_body_match = re.search(r'@RequestBody\s+(\w+(?:<[^>]+>)?)', content[match.start():match.start()+1000])
                    request_body = request_body_match.group(1) if request_body_match else "Object"

                response_match = re.search(r'public\s+(\w+(?:<[^>]+>)?)\s+\w+\s*\([^)]*\)', content[match.start():match.start()+200])
                response_type = response_match.group(1) if response_match else "ResponseEntity"

                api = APIEndpoint(
                    path=full_path.strip("/"),
                    method=method,
                    class_name=class_name,
                    method_name=method_name,
                    file_path=str(file_path),
                    parameters=param_names,
                    request_body=request_body,
                    response_type=response_type
                )
                index.apis.append(api)

    def _analyze_service(self, file_path: Path, content: str, index: BackendIndex) -> None:
        """Analyze a service class."""
        class_name = file_path.stem

        # Extract method names
        methods = re.findall(r'public\s+\w+(?:<[^>]+>)?\s+(\w+)\s*\(', content)

        # Extract dependencies (autowired fields)
        dependencies = re.findall(r'@Autowired\s+(?:private\s+)?(\w+(?:<[^>]+>)?)', content)
        dependencies.extend(re.findall(r'private\s+(\w+(?:<[^>]+>)?)\s+\w+;', content))

        service = ServiceInfo(
            name=class_name,
            file_path=str(file_path),
            methods=methods[:20],  # Limit
            dependencies=list(set(dependencies))[:10]
        )
        index.services.append(service)

    def _analyze_repository(self, file_path: Path, content: str, index: BackendIndex) -> None:
        """Analyze a repository/DAO."""
        class_name = file_path.stem

        # Extract entity type
        entity_match = re.search(r'extends\s+\w+Repository<(\w+)', content)
        entity_type = entity_match.group(1) if entity_match else ""

        # Extract table name from entity if possible
        table_name = class_name.replace("Repository", "").replace("Dao", "")

        repo = RepositoryInfo(
            name=class_name,
            file_path=str(file_path),
            entity_type=entity_type,
            table_name=table_name
        )
        index.repositories.append(repo)

    def _analyze_entity(self, file_path: Path, content: str, index: BackendIndex) -> None:
        """Analyze an entity/model."""
        class_name = file_path.stem

        # Extract table name
        table_match = re.search(r'@Table\(["\']([^"\']+)["\']\)', content)
        table_name = table_match.group(1) if table_match else class_name

        # Extract fields with types
        fields = []
        # Skip inner classes and methods
        class_content = re.split(r'(?:public|private|protected)\s+(?:static\s+)?class', content)[0]
        field_matches = re.findall(r'(?:@Column\([^)]*\)\s+)?(?:@Id\s+)?private\s+(\w+(?:<[^>]+>)?)\s+(\w+);', class_content)
        for field_type, field_name in field_matches:
            fields.append({"type": field_type, "name": field_name})

        entity = EntityInfo(
            name=class_name,
            file_path=str(file_path),
            table_name=table_name,
            fields=fields
        )
        index.entities.append(entity)

    def _analyze_python_file(self, file_path: Path, index: BackendIndex) -> None:
        """Analyze a Python file for FastAPI/Flask endpoints."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Skip if not an API file
            filename_lower = file_path.name.lower()
            is_api_file = any(kw in filename_lower for kw in ['api', 'route', 'endpoint', 'view', 'handler'])
            if not (is_api_file or '@app.' in content or '@router.' in content or 'def ' in content):
                return

            # FastAPI pattern: @app.get("/path"), @app.post("/path"), etc.
            fastapi_pattern = r'@(?:app|router)\.(get|post|put|delete|patch|options|head)\\(["\']([^"\']+)["\']\)'
            for match in re.finditer(fastapi_pattern, content):
                method = match.group(1).upper()
                path = match.group(2)

                # Find the function definition after the decorator
                func_start = match.end()
                func_match = re.search(r'def\s+(\w+)\s*\(', content[func_start:func_start+500])
                if func_match:
                    func_name = func_match.group(1)
                else:
                    func_name = "handler"

                # Extract function parameters
                param_match = re.search(r'def\s+\w+\s*\(([^)]*)\)', content[func_start:func_start+1000])
                params = []
                if param_match and param_match.group(1).strip():
                    params = [p.strip().split(':')[0].strip() for p in param_match.group(1).split(',')]
                    params = [p for p in params if p and not p.startswith('*')]

                api = PythonAPIEndpoint(
                    path=path.strip("/"),
                    method=method,
                    function_name=func_name,
                    file_path=str(file_path),
                    parameters=params
                )
                index.python_apis.append(api)

            # Flask pattern: @app.route("/path", methods=["GET", "POST"])
            flask_pattern = r'@(?:app|blueprint)\.route\(["\']([^"\']+)["\']'
            for match in re.finditer(flask_pattern, content):
                path = match.group(1)

                # Find methods in the same route call
                methods_match = re.search(r'methods\s*=\s*\[([^\]]+)\]', content[match.start():match.start()+200])
                if methods_match:
                    methods_str = methods_match.group(1)
                    methods = re.findall(r'["\'](\w+)["\']', methods_str)
                else:
                    methods = ["GET"]

                for method in methods:
                    # Skip if already found as FastAPI
                    if any(a.path == path.strip("/") and a.method == method for a in index.python_apis):
                        continue

                    func_start = match.end()
                    func_match = re.search(r'def\s+(\w+)\s*\(', content[func_start:func_start+500])
                    func_name = func_match.group(1) if func_match else "handler"

                    api = PythonAPIEndpoint(
                        path=path.strip("/"),
                        method=method.upper(),
                        function_name=func_name,
                        file_path=str(file_path),
                        parameters=[]
                    )
                    index.python_apis.append(api)

            # Django view pattern: path("path", views.handler)
            django_pattern = r'path\(["\']([^"\']+)["\']\s*,\s*(\w+)'
            for match in re.finditer(django_pattern, content):
                path = match.group(1)
                handler = match.group(2)

                api = PythonAPIEndpoint(
                    path=path.strip("/"),
                    method="GET",  # Django paths need view to determine method
                    function_name=handler,
                    file_path=str(file_path),
                    parameters=[]
                )
                index.python_apis.append(api)

        except Exception as e:
            logger.debug(f"Could not analyze Python file {file_path}: {e}")

    def _analyze_go_file(self, file_path: Path, index: BackendIndex) -> None:
        """Analyze a Go file for net/http endpoints."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Skip if not an HTTP file
            if 'net/http' not in content and 'http.' not in content:
                return

            # Pattern 1: http.HandleFunc("/path", handler)
            handlefunc_pattern = r'(?:http\.HandleFunc|http\.HandlerFunc)\(["\']([^"\']+)["\']\s*,\s*(\w+)'
            for match in re.finditer(handlefunc_pattern, content):
                path = match.group(1)
                handler = match.group(2)

                api = GoAPIEndpoint(
                    path=path.strip("/"),
                    method="GET",  # HandleFunc defaults to GET unless specified
                    handler_name=handler,
                    file_path=str(file_path),
                    parameters=[]
                )
                index.go_apis.append(api)

            # Pattern 2: http.MethodFunc("/path", handler)
            methodfunc_pattern = r'(?:http\.(?:Get|Post|Put|Delete|Patch)Func)\(["\']([^"\']+)["\']\s*,\s*(\w+)'
            for match in re.finditer(methodfunc_pattern, content):
                path = match.group(1)
                handler = match.group(2)
                # Extract method from function name
                method_match = re.search(r'http\.(Get|Post|Put|Delete|Patch)(\w+)Func', match.group(0))
                method = method_match.group(1).upper() if method_match else "GET"

                api = GoAPIEndpoint(
                    path=path.strip("/"),
                    method=method,
                    handler_name=handler,
                    file_path=str(file_path),
                    parameters=[]
                )
                index.go_apis.append(api)

            # Pattern 3: mux.HandleFunc for gorilla/mux router
            mux_pattern = r'(?:mux|router)\.HandleFunc\(["\']([^"\']+)["\']\s*,\s*(\w+)'
            for match in re.finditer(mux_pattern, content):
                path = match.group(1)
                handler = match.group(2)

                api = GoAPIEndpoint(
                    path=path.strip("/"),
                    method="GET",
                    handler_name=handler,
                    file_path=str(file_path),
                    parameters=[]
                )
                index.go_apis.append(api)

            # Pattern 4: chi router pattern
            chi_pattern = r'(?:r\.Route|Route)\(["\']([^"\']+)["\']'
            for match in re.finditer(chi_pattern, content):
                path = match.group(1)

                api = GoAPIEndpoint(
                    path=path.strip("/"),
                    method="GET",
                    handler_name="chi_handler",
                    file_path=str(file_path),
                    parameters=[]
                )
                index.go_apis.append(api)

        except Exception as e:
            logger.debug(f"Could not analyze Go file {file_path}: {e}")

    def save_to_file(self, output_path: str) -> None:
        """Save index to JSON file."""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.index.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"Backend index saved to {output_path}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from src.knowledge.indexer import MultiProjectIndexer

    # Create combined indexer
    indexer = MultiProjectIndexer()

    # Index backend
    backend_indexer = BackendIndexer("D:/code/yiye-agent-backend", "yiye-agent-backend")
    backend_indexer.scan()
    backend_indexer.save_to_file("D:/code/AITestKnowledgePlatform/data/backend_knowledge_base.json")

    print(f"Backend index: {len(backend_indexer.index.apis)} APIs, {len(backend_indexer.index.services)} services, {len(backend_indexer.index.entities)} entities")