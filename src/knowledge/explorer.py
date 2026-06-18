"""
自动化系统探索与功能映射模块 (System Explorer & Function Mapper)

该模块通过模拟用户行为，自动遍历目标系统的所有可访问页面和功能点，
并将其结构化地记录下来，构建"系统功能全景图"。

功能：
- 页面遍历与导航
- 功能点识别与提取
- 状态管理与去重
- 功能图谱构建
- 信息汇总与输出
"""
import json
import logging
import uuid
import re
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse, parse_qs
from pathlib import Path

logger = logging.getLogger(__name__)


LOGIN_PATH_PATTERNS = ("/login", "/signin", "/sso", "/auth", "/oauth", "/saml")

DESTRUCTIVE_PATTERNS = (
    "delete", "remove", "save", "submit", "create", "add", "edit", "update",
    "publish", "approve", "reject", "confirm", "pay", "refund", "disable",
    "cancel", "reset", "删除", "移除", "保存", "提交", "创建", "新增", "添加",
    "编辑", "更新", "修改", "发布", "审批", "批准", "拒绝", "确认", "支付",
    "退款", "禁用", "取消", "重置",
)

SAFE_ACTION_PATTERNS = (
    "view", "details", "detail", "open", "search", "query", "filter", "refresh",
    "expand", "collapse", "more", "next", "previous", "back", "查看", "详情",
    "打开", "搜索", "查询", "筛选", "过滤", "刷新", "展开", "收起", "更多",
    "下一页", "上一页", "返回",
)

ACTION_SELECTOR = (
    "a[href], button:not([disabled]), [role='button']:not([aria-disabled='true']), "
    "[role='menuitem']:not([aria-disabled='true']), [role='tab']:not([aria-disabled='true']), "
    "summary, select:not([disabled]), input[type='submit']:not([disabled]), "
    ".ant-menu-item, .ant-tabs-tab, .ant-dropdown-trigger, .ant-select, "
    ".ant-pagination-item, .ant-pagination-next, .ant-pagination-prev, "
    ".el-menu-item, .el-tabs__item, .el-dropdown, .el-select, [aria-haspopup='menu'], [aria-expanded]"
)


def session_path_for(url: str, base_dir: Path = None) -> Path:
    """Return the per-URL storage_state path under data/storage_states/."""
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent.parent / "data" / "storage_states"
    base_dir.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return base_dir / f"{hashlib.sha1(key.encode()).hexdigest()}.json"


class FunctionType(str, Enum):
    """功能点类型"""
    PAGE_NAV = "PAGE_NAV"           # 页面导航
    API_CALL = "API_CALL"           # API调用
    FORM_SUBMIT = "FORM_SUBMIT"       # 表单提交
    UI_INTERACTION = "UI_INTERACTION" # UI交互


@dataclass
class ActionCandidate:
    """A visible UI action candidate in a specific page state."""
    action_id: str
    selector: str
    selector_type: str
    label: str
    role: str
    tag: str
    action_type: str
    href: str = ""
    index: int = 0
    is_safe: bool = True
    skip_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_replay_step(self) -> Dict[str, Any]:
        return {
            "selector": self.selector,
            "selector_type": self.selector_type,
            "label": self.label,
            "role": self.role,
            "tag": self.tag,
            "action_type": self.action_type,
            "href": self.href,
            "index": self.index,
        }


@dataclass
class FunctionPoint:
    """系统功能点"""
    function_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    func_type: FunctionType = FunctionType.PAGE_NAV
    entry_point: str = ""  # URL 或 XPath
    related_apis: List[str] = field(default_factory=list)
    parameters: Dict[str, str] = field(default_factory=dict)  # 参数名 -> 类型
    parent_function_id: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "function_id": self.function_id,
            "name": self.name,
            "description": self.description,
            "type": self.func_type.value,
            "entry_point": self.entry_point,
            "related_apis": self.related_apis,
            "parameters": self.parameters,
            "parent_function_id": self.parent_function_id,
            "evidence": self.evidence,
            "created_at": self.created_at
        }


@dataclass
class FunctionGraph:
    """功能图谱"""
    project_id: str = ""
    nodes: List[FunctionPoint] = field(default_factory=list)
    edges: List[Dict[str, str]] = field(default_factory=list)  # {"from": id, "to": id, "relation": "NAVIGATES_TO|TRIGGERS|DEPENDS_ON"}
    api_endpoints: List[Dict[str, Any]] = field(default_factory=list)
    exploration_log: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_function(self, func: FunctionPoint) -> None:
        self.nodes.append(func)

    def add_edge(self, from_id: str, to_id: str, relation: str) -> None:
        self.edges.append({"from": from_id, "to": to_id, "relation": relation})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": self.edges,
            "api_endpoints": self.api_endpoints,
            "exploration_log": self.exploration_log,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }


class VisitedState:
    """已访问状态管理"""
    visited_urls: Set[str]
    visited_elements: Set[str]
    pending_queue: List[Dict[str, Any]]
    visited_api_patterns: Set[str]
    visited_state_hashes: Set[str]
    queued_state_hashes: Set[str]
    visited_action_keys: Set[str]
    project_id: str

    def __init__(self, project_id: str = "default"):
        self.visited_urls = set()
        self.visited_elements = set()
        self.pending_queue = []
        self.visited_api_patterns = set()
        self.visited_state_hashes = set()
        self.queued_state_hashes = set()
        self.visited_action_keys = set()
        self.project_id = project_id
        self.load_history()

    def _history_path(self) -> Path:
        """Path to the exploration history file for this project."""
        path = Path("data/exploration_history")
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{self.project_id}.json"

    def load_history(self) -> None:
        """Load previously explored URLs and actions from disk."""
        hist_file = self._history_path()
        if not hist_file.exists():
            return
        try:
            import json
            data = json.loads(hist_file.read_text(encoding="utf-8"))
            self.visited_urls.update(data.get("visited_urls", []))
            self.visited_state_hashes.update(data.get("visited_state_hashes", []))
            self.visited_action_keys.update(data.get("visited_action_keys", []))
            logger.info("Loaded exploration history: %d URLs, %d states, %d actions",
                         len(self.visited_urls), len(self.visited_state_hashes), len(self.visited_action_keys))
        except Exception as e:
            logger.debug("Failed to load exploration history: %s", e)

    def save_history(self) -> None:
        """Persist visited URLs, state hashes, and action keys to disk."""
        hist_file = self._history_path()
        try:
            import json
            data = {
                "visited_urls": sorted(self.visited_urls),
                "visited_state_hashes": sorted(self.visited_state_hashes),
                "visited_action_keys": sorted(self.visited_action_keys),
            }
            hist_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Saved exploration history: %d URLs, %d states, %d actions",
                         len(self.visited_urls), len(self.visited_state_hashes), len(self.visited_action_keys))
        except Exception as e:
            logger.error("Failed to save exploration history: %s", e)

    def mark_url_visited(self, url: str) -> bool:
        """标记URL为已访问，返回是否新访问"""
        normalized = self.normalize_url(url)
        if normalized in self.visited_urls:
            return False
        self.visited_urls.add(normalized)
        return True

    def mark_element_visited(self, element_xpath: str) -> bool:
        """标记元素为已访问，返回是否新访问"""
        if element_xpath in self.visited_elements:
            return False
        self.visited_elements.add(element_xpath)
        return True

    def add_to_queue(self, item: Dict[str, Any]) -> None:
        """添加待访问项到队列"""
        self.pending_queue.append(item)

    def mark_state_visited(self, state_hash: str) -> bool:
        """Mark a UI state as visited, returning whether it is new."""
        if state_hash in self.visited_state_hashes:
            return False
        self.visited_state_hashes.add(state_hash)
        return True

    def mark_action_visited(self, action_key: str) -> bool:
        """Mark a state-scoped action as visited, returning whether it is new."""
        if action_key in self.visited_action_keys:
            return False
        self.visited_action_keys.add(action_key)
        return True

    def is_state_seen(self, state_hash: str) -> bool:
        return state_hash in self.visited_state_hashes or state_hash in self.queued_state_hashes

    def normalize_url(self, url: str) -> str:
        """URL标准化，去除细微差异导致的重复访问"""
        parsed = urlparse(url)
        # 去除查询参数和锚点
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    def normalize_api_url(self, url: str) -> str:
        """API URL标准化，提取模式"""
        # 去除动态参数，用占位符替代
        pattern = re.sub(r'/[0-9a-f-]{36}', '/{id}', url)
        pattern = re.sub(r'\?.*', '', pattern)
        return pattern


class SystemExplorer:
    """
    系统探索器

    使用方法：
    explorer = SystemExplorer(start_url="http://localhost:3000")
    graph = explorer.explore(max_depth=3, max_pages=100)
    """

    def __init__(
        self,
        start_url: str = "http://localhost:3000",
        project_id: str = "default",
        auth_token: str = None
    ):
        self.start_url = start_url
        self.project_id = project_id
        self.auth_token = auth_token
        self.state = VisitedState(project_id)
        self.graph = FunctionGraph(project_id=project_id)
        self.stats = {
            "pages_visited": 0,
            "apis_discovered": 0,
            "functions_discovered": 0,
            "errors": []
        }

    def explore(
        self,
        max_depth: int = 3,
        max_pages: int = 100
    ) -> FunctionGraph:
        """
        执行探索

        Args:
            max_depth: 最大递归深度
            max_pages: 最大页面数

        Returns:
            FunctionGraph: 构建好的功能图谱
        """
        logger.info(f"Starting exploration from {self.start_url}, max_depth={max_depth}, max_pages={max_pages}")

        # 添加起始URL到队列
        self.state.add_to_queue({
            "url": self.start_url,
            "depth": 0,
            "parent": None
        })

        while self.state.pending_queue and self.stats["pages_visited"] < max_pages:
            item = self.state.pending_queue.pop(0)
            url = item["url"]
            depth = item["depth"]
            parent_id = item.get("parent")

            if depth > max_depth:
                continue

            if not self.state.mark_url_visited(url):
                logger.debug(f"Skipping already visited: {url}")
                continue

            self.stats["pages_visited"] += 1
            self._log(f"Visiting: {url}")

            # 分析页面
            page_functions = self._analyze_page(url, parent_id)
            for func in page_functions:
                self.graph.add_function(func)
                self.stats["functions_discovered"] += 1

                # 如果是新页面，加入队列继续探索
                if func.func_type == FunctionType.PAGE_NAV:
                    self.state.add_to_queue({
                        "url": func.entry_point,
                        "depth": depth + 1,
                        "parent": func.function_id
                    })

            # 发现相关API
            for api in page_functions[0].related_apis if page_functions else []:
                if api not in self.state.visited_api_patterns:
                    self.state.visited_api_patterns.add(api)
                    self.graph.api_endpoints.append({
                        "url": api,
                        "discovered_from": url,
                        "timestamp": datetime.now().isoformat()
                    })
                    self.stats["apis_discovered"] += 1

        logger.info(f"Exploration complete: {self.stats}")
        return self.graph

    def _analyze_page(self, url: str, parent_id: str = None) -> List[FunctionPoint]:
        """分析单个页面，提取功能点"""
        functions = []

        # 创建页面功能点
        page_func = FunctionPoint(
            name=self._extract_page_name(url),
            description=f"页面: {url}",
            func_type=FunctionType.PAGE_NAV,
            entry_point=url,
            parent_function_id=parent_id,
            evidence={"source": "crawler", "url": url}
        )
        functions.append(page_func)

        # 如果是演示模式，返回模拟数据
        if not self._is_reachable(url):
            # 返回演示功能点
            demo_funcs = self._generate_demo_functions(url, parent_id)
            functions.extend(demo_funcs)

        return functions

    def _is_reachable(self, url: str) -> bool:
        """检查URL是否可访问"""
        try:
            import urllib.request
            req = urllib.request.Request(url)
            if self.auth_token:
                req.add_header("Authorization", f"Bearer {self.auth_token}")
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception:
            return False

    def _extract_page_name(self, url: str) -> str:
        """从URL提取页面名称"""
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if not path:
            return "首页"
        parts = path.split("/")
        return parts[-1] or parts[0]

    def _generate_demo_functions(self, url: str, parent_id: str = None) -> List[FunctionPoint]:
        """生成演示用功能点（当无法真正访问时"""
        functions = []
        base_name = self._extract_page_name(url)

        # 常见的演示功能点
        demo_names = [
            ("登录", FunctionType.FORM_SUBMIT),
            ("注册", FunctionType.FORM_SUBMIT),
            ("搜索", FunctionType.API_CALL),
            ("列表查询", FunctionType.API_CALL),
            ("详情查看", FunctionType.PAGE_NAV),
            ("创建", FunctionType.FORM_SUBMIT),
            ("编辑", FunctionType.FORM_SUBMIT),
            ("删除", FunctionType.API_CALL),
        ]

        for name, ftype in demo_names[:3]:
            func = FunctionPoint(
                name=f"{base_name}_{name}",
                description=f"{base_name}功能的{name}功能",
                func_type=ftype,
                entry_point=url,
                parent_function_id=parent_id,
                related_apis=[f"{url}/api/{name.lower()}"],
                evidence={"source": "demo_generator", "url": url}
            )
            functions.append(func)

        return functions

    def _log(self, message: str) -> None:
        """记录探索日志"""
        logger.info(message)
        self.graph.exploration_log.append({
            "timestamp": datetime.now().isoformat(),
            "message": message
        })

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.graph.to_dict(), ensure_ascii=False, indent=indent)

    def save_to_file(self, filepath: str) -> None:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.to_json())
        logger.info(f"Saved function graph to {filepath}")


class SimpleBrowserExplorer:
    """
    简化的浏览器探索器（无头浏览器版本）

    当安装了 selenium/puppeteer 时使用真实浏览器
    """

    def __init__(self, start_url: str, project_id: str = "default"):
        self.start_url = start_url
        self.project_id = project_id
        self.state = VisitedState(project_id)
        self.graph = FunctionGraph(project_id=project_id)
        self.stats = {
            "pages_visited": 0,
            "apis_discovered": 0,
            "functions_discovered": 0
        }

    def explore(self, max_depth: int = 3, max_pages: int = 100) -> FunctionGraph:
        """探索入口"""
        # 基础URL分析
        self.state.add_to_queue({
            "url": self.start_url,
            "depth": 0,
            "parent": None
        })

        while self.state.pending_queue and self.stats["pages_visited"] < max_pages:
            item = self.state.pending_queue.pop(0)
            url = item["url"]
            depth = item["depth"]

            if depth > max_depth:
                continue

            if not self.state.mark_url_visited(url):
                continue

            self.stats["pages_visited"] += 1

            # 提取功能点
            funcs = self._extract_functions_from_url(url, depth, item.get("parent"))
            for f in funcs:
                self.graph.add_function(f)
                self.stats["functions_discovered"] += 1

                # 继续探索子页面
                if f.func_type == FunctionType.PAGE_NAV and depth < max_depth:
                    self.state.add_to_queue({
                        "url": f.entry_point,
                        "depth": depth + 1,
                        "parent": f.function_id
                    })

        return self.graph

    def _extract_functions_from_url(self, url: str, depth: int, parent_id: str = None) -> List[FunctionPoint]:
        """从URL提取功能点"""
        functions = []
        page_name = self._name_from_path(url)

        # 导航功能
        nav_func = FunctionPoint(
            name=page_name or "home",
            description=f"页面导航: {url}",
            func_type=FunctionType.PAGE_NAV,
            entry_point=url,
            parent_function_id=parent_id,
            evidence={"url": url, "depth": depth}
        )
        functions.append(nav_func)

        # 根据URL推断API
        api_patterns = self._infer_api_from_path(url)
        for api in api_patterns:
            api_func = FunctionPoint(
                name=f"{page_name}_{api['method']}",
                description=f"{api['method']} {api['path']}",
                func_type=FunctionType.API_CALL,
                entry_point=url,
                related_apis=[api["full_path"]],
                parent_function_id=nav_func.function_id,
                evidence={"inferred": True}
            )
            functions.append(api_func)
            self.graph.api_endpoints.append(api)

        return functions

    def _name_from_path(self, url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if not path:
            return "home"
        return path.split("/")[-1]

    def _infer_api_from_path(self, url: str) -> List[Dict[str, Any]]:
        """从URL路径推断可能的API调用"""
        apis = []
        parsed = urlparse(url)
        path = parsed.path

        # 常见RESTful模式
        segments = [s for s in path.split("/") if s]

        for i, seg in enumerate(segments):
            api_path = "/" + "/".join(segments[:i+1])
            method = "GET"
            if "create" in seg or "add" in seg:
                method = "POST"
            elif "edit" in seg or "update" in seg:
                method = "PUT"
            elif "delete" in seg:
                method = "DELETE"

            apis.append({
                "method": method,
                "path": f"/api{api_path}",
                "full_path": f"{parsed.scheme}://{parsed.netloc}/api{api_path}",
                "discovered_from": url
            })

        return apis


class PlaywrightExplorer:
    """
    Real browser explorer using Playwright for automated page crawling.

    This provides actual page exploration with DOM analysis when Playwright
    is available. Falls back to demo mode if Playwright is not installed.

    Usage:
        explorer = PlaywrightExplorer(start_url="http://localhost:3000")
        graph = explorer.explore(max_depth=3, max_pages=100)
    """

    def __init__(
        self,
        start_url: str = "http://localhost:3000",
        project_id: str = "default",
        auth_token: str = None,
        headless: bool = True,
        storage_state_path: str = None,
        safe_mode: bool = True,
        max_states: int = 30,
        max_actions_per_state: int = 12,
        max_action_path_length: int = 5,
        action_timeout_ms: int = 2500,
        cookies: list = None,
        explore_mode: str = "action",  # "action" = 点击所有元素, "menu" = 菜单优先
        auto_close_browser: bool = True,  # False = 手动模式，浏览器保持打开
        flask_api_url: str = "http://localhost:5000",  # 用于注入按钮的API地址
    ):
        self.start_url = start_url
        self.project_id = project_id
        self.auth_token = auth_token
        self.headless = headless
        self.storage_state_path = storage_state_path
        self.safe_mode = safe_mode
        self.cookies = cookies
        self.explore_mode = explore_mode
        self.auto_close_browser = auto_close_browser
        self.flask_api_url = flask_api_url
        import threading
        self._stop_event = threading.Event()  # set by close() to stop manual mode wait
        self.max_states = max_states
        self.max_actions_per_state = max_actions_per_state
        self.max_action_path_length = max_action_path_length
        self.action_timeout_ms = action_timeout_ms
        self.state = VisitedState(project_id=project_id)
        self.graph = FunctionGraph(project_id=project_id)
        self.stats = {
            "pages_visited": 0,
            "states_visited": 0,
            "states_discovered": 0,
            "actions_discovered": 0,
            "actions_executed": 0,
            "actions_skipped": 0,
            "duplicate_states": 0,
            "api_calls_attributed": 0,
            "apis_discovered": 0,
            "functions_discovered": 0,
            "errors": []
        }
        self._browser = None
        self._context = None
        self._page = None
        self._needs_reauth = False
        self._current_action_context = None
        self._action_api_buffer: List[Dict[str, Any]] = []
        self._playwright_available = self._check_playwright()

    @classmethod
    def run_login_helper(
        cls,
        start_url: str,
        done_event,
        timeout_seconds: int = 300,
        auto_detect: bool = False,
    ) -> dict:
        """Open a non-headless Chromium at ``start_url`` and let the user
        log in interactively. Saves ``context.storage_state()`` to
        ``data/storage_states/<sha1>.json`` and returns a result dict.

        The helper auto-detects successful login by polling the page URL:
        once it has been off any ``LOGIN_PATH_PATTERNS`` path for a
        stable period, the session is considered authenticated and the
        helper saves and exits. The ``done_event`` is honoured as a
        manual override (e.g. "我已登录完成" button) and the
        ``timeout_seconds`` is the hard upper bound.
        """
        from playwright.sync_api import sync_playwright
        import time as _time

        target = session_path_for(start_url)
        target.parent.mkdir(parents=True, exist_ok=True)
        result = {
            "path": str(target),
            "saved": False,
            "reason": "unknown",
            "final_url": None,
        }

        def _looks_logged_in(url: str) -> bool:
            if not url:
                return False
            path = urlparse(url.lower()).path
            return not any(p in path for p in LOGIN_PATH_PATTERNS)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            try:
                context = browser.new_context()
                page = context.new_page()
                # Force a logged-out start: clear any leftover cookies /
                # localStorage so the page redirects to its login form,
                # giving the user a window to actually log in.
                # Without this, the page may already be on the post-login
                # dashboard (the browser session still holds cookies),
                # the auto-detect fires immediately, and the window
                # closes in under a second.
                try:
                    from urllib.parse import urlparse
                    start_origin = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
                    context.clear_cookies()
                    page.goto(start_origin, wait_until="domcontentloaded", timeout=15000)
                    page.evaluate("() => { try { window.localStorage.clear(); } catch(e){} }")
                except Exception:
                    pass
                try:
                    page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    result["reason"] = f"initial goto failed: {e}"
                    logger.warning("Login helper initial goto failed: %s", e)

                # Auto-detect: poll URL every 500ms. Once the URL is stable
                # (same value across 2 consecutive samples) AND off any
                # login path, declare success.
                # Disabled by default because on systems where the browser
                # already holds a valid session, the page lands on the
                # dashboard immediately, the loop sees a stable logged-in
                # URL within 1 second, and the window closes before the
                # user can interact. The user must click "我已登录完成"
                # in the Web UI to set done_event.
                deadline = _time.time() + timeout_seconds
                last_url = None
                stable_streak = 0
                while _time.time() < deadline:
                    if done_event.is_set():
                        result["reason"] = "user confirmed"
                        break
                    try:
                        cur = page.url
                    except Exception:
                        cur = last_url
                    result["final_url"] = cur
                    if auto_detect and cur and cur == last_url and _looks_logged_in(cur):
                        stable_streak += 1
                        if stable_streak >= 2:
                            result["reason"] = "auto-detected logged-in URL"
                            break
                    else:
                        stable_streak = 0
                    last_url = cur
                    done_event.wait(timeout=0.5)
                else:
                    if not result["reason"] or result["reason"] == "unknown":
                        result["reason"] = "timeout"

                try:
                    context.storage_state(path=str(target))
                    result["saved"] = True
                except Exception as e:
                    result["reason"] = f"storage_state failed: {e}"
                    logger.error("Failed to save storage_state: %s", e)

                # Also save a small auth.json next to the storage_state
                # file. SPA JWT auth typically lives in localStorage, which
                # storage_state covers, but some apps read the token at
                # boot and set the Authorization header at module scope
                # BEFORE storage_state hydration runs. Saving the raw
                # header as a sidecar lets the next explorer run inject
                # it as a request-level header, which is more reliable.
                try:
                    token = page.evaluate(
                        "() => {"
                        "  const keys = ['token','jwt','access_token','authToken','Authorization','auth','userToken'];"
                        "  for (const k of keys) {"
                        "    const v = localStorage.getItem(k);"
                        "    if (v && typeof v === 'string' && v.length > 8) return v;"
                        "  }"
                        "  try { return sessionStorage.getItem('token') || ''; } catch(e) { return ''; }"
                        "}"
                    )
                    if token and isinstance(token, str) and len(token) > 8:
                        if not token.lower().startswith('bearer '):
                            header_value = f'Bearer {token}'
                        else:
                            header_value = token
                        import json as _json
                        auth_sidecar = Path(str(target) + '.auth.json')
                        auth_sidecar.write_text(
                            _json.dumps({'header_name': 'Authorization', 'header_value': header_value}, ensure_ascii=False, indent=2),
                            encoding='utf-8'
                        )
                        result['auth_header'] = header_value
                        logger.info("Saved Authorization header to %s", auth_sidecar)
                except Exception as e:
                    logger.debug("auth sidecar save failed: %s", e)

                # Also save a cookies sidecar for cookie-based auth such
                # as Admin-Token / sessionid. Pull every cookie from the
                # current context and write them to <sha1>.auth.cookies.json.
                # The next exploration run will load them via
                # context.add_cookies().
                try:
                    cookies = context.cookies()
                    if cookies:
                        import json as _json2
                        cookies_sidecar = Path(str(target) + '.auth.cookies.json')
                        cookies_sidecar.write_text(
                            _json2.dumps(cookies, ensure_ascii=False, indent=2),
                            encoding='utf-8'
                        )
                        result['cookies_saved'] = len(cookies)
                        result['cookies_sidecar'] = str(cookies_sidecar)
                        logger.info("Saved %d cookies to %s", len(cookies), cookies_sidecar)
                except Exception as e:
                    logger.debug("cookies sidecar save failed: %s", e)

                try:
                    page.close()
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
        logger.info("Login helper result: %s", result)
        return result

    def close(self) -> None:
        """Close the browser and unblock the exploration thread (for manual mode)."""
        if self._stop_event:
            self._stop_event.set()
        if self._browser:
            try:
                self._browser.close()
                logger.info("Browser closed manually")
            except Exception as e:
                logger.debug("Browser close error: %s", e)

    def _check_playwright(self) -> bool:
        """Check if Playwright is available."""
        try:
            from playwright.sync_api import sync_playwright
            return True
        except ImportError:
            logger.warning("Playwright not available. Install with: pip install playwright && playwright install chromium")
            return False

    def explore(
        self,
        max_depth: int = 3,
        max_pages: int = 100
    ) -> FunctionGraph:
        """
        Execute real browser exploration.

        Args:
            max_depth: Maximum navigation depth
            max_pages: Maximum pages to visit

        Returns:
            FunctionGraph with discovered functions
        """
        if not self._playwright_available:
            logger.info("Falling back to demo mode")
            demo_explorer = SystemExplorer(self.start_url, self.project_id, self.auth_token)
            return demo_explorer.explore(max_depth, max_pages)

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                logger.info("Launching Chromium headless=%s", self.headless)
                self._browser = p.chromium.launch(headless=self.headless)
                _storage_state = (
                    self.storage_state_path
                    if (self.storage_state_path and Path(self.storage_state_path).exists())
                    else None
                )
                _extra_headers = {}
                if self.auth_token:
                    _extra_headers["Authorization"] = f"Bearer {self.auth_token}"
                if _storage_state:
                    _auth_sidecar = Path(str(self.storage_state_path) + ".auth.json")
                    if _auth_sidecar.exists():
                        try:
                            import json as _json
                            _auth_data = _json.loads(_auth_sidecar.read_text(encoding='utf-8'))
                            _name = _auth_data.get('header_name') or 'Authorization'
                            _extra_headers[_name] = _auth_data.get('header_value') or ''
                            logger.info("Loaded auth sidecar: %s", _name)
                        except Exception as e:
                            logger.debug("auth sidecar load failed: %s", e)
                _cookies_sidecar = None
                if self.storage_state_path:
                    _cookies_sidecar = Path(str(self.storage_state_path) + ".auth.cookies.json")
                _context_already_created = False
                if _cookies_sidecar and _cookies_sidecar.exists():
                    try:
                        import json as _json3
                        from urllib.parse import unquote as _unquote
                        _saved_cookies = _json3.loads(_cookies_sidecar.read_text(encoding='utf-8'))
                        if _saved_cookies:
                            for _c in _saved_cookies:
                                if _c.get('name') == 'Admin-Token':
                                    _raw = _c.get('value') or ''
                                    _tok = _unquote(_raw).strip()
                                    if _tok.lower().startswith('bearer '):
                                        _tok = _tok[7:].strip()
                                    if _tok and 'Authorization' not in _extra_headers:
                                        _extra_headers['Authorization'] = f'Bearer {_tok}'
                                        logger.info("Translated Admin-Token cookie into Authorization header")
                                    break
                            self._context = self._browser.new_context(
                                extra_http_headers=_extra_headers,
                                storage_state=_storage_state,
                            )
                            self._context.add_cookies(_saved_cookies)
                            logger.info("Restored %d cookies from sidecar", len(_saved_cookies))
                            _context_already_created = True
                    except Exception as e:
                        logger.debug("cookies sidecar load failed: %s", e)
                if not _context_already_created:
                    self._context = self._browser.new_context(
                        extra_http_headers=_extra_headers,
                        storage_state=_storage_state,
                    )
                if self.cookies:
                    self._context.add_cookies(self.cookies)
                    logger.info("Added %d cookies from parameter", len(self.cookies))
                self._context.on("request", self._on_request)

                # Pass configuration variables and init script
                api_endpoint = f"{self.flask_api_url.rstrip('/')}/api/explorer/summarize"
                self._context.add_init_script(f"window.__FLASK_API_ENDPOINT__ = '{api_endpoint}';")
                self._context.add_init_script(f"window.__FLASK_URL_FOR_ALERT__ = '{self.flask_api_url}';")

                # Load the button injection script from an external file
                # This avoids Python string parsing issues with quotes and special characters
                button_js = Path(__file__).parent / "button_inject.js"
                if button_js.exists():
                    self._context.add_init_script(path=button_js)
                    logger.info("Loaded button injection script from: %s", button_js)
                else:
                    # Fallback: inline script without emoji and special characters
                    fallback_script = """
(function() {
  function injectClaudeAnalyzeButton() {
    try {
      var existing = document.getElementById('__claude_analyze_btn__');
      if (existing) existing.parentNode.removeChild(existing);
      var existingModal = document.getElementById('__claude_result_modal__');
      if (existingModal) existingModal.parentNode.removeChild(existingModal);
    } catch(e) {}

    var btn = document.createElement('button');
    btn.id = '__claude_analyze_btn__';
    btn.innerHTML = 'Claude 分析';
    btn.style.position = 'fixed';
    btn.style.bottom = '20px';
    btn.style.right = '20px';
    btn.style.zIndex = '2147483647';
    btn.style.background = 'linear-gradient(135deg,#667eea,#764ba2)';
    btn.style.color = '#fff';
    btn.style.border = 'none';
    btn.style.borderRadius = '24px';
    btn.style.padding = '10px 18px';
    btn.style.fontSize = '14px';
    btn.style.fontWeight = '600';
    btn.style.cursor = 'pointer';
    btn.style.boxShadow = '0 4px 16px rgba(102,126,234,.4)';
    btn.style.fontFamily = 'sans-serif';

    btn.onclick = async function() {
      var btn2 = document.getElementById('__claude_analyze_btn__');
      if (btn2) { btn2.disabled = true; btn2.innerHTML = '分析中...'; }

      var data = {
        url: location.href,
        title: document.title,
        headings: Array.from(document.querySelectorAll('h1,h2,h3,h4'))
          .map(function(el) { return el.innerText.trim(); }).filter(Boolean).slice(0, 20),
        forms: Array.from(document.querySelectorAll('form')).map(function(f) {
          return {
            id: f.id, name: f.name,
            inputs: Array.from(f.querySelectorAll('input,select,textarea'))
              .map(function(i) { return {type:i.type,name:i.name,placeholder:i.placeholder}; })
          };
        }),
        buttons: Array.from(document.querySelectorAll('button,input[type=submit]'))
          .map(function(b) { return {tag:b.tagName,text:b.innerText.trim(),id:b.id}; }),
        links: Array.from(document.querySelectorAll('a[href]'))
          .map(function(a) { return {text:a.innerText.trim(),href:a.href}; })
          .filter(function(l) { return l.text && l.href && !l.href.startsWith('javascript'); }),
        apis_known: window.__captured_apis__ || [],
      };

      try {
        var resp = await fetch(window.__FLASK_API_ENDPOINT__, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({manual_page_data: data})
        });
        var result = await resp.json();
        var summary = result.summary || result.error || '无结果';

        var modal = document.getElementById('__claude_result_modal__');
        if (!modal) {
          modal = document.createElement('div');
          modal.id = '__claude_result_modal__';
          modal.style.position = 'fixed';
          modal.style.top = '50%';
          modal.style.left = '50%';
          modal.style.transform = 'translate(-50%,-50%)';
          modal.style.zIndex = '2147483647';
          modal.style.background = '#fff';
          modal.style.borderRadius = '12px';
          modal.style.padding = '20px';
          modal.style.maxWidth = '700px';
          modal.style.width = '90%';
          modal.style.maxHeight = '80vh';
          modal.style.overflow = 'auto';
          modal.style.boxShadow = '0 8px 32px rgba(0,0,0,.3)';
          modal.style.fontFamily = 'sans-serif';
          document.body.appendChild(modal);
        }
        var savedHint = result.analysis_id ? ('<div style=\"margin-bottom:12px;padding:8px 12px;background:#e8f5e9;border-radius:6px;color:#2e7d32;font-size:13px;\">✅ 已保存（ID: ' + result.analysis_id + '）可在项目中查看历史记录</div>') : '';
        modal.innerHTML = '<div style=\"display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;\"><strong style=\"font-size:16px;\">Claude 分析结果</strong><button onclick=\"this.closest(\\'div\\').parentElement.remove()\" style=\"background:#ddd;border:none;border-radius:50%;width:28px;height:28px;cursor:pointer;font-size:16px;line-height:1;\">X</button></div>' + savedHint + '<div style=\"white-space:pre-wrap;line-height:1.6;font-size:14px;color:#333;\">' + summary.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</div>';
      } catch(e) {
        alert('分析失败: ' + e.message + '\\n\\n请确保 Web 应用运行在 ' + window.__FLASK_URL_FOR_ALERT__);
      }

      if (btn2) { btn2.disabled = false; btn2.innerHTML = 'Claude 分析'; }
    };
    document.body.appendChild(btn);
    console.log('[Playwright] Claude analyze button injected');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectClaudeAnalyzeButton);
  } else {
    injectClaudeAnalyzeButton();
  }

  var fire = function() { setTimeout(injectClaudeAnalyzeButton, 500); };
  var wrap = function(k) {
    var orig = history[k];
    history[k] = function() { var r = orig.apply(this, arguments); fire(); return r; };
  };
  wrap('pushState'); wrap('replaceState');
  window.addEventListener('hashchange', fire);
  window.addEventListener('popstate', fire);
})();
"""
                    self._context.add_init_script(fallback_script)
                    logger.info("Using fallback button injection script")

                self._page = self._context.new_page()
                logger.info("Init script added with API endpoint: %s", api_endpoint)

                nav_response = self._page.goto(
                    self.start_url, timeout=30000
                )
                self.stats["pages_visited"] += 1
                if not self._detect_needs_reauth(nav_response, self.start_url):
                    self._wait_for_ui_stable()

                    initial = self._compute_state_hash()
                    self.state.add_to_queue({
                        "state_hash": initial["hash"],
                        "state_info": initial,
                        "url": self._page.url,
                        "depth": 0,
                        "parent_function_id": None,
                        "parent_state_id": None,
                        "action_path": [],
                        "source_action": None,
                    })
                    self.state.queued_state_hashes.add(initial["hash"])
                    self.stats["states_discovered"] += 1
                    self._log(f"Initial state queued: {initial['hash'][:8]} {self._page.url}")

                    if self.auto_close_browser:
                        # Auto mode: process queue then close
                        self._explore_state_queue(max_depth=max_depth, max_pages=max_pages)
                    else:
                        # Manual mode: wait indefinitely for stop signal
                        logger.info("Manual mode: waiting for stop signal...")
                        self._stop_event.wait()
                        logger.info("Manual mode: stop signal received, closing browser")

                if self.auto_close_browser and self._browser:
                    self._browser.close()
                logger.info(f"Playwright exploration complete: {self.stats}")

            except Exception as e:
                logger.error(f"Playwright exploration failed: {e}")
                if self.auto_close_browser and self._browser:
                    self._browser.close()
                # Fallback to demo

        self.state.save_history()
        return self.graph

    def _enqueue_if_new(self, target_url: str, depth: int, parent_id: str, reason: str = "link") -> None:
        """Enqueue a URL only if it's same-origin, normalized, and unseen."""
        from urllib.parse import urljoin, urlparse
        if not target_url:
            return
        # Resolve relative
        if not target_url.startswith("http"):
            target_url = urljoin(self.start_url, target_url)
        parsed = urlparse(target_url)
        base = urlparse(self.start_url)
        if not parsed.netloc or parsed.netloc == base.netloc:
            normalized = self.state.normalize_url(target_url)
            if normalized not in self.state.visited_urls and not any(
                q.get("url") == target_url for q in self.state.pending_queue
            ):
                self.state.add_to_queue({
                    "url": target_url,
                    "depth": depth,
                    "parent": parent_id
                })
                self._log(f"Queued ({reason}, d={depth}): {target_url}")

    def _detect_needs_reauth(self, nav_response, requested_url: str) -> bool:
        """Detect first-hop login redirect or 401/403."""
        final_url = (self._page.url or "").lower() if self._page else ""
        final_path = urlparse(final_url).path
        ended_on_login = any(p in final_path for p in LOGIN_PATH_PATTERNS)
        status = nav_response.status if nav_response else None
        unauthorized = status in (401, 403)
        if ended_on_login or unauthorized:
            self._needs_reauth = True
            reason = (
                f"redirected to login (status={status})"
                if ended_on_login and unauthorized else
                (f"redirected to login ({final_path})" if ended_on_login else f"HTTP {status}")
            )
            self.stats["errors"].append({"url": requested_url, "error": f"needs re-auth: {reason}"})
            self._log(f"Needs re-auth: {reason} at {final_url}")
            return True
        return False

    def _wait_for_ui_stable(self, timeout_ms: Optional[int] = None) -> None:
        """Best-effort wait for SPA UI/network to settle."""
        if not self._page:
            return
        timeout = timeout_ms or self.action_timeout_ms
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except Exception:
            pass
        try:
            self._page.wait_for_load_state("networkidle", timeout=min(timeout, 1500))
        except Exception:
            pass
        try:
            self._page.wait_for_timeout(300)
        except Exception:
            pass

    def _compute_state_hash(self) -> Dict[str, Any]:
        """Compute a stable hash of the visible UI state."""
        if not self._page:
            return {"hash": "missing-page", "signature": {}}
        js = r'''
        () => {
          const visible = (el) => {
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s && s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0;
          };
          const txt = (el) => (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || '').trim().replace(/\s+/g, ' ').slice(0, 120);
          const pick = (sel, limit=30) => Array.from(document.querySelectorAll(sel)).filter(visible).map(txt).filter(Boolean).slice(0, limit);
          return {
            title: document.title || '',
            urlPath: location.pathname,
            urlQueryKeys: Array.from(new URLSearchParams(location.search).keys()).sort(),
            headings: pick('h1,h2,h3,[role="heading"]'),
            dialogs: pick('[role="dialog"], .modal, .drawer, .ant-modal, .ant-drawer, .el-dialog'),
            activeTabs: pick('[role="tab"][aria-selected="true"], .tab.active, .ant-tabs-tab-active, .el-tabs__item.is-active'),
            nav: pick('nav a, aside a, .ant-menu-item, [role="menuitem"]'),
            forms: pick('label, input[placeholder], textarea[placeholder], select'),
            tables: pick('th, [role="columnheader"]'),
            actions: pick('button, [role="button"], a, [role="tab"], [role="menuitem"]', 40),
            counts: {
              buttons: document.querySelectorAll('button,[role="button"]').length,
              links: document.querySelectorAll('a[href]').length,
              forms: document.querySelectorAll('form').length,
              dialogs: document.querySelectorAll('[role="dialog"],.modal,.drawer,.ant-modal,.ant-drawer,.el-dialog').length,
              tables: document.querySelectorAll('table,[role="table"],.ant-table,.el-table').length
            }
          };
        }
        '''
        try:
            signature = self._page.evaluate(js)
        except Exception as e:
            signature = {"error": str(e), "urlPath": urlparse(self._page.url).path}
        payload = json.dumps(signature, ensure_ascii=False, sort_keys=True)
        state_hash = hashlib.sha1(payload.encode("utf-8")).hexdigest()
        return {
            "hash": state_hash,
            "url": self._page.url,
            "title": signature.get("title", ""),
            "signature": signature,
        }

    def _discover_action_candidates(self, state_hash: str, limit: int = None) -> List[ActionCandidate]:
        """Discover visible, replayable action candidates in the current state."""
        if not self._page:
            return []
        limit = limit or self.max_actions_per_state
        candidates = []
        try:
            elements = self._page.query_selector_all(ACTION_SELECTOR)
        except Exception as e:
            self._log(f"Action discovery failed: {e}")
            return []
        for i, elem in enumerate(elements[:80]):
            try:
                info = elem.evaluate(r'''
                (el) => {
                  const s = getComputedStyle(el); const r = el.getBoundingClientRect();
                  const visible = s && s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0;
                  const text = (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || '').trim().replace(/\s+/g, ' ').slice(0, 80);
                  return {
                    visible, tag: el.tagName || '', text,
                    role: el.getAttribute('role') || '', href: el.getAttribute('href') || '',
                    type: el.getAttribute('type') || '', id: el.id || '',
                    testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-cy') || el.getAttribute('data-qa') || '',
                    cls: el.className && typeof el.className === 'string' ? el.className : '',
                    ariaExpanded: el.getAttribute('aria-expanded') || '',
                    ariaHaspopup: el.getAttribute('aria-haspopup') || ''
                  };
                }
                ''')
                if not info.get("visible"):
                    continue
                label = (info.get("text") or info.get("id") or info.get("role") or info.get("tag") or "action").strip()
                selector, selector_type = self._build_stable_selector(info, i)
                action_type = self._classify_action_type(info, label)
                action_id = hashlib.sha1(f"{state_hash}:{selector}:{label}:{action_type}".encode()).hexdigest()[:16]
                candidate = ActionCandidate(
                    action_id=action_id,
                    selector=selector,
                    selector_type=selector_type,
                    label=label[:80],
                    role=info.get("role", ""),
                    tag=info.get("tag", ""),
                    action_type=action_type,
                    href=info.get("href", ""),
                    index=i,
                    metadata={"aria_expanded": info.get("ariaExpanded", ""), "class": info.get("cls", "")[:120]},
                )
                candidate.is_safe, candidate.skip_reason = self._is_safe_action(candidate)
                # Use page_path + label + selector as global dedup key.
                # This ensures each unique element is clicked only once across all sessions.
                current_url = self._page.url if self._page else self.start_url
                page_path = urlparse(current_url).path
                key = f"{page_path}:{candidate.label}:{candidate.selector}"
                if not self.state.mark_action_visited(key):
                    logger.debug("Skipping duplicate action: %s", key)
                    continue
                candidates.append(candidate)
            except Exception:
                continue
        candidates.sort(key=self._action_priority)
        return candidates[:limit]

    def _build_stable_selector(self, info: Dict[str, Any], index: int) -> tuple:
        tag = (info.get("tag") or "*").lower()
        if info.get("testid"):
            value = info["testid"].replace("'", "\\'")
            return f"[data-testid='{value}'],[data-test='{value}'],[data-cy='{value}'],[data-qa='{value}']", "css"
        if info.get("id") and not re.search(r"\d{5,}|[a-f0-9]{8,}", info["id"], re.I):
            return f"#{info['id']}", "css"
        if info.get("role") and info.get("text"):
            return f"{info['role']}:{info['text']}", "role"
        return f"{ACTION_SELECTOR}|||{index}", "nth"

    def _classify_action_type(self, info: Dict[str, Any], label: str) -> str:
        tag = (info.get("tag") or "").lower()
        role = (info.get("role") or "").lower()
        cls = (info.get("cls") or "").lower()
        if tag == "a" and info.get("href"):
            return "link"
        if role == "tab" or "tab" in cls:
            return "tab"
        if role == "menuitem" or "menu" in cls:
            return "menuitem"
        if info.get("ariaHaspopup") or "dropdown" in cls or "select" in cls:
            return "dropdown"
        if "pagination" in cls or "page" in label.lower() or "下一页" in label or "上一页" in label:
            return "table_control"
        if tag == "input" and (info.get("type") or "").lower() == "submit":
            return "form_submit"
        if tag == "button" or role == "button":
            return "button"
        return "unknown_click"

    def _is_safe_action(self, candidate: ActionCandidate) -> tuple:
        text = f"{candidate.label} {candidate.href} {candidate.action_type} {candidate.selector} {candidate.metadata.get('class', '')}".lower()
        if candidate.href and candidate.href.startswith("http"):
            base = urlparse(self.start_url)
            target = urlparse(candidate.href)
            if target.netloc and target.netloc != base.netloc:
                return False, "external link skipped"
        if not self.safe_mode:
            return True, ""
        if any(p.lower() in text for p in DESTRUCTIVE_PATTERNS):
            if not any(p.lower() in text for p in SAFE_ACTION_PATTERNS):
                return False, "safe_mode: possible mutating/destructive action"
        if candidate.action_type == "form_submit" and not any(p.lower() in text for p in SAFE_ACTION_PATTERNS):
            return False, "safe_mode: form submit skipped"
        return True, ""

    def _action_priority(self, candidate: ActionCandidate) -> int:
        order = {"link": 0, "menuitem": 1, "tab": 2, "dropdown": 3, "table_control": 4, "button": 5, "form_submit": 8}
        base = order.get(candidate.action_type, 9)
        if not candidate.is_safe:
            base += 100
        return base

    def _locator_for_action(self, action: Dict[str, Any]):
        if not self._page:
            return None
        stype = action.get("selector_type")
        selector = action.get("selector") or ""
        if stype == "role" and ":" in selector:
            role, name = selector.split(":", 1)
            return self._page.get_by_role(role, name=name).first
        if stype == "nth" and "|||" in selector:
            base, idx = selector.rsplit("|||", 1)
            return self._page.locator(base).nth(int(idx))
        return self._page.locator(selector).first

    def _reset_and_replay(self, action_path: List[Dict[str, Any]]) -> bool:
        if not self._page:
            return False
        try:
            self._page.goto(self.start_url, wait_until="domcontentloaded", timeout=30000)
            self._wait_for_ui_stable()
            for step in action_path[:self.max_action_path_length]:
                loc = self._locator_for_action(step)
                if not loc:
                    return False
                loc.click(timeout=self.action_timeout_ms)
                self._wait_for_ui_stable()
            return True
        except Exception as e:
            self.stats["errors"].append({"url": self.start_url, "error": f"replay failed: {e}"})
            return False

    def _record_state_function(self, state_info: Dict[str, Any], item: Dict[str, Any]) -> FunctionPoint:
        name = state_info.get("title") or urlparse(state_info.get("url", "")).path or "state"
        func = FunctionPoint(
            name=f"{name} [{state_info['hash'][:8]}]",
            description=f"UI state: {state_info.get('url', '')}",
            func_type=FunctionType.PAGE_NAV,
            entry_point=state_info.get("url", ""),
            parent_function_id=item.get("parent_function_id"),
            evidence={
                "source": "playwright-state",
                "state_hash": state_info["hash"],
                "depth": item.get("depth", 0),
                "signature": state_info.get("signature", {}),
                "action_path": item.get("action_path", []),
            }
        )
        self.graph.add_function(func)
        self.stats["functions_discovered"] += 1
        self.stats["states_visited"] += 1
        return func

    def _record_action_function(self, candidate: ActionCandidate, state_func_id: str, result: Dict[str, Any]) -> FunctionPoint:
        func_type = FunctionType.PAGE_NAV if result.get("url_changed") or candidate.action_type == "link" else FunctionType.UI_INTERACTION
        if candidate.action_type == "form_submit":
            func_type = FunctionType.FORM_SUBMIT
        api_urls = [a.get("url", "") for a in result.get("apis", [])]
        func = FunctionPoint(
            name=candidate.label or candidate.action_type,
            description=f"{candidate.action_type}: {candidate.label}",
            func_type=func_type,
            entry_point=candidate.href or candidate.selector,
            parent_function_id=state_func_id,
            related_apis=api_urls,
            evidence={
                "source": "action-crawler",
                "action_id": candidate.action_id,
                "action_type": candidate.action_type,
                "selector": candidate.selector,
                "selector_type": candidate.selector_type,
                "role": candidate.role,
                "tag": candidate.tag,
                "safe_mode": self.safe_mode,
                "is_safe": candidate.is_safe,
                "skip_reason": candidate.skip_reason,
                **result,
            }
        )
        self.graph.add_function(func)
        self.graph.add_edge(state_func_id, func.function_id, "TRIGGERS")
        self.stats["functions_discovered"] += 1
        return func

    def _execute_action_candidate(self, candidate: ActionCandidate, item: Dict[str, Any], state_func_id: str) -> Dict[str, Any]:
        if not candidate.is_safe:
            self.stats["actions_skipped"] += 1
            return {"executed": False, "skipped": True, "skip_reason": candidate.skip_reason, "apis": []}
        if not self._reset_and_replay(item.get("action_path", [])):
            return {"executed": False, "error": "could not replay baseline state", "apis": []}
        before = self._compute_state_hash()
        before_url = self._page.url if self._page else ""
        self._current_action_context = {"action_id": candidate.action_id, "label": candidate.label, "state_hash": before["hash"]}
        self._action_api_buffer = []
        try:
            loc = self._locator_for_action(candidate.to_replay_step())
            loc.click(timeout=self.action_timeout_ms)
            self._wait_for_ui_stable()
            risk = self._dismiss_risky_dialogs()
            after = self._compute_state_hash()
            after_url = self._page.url if self._page else ""
            apis = list(self._action_api_buffer)
            self.stats["actions_executed"] += 1
            if apis:
                self.stats["api_calls_attributed"] += len(apis)
            return {
                "executed": True,
                "url_before": before_url,
                "url_after": after_url,
                "state_before": before["hash"],
                "state_after": after["hash"],
                "state_info_after": after,
                "state_changed": after["hash"] != before["hash"],
                "url_changed": after_url != before_url,
                "apis": apis,
                **risk,
            }
        except Exception as e:
            return {"executed": False, "error": str(e), "apis": []}
        finally:
            self._current_action_context = None
            self._action_api_buffer = []

    def _dismiss_risky_dialogs(self) -> Dict[str, Any]:
        if not self.safe_mode or not self._page:
            return {}
        try:
            text = self._page.locator('[role="dialog"], .ant-modal, .el-dialog').first.inner_text(timeout=500)
            if text and any(p.lower() in text.lower() for p in DESTRUCTIVE_PATTERNS):
                self._page.keyboard.press("Escape")
                return {"dismissed_risky_dialog": True, "dialog_text": text[:200]}
        except Exception:
            pass
        return {}

    def _enqueue_state_if_new(self, state_info: Dict[str, Any], item: Dict[str, Any], action_func: FunctionPoint, candidate: ActionCandidate) -> None:
        state_hash = state_info["hash"]
        if self.state.is_state_seen(state_hash):
            self.stats["duplicate_states"] += 1
            return
        depth = item.get("depth", 0) + 1
        action_path = list(item.get("action_path", [])) + [candidate.to_replay_step()]
        self.state.queued_state_hashes.add(state_hash)
        self.state.add_to_queue({
            "state_hash": state_hash,
            "state_info": state_info,
            "url": state_info.get("url", ""),
            "depth": depth,
            "parent_function_id": action_func.function_id,
            "parent_state_id": item.get("state_hash"),
            "action_path": action_path,
            "source_action": candidate.to_replay_step(),
        })
        self.stats["states_discovered"] += 1
        self._log(f"Queued state {state_hash[:8]} via {candidate.action_type}: {candidate.label}")

    def _explore_state_queue(self, max_depth: int, max_pages: int) -> None:
        state_cap = min(max_pages, self.max_states)
        while self.state.pending_queue and self.stats["states_visited"] < state_cap:
            item = self.state.pending_queue.pop(0)
            if item.get("depth", 0) > max_depth:
                continue
            if not self._reset_and_replay(item.get("action_path", [])):
                continue
            self._wait_for_ui_stable()
            state_info = self._compute_state_hash()
            if not self.state.mark_state_visited(state_info["hash"]):
                self.stats["duplicate_states"] += 1
                continue
            self.state.mark_url_visited(state_info.get("url", ""))
            state_func = self._record_state_function(state_info, item)
            self._log(f"Visited state {state_info['hash'][:8]} depth={item.get('depth', 0)} url={state_info.get('url', '')}")

            if self.explore_mode == "menu":
                self._explore_menu_first(state_func, item)
            else:
                candidates = self._discover_action_candidates(state_info["hash"], self.max_actions_per_state)
                self.stats["actions_discovered"] += len(candidates)
                for candidate in candidates:
                    result = self._execute_action_candidate(candidate, item, state_func.function_id)
                    action_func = self._record_action_function(candidate, state_func.function_id, result)
                    if not result.get("executed"):
                        self._log(f"Skipped action {candidate.action_type}: {candidate.label} ({result.get('skip_reason') or result.get('error', '')})")
                        continue
                    if item.get("depth", 0) < max_depth and result.get("state_changed"):
                        self._enqueue_state_if_new(result["state_info_after"], item, action_func, candidate)
                        self.graph.add_edge(action_func.function_id, result["state_after"], "OPENS_STATE")

    def _explore_menu_first(self, state_func, item: Dict[str, Any]) -> None:
        """Menu-first exploration: click sidebar menu items one by one, then explore each resulting page."""
        menu_selectors = [
            # Ant Design menu
            ".ant-menu-item",
            ".ant-menu-submenu-title",
            ".ant-menu-item:not(.ant-menu-item-disabled)",
            # Element UI menu
            ".el-menu-item",
            ".el-submenu__title",
            # Generic sidebar
            "aside li",
            ".sidebar li",
            "[role='menuitem']",
            # Top-level nav links
            ".nav li",
            "nav li",
        ]
        menu_items = []
        for sel in menu_selectors:
            try:
                els = self._page.query_selector_all(sel)
                for el in els:
                    try:
                        text = (el.inner_text() or "").strip()
                        if text and len(text) < 80:
                            is_visible = el.is_visible()
                            is_disabled = el.get_attribute("aria-disabled") == "true" or "disabled" in (el.get_attribute("class") or "")
                            if is_visible and not is_disabled:
                                menu_items.append((el, text, sel))
                    except Exception:
                        continue
            except Exception:
                continue

        # Deduplicate by text
        seen = set()
        unique_items = []
        for el, text, sel in menu_items:
            if text not in seen:
                seen.add(text)
                unique_items.append((el, text, sel))

        self._log(f"Found {len(unique_items)} menu items on {state_func.entry_point}")
        for el, text, _ in unique_items:
            current_url = self._page.url if self._page else self.start_url
            page_path = urlparse(current_url).path
            key = f"{page_path}:{text}"
            if not self.state.mark_action_visited(key):
                continue

            try:
                el.scroll_into_view_if_needed()
                el.click()
                self._wait_for_ui_stable()
                self._inject_analyze_button()
                self.stats["actions_executed"] += 1

                after_url = self._page.url if self._page else ""
                after_path = urlparse(after_url).path
                self._log(f"Clicked menu: {text} -> {after_path}")

                # Record this menu click as an action
                candidate = ActionCandidate(
                    action_id=f"menu_{len(self.state.visited_action_keys)}",
                    selector="",
                    selector_type="",
                    label=text,
                    role="",
                    tag="",
                    action_type="menuitem",
                    href="",
                    index=0,
                )
                result = {"executed": True, "state_changed": True, "url_after": after_url}
                self._record_action_function(candidate, state_func.function_id, result)

                # Enqueue the new page if URL changed and not already visited
                if after_url and after_url != current_url:
                    normalized = self.state.normalize_url(after_url)
                    if normalized not in self.state.visited_urls:
                        self.state.add_to_queue({
                            "url": after_url,
                            "depth": item.get("depth", 0) + 1,
                            "parent": state_func.function_id,
                        })
                        self._log(f"Queued menu target: {after_path}")
            except Exception as e:
                self._log(f"Failed to click menu '{text}': {e}")

    def _on_request(self, request) -> None:
        """Context-level request listener: capture same-origin XHR/fetch/API calls."""
        try:
            url = request.url
            resource_type = getattr(request, "resource_type", "")
            is_api_like = "/api/" in url or "/rest/" in url or resource_type in ("xhr", "fetch")
            if not is_api_like:
                return
            from urllib.parse import urlparse
            base = urlparse(self.start_url)
            parsed = urlparse(url)
            if parsed.netloc and parsed.netloc != base.netloc:
                return
            normalized = self.state.normalize_api_url(url)
            current = self._current_action_context or {}
            api_event = {
                "url": url,
                "api_pattern": normalized,
                "method": request.method,
                "resource_type": resource_type,
                "discovered_from": self._page.url if self._page else "",
                "action_id": current.get("action_id"),
                "action_label": current.get("label"),
                "state_hash": current.get("state_hash"),
                "timestamp": datetime.now().isoformat()
            }
            if current:
                self._action_api_buffer.append(api_event)
            if normalized in self.state.visited_api_patterns:
                return
            self.state.visited_api_patterns.add(normalized)
            self.graph.api_endpoints.append(api_event)
            self.stats["apis_discovered"] += 1
        except Exception as e:
            logger.debug(f"request listener error: {e}")

    def _explore_spa_from_clicks(self, current_url: str, depth: int, max_depth: int) -> None:
        """Click non-link clickables (buttons, [role=button], nav items) to surface SPA routes."""
        if depth >= max_depth or not self._page:
            return
        try:
            clickables = self._page.query_selector_all(
                "button:not([disabled]), [role='button']:not([aria-disabled='true']), "
                "li[role='menuitem'], .nav-item, .menu-item, .tab, .ant-menu-item"
            )
        except Exception:
            return
        seen_xpath_in_session: set = set()
        for i, elem in enumerate(clickables[:30]):
            try:
                tag = (elem.evaluate("el => el.tagName") or "").upper()
                if tag == "A":
                    continue
                text = (elem.inner_text() or "").strip()[:40]
                xpath = f"//{tag}[{i+1}]"
                if xpath in seen_xpath_in_session:
                    continue
                seen_xpath_in_session.add(xpath)
                url_before = self._page.url
                try:
                    elem.click(timeout=1500)
                except Exception:
                    continue
                # Wait briefly for SPA route change
                try:
                    self._page.wait_for_url(lambda u: u != url_before, timeout=2500)
                except Exception:
                    pass
                new_url = self._page.url
                if new_url and new_url != url_before:
                    self.graph.add_function(FunctionPoint(
                        name=text or f"{tag}_click_{i+1}",
                        description=f"{tag} click → SPA route",
                        func_type=FunctionType.PAGE_NAV,
                        entry_point=new_url,
                        evidence={"source": "spa-click", "tag": tag, "xpath": xpath}
                    ))
                    self.stats["functions_discovered"] += 1
                    self._enqueue_if_new(new_url, depth + 1, None, reason="spa-click")
                # Navigate back so subsequent clicks see the original DOM
                try:
                    self._page.goto(current_url, wait_until="domcontentloaded", timeout=10000)
                except Exception:
                    break
            except Exception:
                continue

    def _extract_functions_from_page(
        self,
        url: str,
        depth: int,
        parent_id: str = None
    ) -> List[FunctionPoint]:
        """Extract function points from current page DOM."""
        functions = []

        try:
            page_title = self._page.title() if self._page else "Unknown"
            path_parts = urlparse(url).path.strip("/").split("/")
            page_name = path_parts[-1] or path_parts[0] if path_parts else "home"

            # Create page navigation function
            page_func = FunctionPoint(
                name=page_title or page_name,
                description=f"Page: {url}",
                func_type=FunctionType.PAGE_NAV,
                entry_point=url,
                parent_function_id=parent_id,
                evidence={"source": "playwright", "title": page_title, "url": url}
            )
            functions.append(page_func)

            if not self._page:
                return functions

            # Extract clickable elements as UI interactions
            try:
                clickables = self._page.query_selector_all("a, button, [role='button'], input[type='submit']")
                for i, elem in enumerate(clickables[:20]):  # Limit to 20 per page
                    try:
                        tag = elem.evaluate("el => el.tagName")
                        text = elem.inner_text().strip()[:50]
                        xpath = elem.get_attribute("data-xpath") or f"//{tag}[{i+1}]"

                        if not self.state.mark_element_visited(xpath):
                            continue

                        # Get href if link
                        href = ""
                        if tag.upper() == "A":
                            href = elem.get_attribute("href") or ""

                        func_type = FunctionType.UI_INTERACTION
                        entry_point = href if href else xpath

                        # Check if it's a navigation link
                        if href and (href.startswith("/") or href.startswith("http")):
                            func_type = FunctionType.PAGE_NAV
                            if href.startswith("/"):
                                from urllib.parse import urljoin
                                entry_point = urljoin(url, href)

                        ui_func = FunctionPoint(
                            name=text or f"{tag}_button_{i+1}",
                            description=f"{tag.upper()} element: {text or 'clickable'}",
                            func_type=func_type,
                            entry_point=str(entry_point),
                            parent_function_id=page_func.function_id,
                            evidence={"source": "dom", "tag": tag, "xpath": xpath}
                        )
                        functions.append(ui_func)
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"Error extracting clickables: {e}")

            # Extract forms as form submit functions
            try:
                forms = self._page.query_selector_all("form")
                for i, form in enumerate(forms[:10]):  # Limit to 10 per page
                    try:
                        form_id = form.get_attribute("id") or f"form_{i+1}"
                        action = form.get_attribute("action") or ""
                        method = form.get_attribute("method") or "GET"

                        form_func = FunctionPoint(
                            name=f"form_submit_{form_id}",
                            description=f"Form submission: {method} {action or url}",
                            func_type=FunctionType.FORM_SUBMIT,
                            entry_point=action or url,
                            parent_function_id=page_func.function_id,
                            parameters={"method": method},
                            evidence={"source": "dom", "form_id": form_id}
                        )
                        functions.append(form_func)
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"Error extracting forms: {e}")

        except Exception as e:
            logger.debug(f"Error extracting functions from page: {e}")

        return functions

    def _capture_api_endpoints(self, source_url: str) -> None:
        """Deprecated: kept for backwards compatibility.

        Network capture is now handled by the context-level ``_on_request``
        listener installed in ``explore()``. Calling this method is a no-op.
        """
        return

    def _log(self, message: str) -> None:
        """Log exploration message."""
        logger.info(message)
        self.graph.exploration_log.append({
            "timestamp": datetime.now().isoformat(),
            "message": message
        })


class SeleniumExplorer:
    """
    Real browser explorer using Selenium WebDriver.

    Alternative to Playwright - use when Selenium is preferred.
    """

    def __init__(
        self,
        start_url: str = "http://localhost:3000",
        project_id: str = "default",
        auth_token: str = None,
        headless: bool = True
    ):
        self.start_url = start_url
        self.project_id = project_id
        self.auth_token = auth_token
        self.headless = headless
        self.state = VisitedState(project_id)
        self.graph = FunctionGraph(project_id=project_id)
        self.stats = {
            "pages_visited": 0,
            "apis_discovered": 0,
            "functions_discovered": 0,
            "errors": []
        }
        self._driver = None
        self._selenium_available = self._check_selenium()

    def _check_selenium(self) -> bool:
        """Check if Selenium is available."""
        try:
            from selenium import webdriver
            return True
        except ImportError:
            logger.warning("Selenium not available. Install with: pip install selenium")
            return False

    def explore(
        self,
        max_depth: int = 3,
        max_pages: int = 100
    ) -> FunctionGraph:
        """Execute Selenium-based exploration."""
        if not self._selenium_available:
            logger.info("Falling back to demo mode")
            demo_explorer = SystemExplorer(self.start_url, self.project_id, self.auth_token)
            return demo_explorer.explore(max_depth, max_pages)

        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options

        try:
            options = Options()
            if self.headless:
                options.add_argument("--headless")
            if self.auth_token:
                options.add_argument(f"--header=Authorization: Bearer {self.auth_token}")

            self._driver = webdriver.Chrome(options=options)
            self._driver.set_page_load_timeout(30)

            # Start exploration
            self.state.add_to_queue({
                "url": self.start_url,
                "depth": 0,
                "parent": None
            })

            while self.state.pending_queue and self.stats["pages_visited"] < max_pages:
                item = self.state.pending_queue.pop(0)
                url = item["url"]
                depth = item["depth"]
                parent_id = item.get("parent")

                if depth > max_depth:
                    continue

                if not self.state.mark_url_visited(url):
                    continue

                try:
                    self._driver.get(url)
                    self.stats["pages_visited"] += 1

                    # Extract functions (simplified - full impl would mirror Playwright)
                    funcs = self._extract_functions_from_selenium(url, depth, parent_id)
                    for f in funcs:
                        self.graph.add_function(f)
                        self.stats["functions_discovered"] += 1

                        if f.func_type == FunctionType.PAGE_NAV and depth < max_depth:
                            self.state.add_to_queue({
                                "url": f.entry_point,
                                "depth": depth + 1,
                                "parent": f.function_id
                            })

                    self._log(f"Visited: {url}")

                except Exception as e:
                    self.stats["errors"].append({"url": url, "error": str(e)})

            self._driver.quit()
            logger.info(f"Selenium exploration complete: {self.stats}")

        except Exception as e:
            logger.error(f"Selenium exploration failed: {e}")
            if self._driver:
                self._driver.quit()

        return self.graph

    def _extract_functions_from_selenium(
        self,
        url: str,
        depth: int,
        parent_id: str = None
    ) -> List[FunctionPoint]:
        """Extract functions using Selenium."""
        functions = []

        try:
            page_title = self._driver.title if self._driver else "Unknown"
            path_parts = urlparse(url).path.strip("/").split("/")
            page_name = path_parts[-1] or path_parts[0] if path_parts else "home"

            page_func = FunctionPoint(
                name=page_title or page_name,
                description=f"Page: {url}",
                func_type=FunctionType.PAGE_NAV,
                entry_point=url,
                parent_function_id=parent_id,
                evidence={"source": "selenium", "title": page_title}
            )
            functions.append(page_func)

        except Exception as e:
            logger.debug(f"Error extracting functions: {e}")

        return functions

    def _log(self, message: str) -> None:
        """Log exploration message."""
        logger.info(message)
        self.graph.exploration_log.append({
            "timestamp": datetime.now().isoformat(),
            "message": message
        })


if __name__ == "__main__":
    # 演示用法
    import sys

    # 命令行接口
    if len(sys.argv) > 1:
        start_url = sys.argv[1]
        depth = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        output = sys.argv[3] if len(sys.argv) > 3 else "function_graph.json"

        print(f"Exploring {start_url} (depth={depth})...")
        explorer = SystemExplorer(start_url=start_url)
        graph = explorer.explore(max_depth=depth)
        explorer.save_to_file(output)
        print(f"Done! Discovered {len(graph.nodes)} functions, {len(graph.api_endpoints)} APIs")
        sys.exit(0)

    # 默认演示
    print("System Explorer Module - Demo")
    explorer = SystemExplorer(start_url="http://localhost:3000/admin/users")
    graph = explorer.explore(max_depth=2)
    print(f"Discovered {len(graph.nodes)} functions")
    print(graph.to_json())