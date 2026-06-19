"""
Web UI for Multi-Agent AI Test Engineer System

A simple Flask-based web interface for the test case generation system.
"""
import json
import logging
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, render_template, request, jsonify, session
from src.orchestrator.workflow import Orchestrator
from src.memory.storage import MemoryStorage
from src.adapters.llm_adapter import LLMAdapter

# Configure logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "system.log"

# File handler for logging
file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s'
))

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'test-engineer-secret-key-2024'
app.config['JSON_AS_ASCII'] = False
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True

# ==================== Analysis History Storage ====================
# Analysis results are stored as JSON files in data/analysis_history/
ANALYSIS_HISTORY_DIR = Path(__file__).parent / "data" / "analysis_history"
ANALYSIS_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

def _save_analysis_result(analysis_type: str, url: str, summary: str, raw_data: dict, stats: dict = None) -> str:
    """Save analysis result to a timestamped JSON file. Returns the analysis ID."""
    import uuid
    analysis_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().isoformat()

    result = {
        "id": analysis_id,
        "type": analysis_type,  # "manual" or "graph"
        "url": url,
        "summary": summary,
        "raw_data": raw_data,
        "stats": stats or {},
        "created_at": timestamp,
    }

    file_path = ANALYSIS_HISTORY_DIR / f"{analysis_id}.json"
    try:
        file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Analysis result saved: {file_path}")
    except Exception as e:
        logger.error(f"Failed to save analysis result: {e}")

    return analysis_id

def _list_analysis_history(limit: int = 50) -> list:
    """List all analysis history, sorted by most recent first."""
    results = []
    try:
        for file_path in sorted(ANALYSIS_HISTORY_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                # Return simplified version for listing
                results.append({
                    "id": data.get("id", file_path.stem),
                    "type": data.get("type", "unknown"),
                    "url": data.get("url", ""),
                    "summary_preview": (data.get("summary", "") or "")[:150] + "...",
                    "created_at": data.get("created_at", ""),
                    "stats": data.get("stats", {}),
                })
                if len(results) >= limit:
                    break
            except Exception as e:
                logger.debug(f"Failed to read {file_path}: {e}")
                continue
    except Exception as e:
        logger.error(f"Failed to list analysis history: {e}")
    return results

def _get_analysis_detail(analysis_id: str) -> Optional[dict]:
    """Get full details of a specific analysis result."""
    file_path = ANALYSIS_HISTORY_DIR / f"{analysis_id}.json"
    if not file_path.exists():
        return None
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to read analysis {analysis_id}: {e}")
        return None

def _delete_analysis(analysis_id: str) -> bool:
    """Delete an analysis result."""
    file_path = ANALYSIS_HISTORY_DIR / f"{analysis_id}.json"
    if not file_path.exists():
        return False
    try:
        file_path.unlink()
        logger.info(f"Analysis deleted: {analysis_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete analysis {analysis_id}: {e}")
        return False

# Add CORS headers manually (no external dependency)
# The injected '发送给Claude' button in Playwright browser needs to
# call back to this Flask server from a different origin (e.g., dbq.asptest.yiye.ai)
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Initialize storage
storage = MemoryStorage()

# Store orchestrator instances per session
orchestrators = {}


def get_orchestrator():
    """Get or create orchestrator for current session."""
    session_id = session.get('session_id', 'default')
    if session_id not in orchestrators:
        orchestrators[session_id] = Orchestrator(memory_storage=storage)
    return orchestrators[session_id]


@app.route('/')
def index():
    """Main page."""
    return render_template('index.html')


@app.route('/api/requirement/preview', methods=['POST'])
def preview_requirement():
    """Run a lightweight PM analysis on a requirement and return
    the parsed structure plus the list of ambiguous/edge-case points
    that the user should confirm before generating full test cases.

    Request body:
    { "requirement": "...", "extra_notes": "..." }

    Response:
    {
      "status": "success",
      "parsed": { ... full PM output ... },
      "ambiguous_points": [ { "question": "...", "context": "..." } ],
      "summary": "1-3 sentence summary of the parsed requirement"
    }
    """
    try:
        data = request.get_json() or {}
        requirement = (data.get('requirement') or '').strip()
        extra_notes = (data.get('extra_notes') or '').strip()
        if not requirement:
            return jsonify({'error': 'requirement is required'}), 400

        from src.adapters.llm_adapter import LLMAdapter
        llm = LLMAdapter()

        # Single, controlled JSON-only call. This avoids PM Agent's strict
        # schema validation (which can fail when the LLM returns plain text
        # from the CLI) and produces a stable response shape for the UI.
        prompt = (
            "你是一个资深测试工程师。用户提供了以下需求，请完成两件事：\n"
            "1. 用 1 句话概述这个需求的核心目的（summary）\n"
            "2. 列出 3-7 个**在测试中容易遗漏/边界值/灰色地带**的注意事项\n\n"
            "要求：\n"
            "- 每条问题要简洁、明确、可勾选（用户可回答：待确认/按通用/不需要/自定义）\n"
            "- 不要问开放性问题，不要问已知信息\n"
            "- category 必须是以下之一：边界值、权限、异常、业务规则、性能、兼容性、其他\n"
            "- context 是给用户的提示文字，说明该问题为何重要（不超过 50 字）\n\n"
            f"需求：\n{requirement}\n\n"
            + (f"用户补充说明：\n{extra_notes}\n\n" if extra_notes else "")
            + "请严格用以下 JSON 格式返回（不要任何其他内容、不要 markdown 代码块、不要换行包裹）：\n"
            '{"summary": "<一句话需求概述>",'
            '"ambiguous_points": ['
            '{"question": "...", "context": "...", "category": "边界值|权限|异常|业务规则|性能|兼容性|其他"}'
            ']}'
        )
        result = llm.generate_structured(
            system_prompt="你只输出 JSON，不要任何解释或前后缀。",
            user_message=prompt,
        )

        if not isinstance(result, dict):
            # Defensive: if for any reason we didn't get a dict, synthesize an
            # empty-but-valid response so the UI still works.
            result = {'summary': '', 'ambiguous_points': []}

        ambiguous_points = []
        for q in (result.get('ambiguous_points') or []):
            if isinstance(q, dict) and q.get('question'):
                ambiguous_points.append({
                    'question': str(q.get('question', '')).strip(),
                    'context': str(q.get('context', '')).strip(),
                    'category': str(q.get('category', 'general')).strip() or 'general',
                })
            elif isinstance(q, str) and q.strip():
                ambiguous_points.append({
                    'question': q.strip(),
                    'context': '',
                    'category': 'general',
                })

        summary = str(result.get('summary') or '').strip()[:500]

        return jsonify({
            'status': 'success',
            'parsed': {'summary': summary, 'ambiguous_points': ambiguous_points},
            'ambiguous_points': ambiguous_points,
            'summary': summary,
            'has_error': False,
            'error': None,
        })
    except Exception as e:
        logger.error("Error previewing requirement: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/requirement', methods=['POST'])
def process_requirement():
    """Process a requirement and generate test cases.

    Request body:
    {
      "requirement": "<natural language requirement>",
      "frontend_context": [<manual picks, optional>],
      "backend_context":  [<manual picks, optional>],
      "extra_notes":      "<free-form text to supplement logic>",
      "auto_context":     true,   # default true: auto-match KB by keywords
      "edge_confirmations": [       # answers to the previewed ambiguous points
        { "question": "...", "answer": "..." }, ...
      ]
    }
    """
    try:
        data = request.get_json()
        requirement = data.get('requirement', '')
        frontend_context = list(data.get('frontend_context') or [])
        backend_context = list(data.get('backend_context') or [])
        extra_notes = (data.get('extra_notes') or '').strip()
        auto_context = bool(data.get('auto_context', True))
        edge_confirmations = list(data.get('edge_confirmations') or [])
        tech_review_notes = (data.get('tech_review_notes') or '').strip()
        tech_review_confirmed = bool(data.get('tech_review_confirmed', False))
        tech_review_payload = data.get('tech_review_payload') or {}

        if not requirement:
            return jsonify({'error': 'Requirement is required'}), 400

        # Auto-match KB items by keyword extraction from the requirement text
        auto_fe = []
        auto_be = []
        if auto_context:
            auto_fe, auto_be = _auto_match_kb_context(requirement)

        # Merge auto + manual, dedup by stable key
        def _dedup_fe(manual, auto):
            seen = set()
            out = []
            for item in manual + auto:
                key = item.get('component', {}).get('name', '') + '|' + item.get('project', '')
                if key in seen:
                    continue
                seen.add(key)
                out.append(item)
            return out

        def _dedup_be(manual, auto):
            seen = set()
            out = []
            for item in manual + auto:
                if item.get('type') == 'api':
                    key = 'api|' + (item.get('api', {}).get('path', '') + '|' + item.get('api', {}).get('method', ''))
                elif item.get('type') == 'service':
                    key = 'service|' + item.get('service', {}).get('name', '')
                elif item.get('type') == 'entity':
                    key = 'entity|' + item.get('entity', {}).get('name', '')
                else:
                    key = json.dumps(item, sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                out.append(item)
            return out

        merged_fe = _dedup_fe(frontend_context, auto_fe)
        merged_be = _dedup_be(backend_context, auto_be)

        # Build enriched prompt
        sections = [requirement]
        if edge_confirmations:
            sections.append(
                "## 流程控制要求\n"
                "本次需求已经经过前置的 AI 边界分析与用户确认。后续 PM/FE/BE/QA 不应再因为一般边界不明确而中断流程。"
                "如果仍有未明确点，请将其作为“待确认风险/待确认测试场景”写入测试用例和证据链，而不是返回 needs_clarification。"
            )
        if extra_notes:
            sections.append(
                "## 用户补充的额外说明（人工提供，需要在测试用例/证据链中体现）\n"
                + extra_notes
            )
        if edge_confirmations:
            qa_lines = []
            for item in edge_confirmations:
                if not isinstance(item, dict):
                    continue
                q = (item.get('question') or '').strip()
                a = (item.get('answer') or '').strip()
                if not q or not a:
                    continue
                qa_lines.append(f"- 边界问题：{q}\n  用户确认：{a}")
            if qa_lines:
                sections.append(
                    "## 需求边界确认（用户已逐条回答，需要在测试用例/证据链中体现）\n"
                    + "\n".join(qa_lines)
                )
        if tech_review_confirmed or tech_review_notes or tech_review_payload:
            review_section = {
                'confirmed': tech_review_confirmed,
                'review_notes': tech_review_notes,
                'ai_tech_review': tech_review_payload,
            }
            sections.append(
                "## FE/BE 技术审核结果（用户已人工审核，生成测试用例时必须参考）\n"
                + json.dumps(review_section, ensure_ascii=False, indent=2)
            )

        if merged_fe or merged_be:
            context_payload = {
                'frontend_selected_knowledge': merged_fe,
                'backend_selected_knowledge': merged_be,
                '_meta': {
                    'auto_fe_count': len(auto_fe),
                    'auto_be_count': len(auto_be),
                    'manual_fe_count': len(frontend_context),
                    'manual_be_count': len(backend_context),
                },
            }
            sections.append(
                "## 知识库上下文（自动匹配 + 人工选择，FE/BE 分析时优先参考）\n"
                + json.dumps(context_payload, ensure_ascii=False, indent=2)
            )
        enriched_requirement = "\n\n".join(sections)

        orchestrator = get_orchestrator()
        result = orchestrator.run(enriched_requirement)

        # After the new preflight boundary-confirmation flow, the final submit
        # should produce test cases. If PM still asks generic clarification
        # questions, auto-answer them as "treat as confirmed risk" and continue.
        if result.get('status') == 'needs_clarification' and (edge_confirmations or tech_review_confirmed):
            auto_answers = [
                {
                    'question': q,
                    'answer': '按前置边界确认和技术审核结果处理；若仍不明确，请作为待确认风险/待确认测试场景写入测试用例。'
                }
                for q in result.get('questions', [])
            ]
            logger.info("Auto-continuing after PM clarification with %d answers", len(auto_answers))
            clarified_requirement = (
                enriched_requirement
                + "\n\n## PM 追加澄清（系统根据前置确认自动继续）\n"
                + json.dumps(auto_answers, ensure_ascii=False, indent=2)
                + "\n\n请不要再次中断流程，必须继续生成测试用例。"
            )
            result = orchestrator.run(clarified_requirement)

        result['selected_frontend_context'] = merged_fe
        result['selected_backend_context'] = merged_be
        result['auto_matched'] = {
            'frontend_count': len(auto_fe),
            'backend_count': len(auto_be),
        }
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error processing requirement: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


def _auto_match_kb_context(requirement: str):
    """Auto-pick FE components and BE APIs/services/entities based on
    keyword extraction from the requirement text.

    Strategy: pull Chinese + English tokens, then rank KB items by token
    overlap. Cap results to keep prompt size manageable.
    """
    import re

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_/-]{2,}|[一-鿿]{2,}", requirement)
    tokens_lc = [t.lower() for t in tokens if len(t) >= 2]
    # Dedupe while preserving order
    seen = set()
    uniq_tokens = []
    for t in tokens_lc:
        if t not in seen:
            seen.add(t)
            uniq_tokens.append(t)
    if not uniq_tokens:
        return [], []

    auto_fe = []
    auto_be = []

    try:
        from src.knowledge.fe_knowledge import get_knowledge_base
        kb = get_knowledge_base()
        scored = []
        for proj_name, proj_data in kb.data.get("projects", {}).items():
            for c in proj_data.get("components", []):
                name = (c.get("name") or "").lower()
                fp = (c.get("file_path") or "").lower()
                imports = " ".join(c.get("imports") or []).lower()
                haystack = " ".join([name, fp, imports])
                score = sum(haystack.count(t) for t in uniq_tokens)
                if score > 0:
                    scored.append((score, proj_name, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        for score, proj_name, c in scored[:10]:
            auto_fe.append({
                "type": "component",
                "component": c,
                "project": proj_name,
                "score": score,
                "auto_matched": True,
            })
    except Exception as e:
        logger.debug("auto FE match failed: %s", e)

    try:
        from src.knowledge.be_knowledge import get_backend_knowledge_base
        bk = get_backend_knowledge_base()

        # APIs
        api_scored = []
        for it in bk.data.get("apis", []) or []:
            haystack = " ".join([
                (it.get("path") or ""),
                (it.get("class_name") or ""),
                (it.get("method_name") or ""),
                (it.get("method") or ""),
            ]).lower()
            score = sum(haystack.count(t) for t in uniq_tokens)
            if score > 0:
                api_scored.append((score, it))
        api_scored.sort(key=lambda x: x[0], reverse=True)
        for score, it in api_scored[:10]:
            auto_be.append({
                "type": "api",
                "api": it,
                "score": score,
                "auto_matched": True,
            })

        # Services
        svc_scored = []
        for it in bk.data.get("services", []) or []:
            haystack = " ".join([
                (it.get("name") or ""),
                (it.get("file_path") or ""),
                " ".join(it.get("methods") or []),
            ]).lower()
            score = sum(haystack.count(t) for t in uniq_tokens)
            if score > 0:
                svc_scored.append((score, it))
        svc_scored.sort(key=lambda x: x[0], reverse=True)
        for score, it in svc_scored[:5]:
            auto_be.append({
                "type": "service",
                "service": it,
                "score": score,
                "auto_matched": True,
            })

        # Entities
        ent_scored = []
        for it in bk.data.get("entities", []) or []:
            haystack = " ".join([
                (it.get("name") or ""),
                (it.get("file_path") or ""),
                (it.get("table_name") or ""),
            ]).lower()
            score = sum(haystack.count(t) for t in uniq_tokens)
            if score > 0:
                ent_scored.append((score, it))
        ent_scored.sort(key=lambda x: x[0], reverse=True)
        for score, it in ent_scored[:5]:
            auto_be.append({
                "type": "entity",
                "entity": it,
                "score": score,
                "auto_matched": True,
            })
    except Exception as e:
        logger.debug("auto BE match failed: %s", e)

    return auto_fe, auto_be


@app.route('/api/requirement/tech-review', methods=['POST'])
def preview_tech_review():
    """Generate FE/BE technical review based on requirement + edge confirmations
    + auto-matched KB context. This is reviewed by the user before running the
    full test-case generation workflow.
    """
    try:
        data = request.get_json() or {}
        requirement = (data.get('requirement') or '').strip()
        extra_notes = (data.get('extra_notes') or '').strip()
        edge_confirmations = list(data.get('edge_confirmations') or [])
        auto_context = bool(data.get('auto_context', True))
        if not requirement:
            return jsonify({'error': 'requirement is required'}), 400

        auto_fe, auto_be = _auto_match_kb_context(requirement) if auto_context else ([], [])

        # Slim context to keep prompt under control
        fe_slim = []
        for item in auto_fe[:10]:
            c = item.get('component', {})
            fe_slim.append({
                'project': item.get('project'),
                'name': c.get('name'),
                'file_path': c.get('file_path'),
                'type': c.get('type'),
                'props': c.get('props', [])[:10],
                'imports': c.get('imports', [])[:20],
                'api_calls': c.get('api_calls', [])[:20],
                'score': item.get('score'),
            })
        be_slim = []
        for item in auto_be[:20]:
            if item.get('type') == 'api':
                a = item.get('api', {})
                be_slim.append({
                    'type': 'api', 'method': a.get('method'), 'path': a.get('path'),
                    'class_name': a.get('class_name'), 'method_name': a.get('method_name'),
                    'file_path': a.get('file_path'), 'parameters': a.get('parameters', [])[:10],
                    'request_body': a.get('request_body'), 'response_type': a.get('response_type'),
                    'score': item.get('score'),
                })
            elif item.get('type') == 'service':
                s = item.get('service', {})
                be_slim.append({
                    'type': 'service', 'name': s.get('name'), 'file_path': s.get('file_path'),
                    'methods': s.get('methods', [])[:20], 'dependencies': s.get('dependencies', [])[:20],
                    'score': item.get('score'),
                })
            elif item.get('type') == 'entity':
                e = item.get('entity', {})
                be_slim.append({
                    'type': 'entity', 'name': e.get('name'), 'file_path': e.get('file_path'),
                    'table_name': e.get('table_name'), 'fields': e.get('fields', [])[:30],
                    'score': item.get('score'),
                })

        from src.adapters.llm_adapter import LLMAdapter
        llm = LLMAdapter()
        prompt = f"""你是资深测试架构师，需要在正式生成测试用例前做一次 FE/BE 技术审核。

## 需求
{requirement}

## 用户补充说明
{extra_notes or '无'}

## 已确认的需求边界
{json.dumps(edge_confirmations, ensure_ascii=False, indent=2)}

## 自动匹配到的 FE 知识库上下文
{json.dumps(fe_slim, ensure_ascii=False, indent=2)}

## 自动匹配到的 BE 知识库上下文
{json.dumps(be_slim, ensure_ascii=False, indent=2)}

请输出 JSON，字段如下：
{{
  "summary": "一句话总结本次技术审核结论",
  "frontend_review": {{
    "affected_components": ["组件名/文件路径/影响说明"],
    "ui_states": ["需要关注的页面状态/交互状态"],
    "frontend_risks": ["前端风险/边界"],
    "suggested_checks": ["前端测试检查点"]
  }},
  "backend_review": {{
    "affected_apis": ["METHOD path - 影响说明"],
    "services_entities": ["Service/Entity/表/字段影响"],
    "backend_risks": ["后端风险/边界"],
    "suggested_checks": ["后端测试检查点"]
  }},
  "integration_review": ["前后端联调/数据一致性/错误码/权限/性能等检查点"],
  "needs_manual_attention": ["必须由人工审核确认的点"]
}}

要求：只返回 JSON，不要 markdown，不要解释。"""
        review = llm.generate_structured(
            system_prompt="你只输出 JSON。",
            user_message=prompt,
        )
        if not isinstance(review, dict):
            review = {
                'summary': '',
                'frontend_review': {},
                'backend_review': {},
                'integration_review': [],
                'needs_manual_attention': [],
            }
        return jsonify({
            'status': 'success',
            'review': review,
            'matched_context': {
                'frontend': fe_slim,
                'backend': be_slim,
                'totals': {'frontend': len(auto_fe), 'backend': len(auto_be)},
            },
        })
    except Exception as e:
        logger.error("Error generating tech review: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/requirement/auto-context', methods=['POST'])
def preview_auto_context():
    """Preview what the auto-matcher will pick for a given requirement, without
    actually running the orchestrator. Useful for showing the user the matches
    before they submit."""
    try:
        data = request.get_json() or {}
        requirement = (data.get('requirement') or '').strip()
        if not requirement:
            return jsonify({'error': 'requirement is required'}), 400
        auto_fe, auto_be = _auto_match_kb_context(requirement)
        # Compact summaries
        def _fe_slim(item):
            c = item.get('component', {})
            return {
                'project': item.get('project'),
                'name': c.get('name'),
                'file_path': c.get('file_path'),
                'type': c.get('type'),
                'score': item.get('score'),
            }
        def _be_slim(item):
            if item.get('type') == 'api':
                a = item['api']
                return {'type': 'api', 'method': a.get('method'), 'path': a.get('path'),
                        'class_name': a.get('class_name'), 'file_path': a.get('file_path'), 'score': item.get('score')}
            if item.get('type') == 'service':
                s = item['service']
                return {'type': 'service', 'name': s.get('name'), 'file_path': s.get('file_path'), 'score': item.get('score')}
            if item.get('type') == 'entity':
                e = item['entity']
                return {'type': 'entity', 'name': e.get('name'), 'file_path': e.get('file_path'), 'score': item.get('score')}
            return item
        return jsonify({
            'status': 'success',
            'frontend': [_fe_slim(x) for x in auto_fe],
            'backend': [_be_slim(x) for x in auto_be],
            'totals': {
                'frontend': len(auto_fe),
                'backend': len(auto_be),
            },
        })
    except Exception as e:
        logger.error("Error previewing auto context: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/clarification', methods=['POST'])
def provide_clarification():
    """Provide clarification answers."""
    try:
        data = request.get_json()
        answers = data.get('answers', [])

        if not answers:
            return jsonify({'error': 'Answers are required'}), 400

        orchestrator = get_orchestrator()
        result = orchestrator.provide_clarification(answers)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error providing clarification: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
def get_stats():
    """Get memory storage statistics."""
    try:
        stats = storage.get_stats()
        try:
            from src.knowledge.fe_knowledge import get_knowledge_base
            from src.knowledge.be_knowledge import get_backend_knowledge_base
            fe_summary = get_knowledge_base().get_project_summary()
            be_summary = get_backend_knowledge_base().get_summary()
            stats['frontend_components'] = fe_summary.get('total_components', 0)
            stats['backend_apis'] = be_summary.get('total_apis', 0)
            stats['backend_services'] = be_summary.get('total_services', 0)
            stats['backend_entities'] = be_summary.get('total_entities', 0)
        except Exception as kb_error:
            logger.warning(f"Knowledge base stats unavailable: {kb_error}")
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/history')
def get_history():
    """Get conversation history."""
    try:
        history = storage.get_conversation_history(limit=50)
        return jsonify(history)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reset', methods=['POST'])
def reset_workflow():
    """Reset the workflow state."""
    try:
        session_id = session.get('session_id', 'default')
        if session_id in orchestrators:
            orchestrators[session_id].reset()
        return jsonify({'status': 'reset'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/knowledge/search', methods=['GET'])
def search_knowledge():
    """Search components/APIs in knowledge base."""
    try:
        query = request.args.get('q', '')
        query_type = request.args.get('type', 'all')  # all, components, apis, services, entities
        limit = int(request.args.get('limit', 20))

        if not query:
            return jsonify({'error': 'Query is required'}), 400

        results = {'query': query, 'type': query_type}

        if query_type in ['all', 'components']:
            from src.knowledge.fe_knowledge import get_knowledge_base
            kb = get_knowledge_base()
            results['components'] = kb.search_components(query, limit=limit)

        if query_type in ['all', 'apis', 'services', 'entities']:
            from src.knowledge.be_knowledge import get_backend_knowledge_base
            bk = get_backend_knowledge_base()
            if query_type in ['all', 'apis']:
                results['apis'] = bk.search_apis(query, limit=limit)
            if query_type in ['all', 'services']:
                results['services'] = bk.search_services(query, limit=limit)
            if query_type in ['all', 'entities']:
                results['entities'] = bk.search_entities(query, limit=limit)

        return jsonify(results)

    except Exception as e:
        logger.error(f"Error searching knowledge: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/knowledge/summary', methods=['GET'])
def knowledge_summary():
    """Get frontend/backend knowledge base summary."""
    try:
        from src.knowledge.fe_knowledge import get_knowledge_base
        from src.knowledge.be_knowledge import get_backend_knowledge_base
        return jsonify({
            'frontend': get_knowledge_base().get_project_summary(),
            'backend': get_backend_knowledge_base().get_summary(),
        })
    except Exception as e:
        logger.error(f"Error loading knowledge summary: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ==================== Source Code Browser API ====================

@app.route('/api/sourcecode/list', methods=['GET'])
def sourcecode_list():
    """List all frontend components grouped by project. Optional filters: project, type, query."""
    try:
        from src.knowledge.fe_knowledge import get_knowledge_base
        kb = get_knowledge_base()
        data = getattr(kb, "data", {}) or {}

        project_filter = request.args.get('project', '').strip() or None
        type_filter = request.args.get('type', '').strip().lower() or None
        query = request.args.get('query', '').strip().lower() or None
        limit = int(request.args.get('limit', 500))

        projects_out = []
        total = 0
        projects = data.get("projects", {})
        for proj_name, proj_data in projects.items():
            if project_filter and proj_name != project_filter:
                continue
            comps_in = proj_data.get("components", [])
            comps_out = []
            for c in comps_in:
                if type_filter:
                    ctype = (c.get("type") or "").lower()
                    if ctype != type_filter:
                        continue
                if query:
                    name = (c.get("name") or "").lower()
                    fp = (c.get("file_path") or "").lower()
                    if query not in name and query not in fp:
                        continue
                comps_out.append({
                    "name": c.get("name"),
                    "file_path": c.get("file_path"),
                    "type": c.get("type"),
                    "props_count": len(c.get("props") or []),
                    "imports_count": len(c.get("imports") or []),
                    "api_calls_count": len(c.get("api_calls") or []),
                })
                if len(comps_out) >= limit:
                    break
            if comps_out:
                total += len(comps_out)
                projects_out.append({
                    "project_name": proj_name,
                    "project_path": proj_data.get("project_path"),
                    "file_count": proj_data.get("file_count"),
                    "components": comps_out,
                })

        return jsonify({
            "status": "success",
            "total": total,
            "projects": projects_out,
            "available_types": _get_known_component_types(),
        })
    except Exception as e:
        logger.error("Error listing source code: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/sourcecode/detail', methods=['GET'])
def sourcecode_detail():
    """Get full detail of one component by project + component name, plus file content if exists."""
    try:
        from src.knowledge.fe_knowledge import get_knowledge_base
        project = request.args.get('project', '').strip()
        name = request.args.get('name', '').strip()
        if not project or not name:
            return jsonify({"error": "project and name are required"}), 400

        kb = get_knowledge_base()
        detail = kb.get_component_details(name, project=project)
        if not detail:
            return jsonify({"error": "component not found"}), 404

        component = detail.get("component", {})
        file_path = component.get("file_path", "")
        file_content = None
        file_exists = False
        file_size = 0
        truncated = False
        if file_path:
            try:
                p = Path(file_path)
                if p.exists() and p.is_file():
                    file_exists = True
                    file_size = p.stat().st_size
                    with open(p, 'r', encoding='utf-8', errors='replace') as f:
                        lines = f.readlines()
                    if len(lines) > 200:
                        truncated = True
                        file_content = ''.join(lines[:200])
                    else:
                        file_content = ''.join(lines)
            except Exception as e:
                logger.debug("Failed to read file %s: %s", file_path, e)

        return jsonify({
            "status": "success",
            "component": {
                "name": component.get("name"),
                "file_path": file_path,
                "type": component.get("type"),
                "props": component.get("props", []),
                "imports": component.get("imports", []),
                "api_calls": component.get("api_calls", []),
                "exports": component.get("exports", []),
            },
            "file": {
                "exists": file_exists,
                "size": file_size,
                "truncated": truncated,
                "content": file_content,
            },
            "project": project,
        })
    except Exception as e:
        logger.error("Error getting component detail: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/sourcecode/file', methods=['GET'])
def sourcecode_file():
    """Read a registered source file's content with line range."""
    try:
        from src.knowledge.fe_knowledge import get_knowledge_base
        project = request.args.get('project', '').strip()
        file_path = request.args.get('path', '').strip()
        max_lines = int(request.args.get('max_lines', 500))
        if not file_path:
            return jsonify({"error": "path is required"}), 400

        # Security: only allow files that exist in the knowledge base
        kb = get_knowledge_base()
        if project:
            proj = kb.data.get("projects", {}).get(project, {})
            registered = {
                c.get("file_path") for c in proj.get("components", []) if c.get("file_path")
            }
            if registered and file_path not in registered:
                return jsonify({"error": "file not in knowledge base"}), 403

        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return jsonify({"error": "file not found", "path": file_path}), 404

        with open(p, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        total = len(lines)
        truncated = total > max_lines
        content = ''.join(lines[:max_lines])

        return jsonify({
            "status": "success",
            "path": file_path,
            "total_lines": total,
            "returned_lines": min(max_lines, total),
            "truncated": truncated,
            "content": content,
        })
    except Exception as e:
        logger.error("Error reading source file: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


def _get_known_component_types() -> list:
    """Return a sorted list of unique component types in the KB."""
    try:
        from src.knowledge.fe_knowledge import get_knowledge_base
        types = set()
        for proj_data in get_knowledge_base().data.get("projects", {}).values():
            for c in proj_data.get("components", []):
                t = c.get("type")
                if t:
                    types.add(t)
        return sorted(types)
    except Exception:
        return []


# ==================== Backend Source Code Browser API ====================

@app.route('/api/sourcecode-be/list', methods=['GET'])
def sourcecode_be_list():
    """List backend KB items. category in {apis,services,entities,repositories,all}."""
    try:
        from src.knowledge.be_knowledge import get_backend_knowledge_base
        bk = get_backend_knowledge_base()
        category = (request.args.get('category', 'all').strip().lower() or 'all')
        query = (request.args.get('query', '').strip().lower() or None)
        method_filter = (request.args.get('method', '').strip().upper() or None)
        limit = int(request.args.get('limit', 200))

        result = {}
        categories = ['apis', 'services', 'entities', 'repositories'] if category == 'all' else [category]
        for cat in categories:
            items = bk.data.get(cat, []) or []
            out = []
            for it in items:
                if method_filter and cat == 'apis':
                    if (it.get('method') or '').upper() != method_filter:
                        continue
                if query:
                    haystack = ' '.join([
                        str(it.get('name', '')),
                        str(it.get('path', '')),
                        str(it.get('file_path', '')),
                        str(it.get('class_name', '')),
                        str(it.get('method_name', '')),
                        str(it.get('table_name', '')),
                        str(it.get('entity_type', '')),
                    ]).lower()
                    if query not in haystack:
                        continue
                summary = _be_item_summary(cat, it)
                out.append(summary)
                if len(out) >= limit:
                    break
            result[cat] = {
                'total': len(items),
                'returned': len(out),
                'items': out,
            }

        # project meta
        result['_meta'] = {
            'project_name': bk.data.get('project_name'),
            'project_path': bk.data.get('project_path'),
            'file_count': bk.data.get('file_count'),
            'created_at': bk.data.get('created_at'),
        }
        return jsonify({'status': 'success', 'data': result})
    except Exception as e:
        logger.error("Error listing backend source code: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


def _be_item_summary(category: str, item: dict) -> dict:
    """Build a compact summary dict for a backend KB item."""
    if category == 'apis':
        return {
            'id': f"{item.get('method','')}:{item.get('path','')}",
            'name': item.get('path', ''),
            'method': item.get('method', ''),
            'class_name': item.get('class_name', ''),
            'method_name': item.get('method_name', ''),
            'file_path': item.get('file_path', ''),
            'response_type': item.get('response_type', ''),
            'has_request_body': bool(item.get('request_body')),
        }
    if category == 'services':
        methods = item.get('methods', []) or []
        return {
            'id': item.get('name', ''),
            'name': item.get('name', ''),
            'file_path': item.get('file_path', ''),
            'method_count': len(methods),
            'dependency_count': len(item.get('dependencies', []) or []),
        }
    if category == 'repositories':
        return {
            'id': item.get('name', ''),
            'name': item.get('name', ''),
            'file_path': item.get('file_path', ''),
            'entity_type': item.get('entity_type', ''),
            'table_name': item.get('table_name', ''),
        }
    if category == 'entities':
        fields = item.get('fields', []) or []
        return {
            'id': item.get('name', ''),
            'name': item.get('name', ''),
            'file_path': item.get('file_path', ''),
            'table_name': item.get('table_name', ''),
            'field_count': len(fields),
        }
    return {'id': str(item), 'name': str(item)}


@app.route('/api/sourcecode-be/detail', methods=['GET'])
def sourcecode_be_detail():
    """Get full detail of one backend KB item + read its source file."""
    try:
        from src.knowledge.be_knowledge import get_backend_knowledge_base
        bk = get_backend_knowledge_base()

        category = (request.args.get('category', '').strip().lower() or '')
        item_id = request.args.get('id', '').strip()
        if not category or not item_id:
            return jsonify({"error": "category and id are required"}), 400
        if category not in ('apis', 'services', 'entities', 'repositories'):
            return jsonify({"error": f"unsupported category: {category}"}), 400

        items = bk.data.get(category, []) or []
        target = None
        if category == 'apis':
            try:
                method, path = item_id.split(':', 1)
            except ValueError:
                return jsonify({"error": "id must be METHOD:path"}), 400
            for it in items:
                if (it.get('method') or '').upper() == method.upper() and it.get('path') == path:
                    target = it
                    break
        else:
            for it in items:
                if it.get('name') == item_id:
                    target = it
                    break
        if not target:
            return jsonify({"error": "item not found"}), 404

        file_path = target.get('file_path', '')
        file_content = None
        file_exists = False
        file_size = 0
        truncated = False
        if file_path:
            try:
                p = Path(file_path)
                if p.exists() and p.is_file():
                    file_exists = True
                    file_size = p.stat().st_size
                    with open(p, 'r', encoding='utf-8', errors='replace') as f:
                        lines = f.readlines()
                    if len(lines) > 200:
                        truncated = True
                        file_content = ''.join(lines[:200])
                    else:
                        file_content = ''.join(lines)
            except Exception as e:
                logger.debug("Failed to read backend file %s: %s", file_path, e)

        return jsonify({
            'status': 'success',
            'category': category,
            'item': target,
            'file': {
                'exists': file_exists,
                'size': file_size,
                'truncated': truncated,
                'content': file_content,
            },
        })
    except Exception as e:
        logger.error("Error getting backend detail: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/explorer', methods=['POST'])
def explore_system():
    """
    Explore a target system URL and build function graph.

    Request body:
    {
        "url": "https://dbq.asptest.yiye.ai/pmp/landing-page?type=pmp&advertiserGroupId=113",
        "max_depth": 3,
        "max_pages": 100,
        "engine": "playwright" | "selenium" | "simple" (default: "playwright"),
        "storage_state_path": "optional/data/storage_states/<sha1>.json",
        "safe_mode": true,
        "max_states": 30,
        "max_actions_per_state": 12,
        "cookies": [{"name": "...", "value": "...", "domain": "...", "path": "/"}, ...],
        "headless": false,
        "explore_mode": "action" | "menu" (default: "action")
    }
    """
    try:
        data = request.get_json()
        start_url = data.get('url', 'https://dbq.asptest.yiye.ai/pmp/landing-page?type=pmp&advertiserGroupId=113')
        max_depth = int(data.get('max_depth', 3))
        max_pages = int(data.get('max_pages', 100))
        engine = data.get('engine', 'playwright')
        storage_state_path = data.get('storage_state_path')
        safe_mode = bool(data.get('safe_mode', True))
        max_states = int(data.get('max_states', min(max_pages, 30)))
        max_actions_per_state = int(data.get('max_actions_per_state', 12))
        cookies = data.get('cookies')  # list of dicts: [{name, value, domain, path}, ...]
        headless = bool(data.get('headless', True))  # False to show browser
        explore_mode = data.get('explore_mode', 'action')  # 'action' or 'menu'

        max_depth = max(1, min(max_depth, 5))
        max_pages = max(1, min(max_pages, 100))
        max_states = max(1, min(max_states, 50))
        max_actions_per_state = max(1, min(max_actions_per_state, 20))

        if not start_url:
            return jsonify({'error': 'URL is required'}), 400

        logger.info(f"Starting {engine} exploration for {start_url}")

        if engine == 'puppeteer':
            explorer_js = Path(__file__).parent / 'src' / 'knowledge' / 'system_explorer.js'
            output_dir = Path(__file__).parent / 'data' / 'explorer'
            output_dir.mkdir(parents=True, exist_ok=True)
            cmd = [
                'node', str(explorer_js),
                '--url', start_url,
                '--maxDepth', str(max_depth),
                '--maxPages', str(max_pages),
                '--outputDir', str(output_dir),
                '--safeMode', 'true' if safe_mode else 'false',
            ]
            if storage_state_path:
                cmd.extend(['--sessionPath', storage_state_path])
            executable_path = os.environ.get('PUPPETEER_EXECUTABLE_PATH')
            if executable_path:
                cmd.extend(['--executablePath', executable_path])
            # text=True + explicit utf-8 + errors='replace' so the CJK bytes
            # the Node child prints (Claude CLI returns Chinese names) don't
            # fail on Windows default GBK codec.
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=600,
            )
            raw = proc.stdout if proc.returncode == 0 else proc.stderr or proc.stdout
            if raw is None:
                raw = ''
            try:
                node_result = json.loads(raw)
            except Exception:
                raise RuntimeError(f'Puppeteer explorer failed: {raw[-1000:]}')
            if proc.returncode == 2 or node_result.get('status') == 'needs_reauth':
                return jsonify({
                    'status': 'needs_reauth',
                    'url': start_url,
                    'engine': engine,
                    'stats': {'pages_visited': 0, 'functions_discovered': 0, 'apis_discovered': 0, 'errors': [node_result.get('error')]},
                    'graph': {'nodes': [], 'edges': [], 'api_endpoints': [], 'exploration_log': []},
                    'needs_reauth': True,
                    'storage_state_path': storage_state_path,
                })
            functions = node_result.get('functions', [])
            api_seen = {}
            nodes = []
            for fn in functions:
                nodes.append({
                    'function_id': fn.get('id'),
                    'name': fn.get('name'),
                    'description': fn.get('text') or fn.get('type'),
                    'type': 'FORM_SUBMIT' if fn.get('type') == 'form' else ('PAGE_NAV' if fn.get('type') == 'link' else 'UI_INTERACTION'),
                    'entry_point': fn.get('xpath') or fn.get('normalized_url'),
                    'related_apis': [api.get('url') for api in fn.get('apis', [])],
                    'parameters': fn.get('payload_schema') or fn.get('parameters') or {},
                    'parent_function_id': fn.get('parent'),
                    'evidence': fn,
                })
                for api in fn.get('apis', []):
                    api_seen[api.get('fingerprint') or api.get('url')] = api
            return jsonify({
                'status': 'success',
                'url': start_url,
                'engine': engine,
                'stats': {
                    'pages_visited': node_result.get('stats', {}).get('pagesVisited', 0),
                    'states_visited': node_result.get('stats', {}).get('statesVisited', 0),
                    'states_discovered': node_result.get('stats', {}).get('statesDiscovered', 0),
                    'actions_discovered': node_result.get('stats', {}).get('actionsDiscovered', len(functions)),
                    'actions_executed': node_result.get('stats', {}).get('actionsExecuted', 0),
                    'actions_skipped': node_result.get('stats', {}).get('actionsSkipped', 0),
                    'duplicate_states': node_result.get('stats', {}).get('duplicateStates', 0),
                    'api_calls_attributed': node_result.get('stats', {}).get('apiCallsAttributed', 0),
                    'functions_discovered': node_result.get('stats', {}).get('functionsDiscovered', len(functions)),
                    'apis_discovered': node_result.get('stats', {}).get('apisDiscovered', len(api_seen)),
                    'errors': node_result.get('stats', {}).get('errors', []),
                },
                'graph': {
                    'nodes': nodes,
                    'edges': [],
                    'api_endpoints': list(api_seen.values()),
                    'exploration_log': [],
                },
                'needs_reauth': False,
                'storage_state_path': storage_state_path,
                'output': node_result.get('output', {}),
            })
        elif engine == 'playwright':
            from src.knowledge.explorer import PlaywrightExplorer
            explorer = PlaywrightExplorer(
                start_url=start_url,
                storage_state_path=storage_state_path,
                safe_mode=safe_mode,
                max_states=max_states,
                max_actions_per_state=max_actions_per_state,
                cookies=cookies,
                headless=headless,
                explore_mode=explore_mode,
            )
        elif engine == 'selenium':
            from src.knowledge.explorer import SeleniumExplorer
            explorer = SeleniumExplorer(start_url=start_url)
        else:
            from src.knowledge.explorer import SimpleBrowserExplorer
            explorer = SimpleBrowserExplorer(start_url=start_url)

        graph = explorer.explore(max_depth=max_depth, max_pages=max_pages)

        needs_reauth = bool(getattr(explorer, '_needs_reauth', False))
        return jsonify({
            'status': 'needs_reauth' if needs_reauth else 'success',
            'url': start_url,
            'engine': engine,
            'stats': explorer.stats,
            'graph': graph.to_dict(),
            'needs_reauth': needs_reauth,
            'storage_state_path': storage_state_path,
            'limits': {
                'max_depth': max_depth,
                'max_pages': max_pages,
                'max_states': max_states,
                'max_actions_per_state': max_actions_per_state,
                'safe_mode': safe_mode,
            },
        })

    except Exception as e:
        logger.error(f"Error exploring system: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# --- Non-blocking manual explorer (browser stays open, user clicks manually) ---
import threading, uuid

_explorer_sessions = {}  # session_id -> {explorer, stats, graph, done, error}


@app.route('/api/explorer/start', methods=['POST'])
def explorer_start():
    """
    Start a non-blocking browser exploration.
    Browser stays open; user manually navigates and clicks the '发送给Claude分析' button.
    Returns session_id immediately.
    """
    try:
        data = request.get_json() or {}
        start_url = data.get('url', 'https://dbq.asptest.yiye.ai/pmp/landing-page?type=pmp&advertiserGroupId=113')
        cookies = data.get('cookies')
        max_depth = int(data.get('max_depth', 3))
        max_pages = int(data.get('max_pages', 100))
        explore_mode = data.get('explore_mode', 'menu')
        headless = False  # Always non-headless for manual mode
        flask_api_url = request.host_url.rstrip('/') if request else 'http://localhost:5000'

        session_id = str(uuid.uuid4())
        session = {
            'done': False,
            'error': None,
            'stats': {'pages_visited': 0, 'states_visited': 0, 'apis_discovered': 0, 'actions_executed': 0},
            'graph': None,
            'explorer': None,
        }
        _explorer_sessions[session_id] = session

        def _run():
            from src.knowledge.explorer import PlaywrightExplorer
            try:
                explorer = PlaywrightExplorer(
                    start_url=start_url,
                    headless=headless,
                    cookies=cookies,
                    explore_mode=explore_mode,
                    auto_close_browser=False,
                    flask_api_url=flask_api_url,
                    max_states=100,
                    max_actions_per_state=12,
                )
                session['explorer'] = explorer
                graph = explorer.explore(max_depth=max_depth, max_pages=max_pages)
                session['graph'] = graph.to_dict()
                session['stats'] = explorer.stats
            except Exception as e:
                logger.error("Explorer session %s failed: %s", session_id, e)
                session['error'] = str(e)
            finally:
                session['done'] = True

        thread = threading.Thread(target=_run, daemon=True)
        session['thread'] = thread
        thread.start()

        return jsonify({
            'status': 'started',
            'session_id': session_id,
            'url': start_url,
            'message': '浏览器已启动，请在打开的窗口中手动浏览，完成后调用 /api/explorer/stop 结束',
        })
    except Exception as e:
        logger.error("Error starting explorer: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/explorer/status/<session_id>', methods=['GET'])
def explorer_status(session_id):
    """Poll the status of a non-blocking explorer session."""
    session = _explorer_sessions.get(session_id)
    if not session:
        return jsonify({'error': 'session not found'}), 404
    return jsonify({
        'done': session['done'],
        'error': session['error'],
        'stats': session['stats'],
    })


@app.route('/api/explorer/stop', methods=['POST'])
def explorer_stop():
    """Stop a non-blocking explorer session and return final results."""
    try:
        data = request.get_json() or {}
        session_id = data.get('session_id')
        session = _explorer_sessions.get(session_id)
        if not session:
            return jsonify({'error': 'session not found'}), 404

        # Close the browser if still running (triggers thread to exit)
        explorer = session.get('explorer')
        if explorer:
            explorer.close()
            # Wait for thread to finish
            t = session.get('thread')
            if t:
                t.join(timeout=10)

        return jsonify({
            'status': 'done',
            'session_id': session_id,
            'stats': session['stats'],
            'graph': session.get('graph') or {'nodes': [], 'edges': [], 'api_endpoints': []},
        })
    except Exception as e:
        logger.error("Error stopping explorer: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


# --- Manual login helper (one-shot non-headless Chromium session) ---

import threading
import uuid
from src.knowledge.explorer import session_path_for

_login_helpers = {}  # helper_id -> {"event": Event, "thread": Thread, "url": str, "path": str|None}


@app.route('/api/explorer/login-helper', methods=['POST'])
def explorer_login_helper():
    """Spawn a non-headless browser at start_url so the user can log in.
    Returns helper_id immediately; the helper auto-detects successful
    login and saves storage_state on its own. The /done and /cancel
    routes let the user force completion or abort early.
    """
    try:
        data = request.get_json() or {}
        start_url = data.get('url')
        if not start_url:
            return jsonify({'error': 'url is required'}), 400
        target_path = session_path_for(start_url)
        helper_id = str(uuid.uuid4())
        event = threading.Event()

        def _run():
            from src.knowledge.explorer import PlaywrightExplorer
            try:
                result = PlaywrightExplorer.run_login_helper(
                    start_url=start_url,
                    done_event=event,
                    timeout_seconds=300,
                    auto_detect=False,
                )
                _login_helpers[helper_id]["result"] = result
                _login_helpers[helper_id]["path"] = result.get("path")
            except Exception as e:
                logger.error("Login helper failed: %s", e, exc_info=True)
                _login_helpers[helper_id]["error"] = str(e)

        thread = threading.Thread(target=_run, daemon=True)
        _login_helpers[helper_id] = {
            "event": event,
            "thread": thread,
            "url": start_url,
            "path": None,
            "result": None,
            "error": None,
        }
        thread.start()
        return jsonify({
            "status": "started",
            "helper_id": helper_id,
            "url": start_url,
            "storage_state_path": str(target_path),
        })
    except Exception as e:
        logger.error("Error starting login helper: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/explorer/login-helper/<helper_id>/done', methods=['POST'])
def explorer_login_helper_done(helper_id):
    """Signal that the user finished logging in. Returns the helper
    result (saved/reason/final_url) once the thread writes it (capped
    to 10s)."""
    entry = _login_helpers.get(helper_id)
    if not entry:
        return jsonify({'error': 'unknown helper_id'}), 404
    entry["event"].set()
    entry["thread"].join(timeout=10)
    result = entry.get("result") or {}
    return jsonify({
        "status": "saved" if result.get("saved") else "no_save",
        "helper_id": helper_id,
        "url": entry["url"],
        "storage_state_path": result.get("path") or entry.get("path"),
        "saved": result.get("saved", False),
        "reason": result.get("reason"),
        "final_url": result.get("final_url"),
        "error": entry.get("error"),
    })


@app.route('/api/explorer/login-helper/<helper_id>/status', methods=['GET'])
def explorer_login_helper_status(helper_id):
    """Read-only status — does not signal done. Useful for polling."""
    entry = _login_helpers.get(helper_id)
    if not entry:
        return jsonify({'error': 'unknown helper_id'}), 404
    result = entry.get("result") or {}
    thread = entry.get("thread")
    return jsonify({
        "helper_id": helper_id,
        "url": entry["url"],
        "running": bool(thread and thread.is_alive()),
        "saved": bool(result.get("saved")),
        "final_url": result.get("final_url"),
        "reason": result.get("reason"),
        "error": entry.get("error"),
    })


@app.route('/api/explorer/login-helper/<helper_id>/cancel', methods=['POST'])
def explorer_login_helper_cancel(helper_id):
    """Best-effort cancel: signal done so the helper exits early."""
    entry = _login_helpers.pop(helper_id, None)
    if not entry:
        return jsonify({'error': 'unknown helper_id'}), 404
    entry["event"].set()
    return jsonify({"status": "cancelled", "helper_id": helper_id})


@app.route('/api/explorer/auth-save', methods=['POST'])
def explorer_auth_save():
    """Persist a manually-supplied JWT (or any Authorization header value)
    as the auth sidecar for the target URL. Subsequent exploration runs
    will inject this header at the network layer, so JWT-authenticated
    SPAs stay logged in even if localStorage hydration races."""
    try:
        data = request.get_json() or {}
        start_url = data.get('url', '').strip()
        header_value = (data.get('header_value') or data.get('auth_token') or '').strip()
        header_name = (data.get('header_name') or 'Authorization').strip() or 'Authorization'
        if not start_url or not header_value:
            return jsonify({'error': 'url and header_value are required'}), 400
        target = session_path_for(start_url)
        target.parent.mkdir(parents=True, exist_ok=True)
        sidecar = Path(str(target) + '.auth.json')
        sidecar.write_text(
            json.dumps({'header_name': header_name, 'header_value': header_value}, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        return jsonify({
            'status': 'saved',
            'storage_state_path': str(target),
            'auth_sidecar': str(sidecar),
        })
    except Exception as e:
        logger.error("Error saving auth sidecar: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/explorer/demo', methods=['GET'])
def explore_demo():
    """
    Run a demo exploration (simple mode without real browser).
    """
    try:
        url = request.args.get('url', 'http://localhost:3000')
        depth = int(request.args.get('depth', 2))

        from src.knowledge.explorer import SystemExplorer
        explorer = SystemExplorer(start_url=url)
        graph = explorer.explore(max_depth=depth, max_pages=50)

        return jsonify({
            'status': 'success',
            'url': url,
            'engine': 'demo',
            'stats': explorer.stats,
            'graph': graph.to_dict()
        })
    except Exception as e:
        logger.error(f"Error in demo exploration: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/explorer/cookie-save', methods=['POST'])
def explorer_cookie_save():
    """Persist a single cookie (e.g. Admin-Token) as a sidecar so
    subsequent exploration runs send it on every request. body:
      { url, name, value, domain?, path?, httpOnly?, secure?, sameSite? }
    """
    try:
        data = request.get_json() or {}
        start_url = data.get('url', '').strip()
        name = (data.get('name') or '').strip() or 'Admin-Token'
        value = (data.get('value') or '').strip()
        if not start_url or not value:
            return jsonify({'error': 'url and value are required'}), 400
        target = session_path_for(start_url)
        target.parent.mkdir(parents=True, exist_ok=True)
        sidecar = Path(str(target) + '.auth.cookies.json')
        existing = []
        if sidecar.exists():
            try:
                existing = json.loads(sidecar.read_text(encoding='utf-8'))
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []
        from urllib.parse import urlparse as _urlparse
        host = data.get('domain') or _urlparse(start_url).netloc
        path = data.get('path') or '/'
        cookie = {
            'name': name,
            'value': value,
            'domain': host,
            'path': path,
            'httpOnly': bool(data.get('httpOnly', False)),
            'secure': bool(data.get('secure', False)),
            'sameSite': data.get('sameSite') or 'Lax',
        }
        existing = [c for c in existing if c.get('name') != name]
        existing.append(cookie)
        sidecar.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        return jsonify({
            'status': 'saved',
            'storage_state_path': str(target),
            'cookies_sidecar': str(sidecar),
            'cookie': cookie,
        })
    except Exception as e:
        logger.error("Error saving cookie sidecar: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/explorer/summarize', methods=['POST'])
def summarize_exploration():
    """
    Send exploration graph or manual page data to Claude for summarization.
    Request body:
      - 探索结果: { graph: {nodes, api_endpoints, edges}, url, description }
      - 手动页面: { manual_page_data: {url, title, headings, forms, buttons, links}, description }
    """
    try:
        data = request.get_json() or {}
        manual_data = data.get('manual_page_data')
        graph = data.get('graph', {})
        url = data.get('url', '')
        description = data.get('description', '')

        from src.adapters.llm_adapter import LLMAdapter
        llm = LLMAdapter()

        # Mode 1: 手动页面数据（用户在浏览器中点击按钮）
        if manual_data:
            page_url = manual_data.get('url', '')
            headings = manual_data.get('headings', [])
            forms = manual_data.get('forms', [])
            buttons = manual_data.get('buttons', [])
            links = manual_data.get('links', [])
            captured_apis = manual_data.get('apis_known', [])

            prompt = f"""你是一个专业的系统分析师。请分析当前页面并总结其功能。

当前页面URL: {page_url}

## 页面标题
{manual_data.get('title', '')}

## 页面标题元素 (Headings)
{chr(10).join(f"- {h}" for h in headings) if headings else '无'}

## 表单 (Forms)
"""
            for form in forms:
                inputs = form.get('inputs', [])
                prompt += f"- 表单 (id={form.get('id')}, name={form.get('name')}): {len(inputs)} 个输入字段\n"
                for inp in inputs[:10]:
                    prompt += f"  - {inp.get('type', 'text')} {inp.get('name', '')} placeholder={inp.get('placeholder', '')}\n"

            prompt += f"""
## 按钮 (Buttons)
{chr(10).join(f"- {b.get('tag')} {b.get('text', '')[:50]}" for b in buttons[:20]) if buttons else '无'}

## 链接 (Links)
{chr(10).join(f"- {l.get('text', '')[:40]} -> {l.get('href', '')[:80]}" for l in links[:20]) if links else '无'}

## 请分析并总结：
1. 这个页面是什么功能模块？
2. 主要的用户交互元素有哪些？
3. 表单的作用是什么？
4. 有哪些关键的导航链接？

请用中文回答，条理清晰。
"""
            response = llm.generate(
                system_prompt="你是一个专业的系统分析师。",
                user_message=prompt
            )
            if response.error:
                return jsonify({'error': response.error}), 500

            # Save analysis result to history
            analysis_id = _save_analysis_result(
                analysis_type="manual",
                url=page_url,
                summary=response.content,
                raw_data={
                    "title": manual_data.get("title", ""),
                    "headings": headings,
                    "forms_count": len(forms),
                    "buttons_count": len(buttons),
                    "links_count": len(links),
                    "apis_count": len(captured_apis),
                },
                stats={
                    "headings": len(headings),
                    "forms": len(forms),
                    "buttons": len(buttons),
                    "links": len(links),
                    "apis": len(captured_apis),
                }
            )
            return jsonify({
                'status': 'success',
                'summary': response.content,
                'mode': 'manual',
                'analysis_id': analysis_id
            })

        # Mode 2: 探索图数据（批量探索结果）
        nodes = graph.get('nodes', [])
        apis = graph.get('api_endpoints', [])
        edges = graph.get('edges', [])

        prompt = f"""你是一个专业的系统探索分析师。请分析以下网页探索结果，并总结该系统的功能和结构。

目标URL: {url}
探索说明: {description}

## 发现的页面/功能节点 ({len(nodes)} 个)
"""
        for i, node in enumerate(nodes):
            ev = node.get('evidence', {})
            sig = ev.get('signature', {})
            prompt += f"""
### {i+1}. {node.get('name', 'Unknown')}
- 类型: {node.get('type', '')}
- 入口: {node.get('entry_point', '')}
- 动作: {', '.join(sig.get('actions', [])) or '无'}
- 表单: {', '.join(sig.get('forms', [])) or '无'}
"""

        prompt += f"""
## 发现的API端点 ({len(apis)} 个)
"""
        seen_urls = set()
        for api in apis:
            url_key = api.get('url', '')
            if url_key in seen_urls:
                continue
            seen_urls.add(url_key)
            prompt += f"\n### {api.get('method', 'GET')} {api.get('url', 'Unknown')}"

        prompt += """
## 请分析并总结：
1. 该系统的主要功能模块有哪些？
2. 核心业务流程是什么？
3. 每个模块的关键 API 是哪些？
4. 表单和用户交互流程是怎样的？

请用中文回答，条理清晰。
"""
        response = llm.generate(
            system_prompt="你是一个专业的系统探索分析师。",
            user_message=prompt
        )
        if response.error:
            return jsonify({'error': response.error}), 500

        # Save analysis result to history
        analysis_stats = {'nodes': len(nodes), 'apis': len(apis), 'edges': len(edges)}
        analysis_id = _save_analysis_result(
            analysis_type="graph",
            url=url,
            summary=response.content,
            raw_data={
                "description": description,
                "nodes_count": len(nodes),
                "apis_count": len(apis),
                "edges_count": len(edges),
            },
            stats=analysis_stats
        )
        return jsonify({
            'status': 'success',
            'summary': response.content,
            'stats': analysis_stats,
            'mode': 'graph',
            'analysis_id': analysis_id
        })

    except Exception as e:
        logger.error("Error summarizing exploration: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


# ==================== Analysis History API ====================

@app.route('/api/analysis/history', methods=['GET'])
def get_analysis_history():
    """List all analysis history, most recent first."""
    try:
        limit = int(request.args.get('limit', 50))
        results = _list_analysis_history(limit=limit)
        return jsonify({
            'status': 'success',
            'total': len(results),
            'results': results
        })
    except Exception as e:
        logger.error("Error getting analysis history: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/analysis/<analysis_id>', methods=['GET'])
def get_analysis_detail(analysis_id):
    """Get full details of a specific analysis result."""
    try:
        result = _get_analysis_detail(analysis_id)
        if not result:
            return jsonify({'error': 'Analysis not found'}), 404
        return jsonify({
            'status': 'success',
            'result': result
        })
    except Exception as e:
        logger.error("Error getting analysis detail: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/analysis/<analysis_id>', methods=['DELETE'])
def delete_analysis(analysis_id):
    """Delete a specific analysis result."""
    try:
        if _delete_analysis(analysis_id):
            return jsonify({'status': 'success', 'message': 'Analysis deleted'})
        return jsonify({'error': 'Analysis not found'}), 404
    except Exception as e:
        logger.error("Error deleting analysis: %s", e, exc_info=True)
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("Starting Web UI...")
    print("Open http://localhost:5000 in your browser")
    app.run(host='0.0.0.0', port=5000, debug=False)


# ==================== Document Upload API ====================

@app.route('/api/documents/upload', methods=['POST'])
def upload_document():
    """
    Upload and process a document for the knowledge base.

    Accepts file uploads via multipart/form-data.
    """
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'No file selected'}), 400

        # Save uploaded file temporarily
        upload_dir = Path(__file__).parent / "data" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        temp_path = upload_dir / file.filename
        file.save(str(temp_path))

        # Process the document
        from src.knowledge.document_processor import get_document_processor, get_search_index
        processor = get_document_processor()
        search_index = get_search_index()

        doc = processor.process_file(str(temp_path))
        if not doc:
            return jsonify({'error': 'Failed to process document'}), 400

        # Add to search index
        search_index.add_document(doc)

        # Also save to document storage
        processor.save_document(doc)

        # Clean up temp file
        temp_path.unlink()

        return jsonify({
            'status': 'success',
            'document': doc.to_dict()
        })

    except Exception as e:
        logger.error(f"Error uploading document: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/documents/search', methods=['GET'])
def search_documents():
    """
    Search documents in the knowledge base.

    Query params:
    - q: Search query
    - limit: Max results (default 10)
    - file_type: Filter by file type
    """
    try:
        query = request.args.get('q', '')
        limit = int(request.args.get('limit', 10))
        file_type = request.args.get('file_type')

        if not query:
            return jsonify({'error': 'Query is required'}), 400

        from src.knowledge.document_processor import get_search_index
        search_index = get_search_index()

        results = search_index.search(query, limit=limit, file_type=file_type)

        return jsonify({
            'query': query,
            'results': results,
            'total': len(results)
        })

    except Exception as e:
        logger.error(f"Error searching documents: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/documents', methods=['GET'])
def list_documents():
    """List all indexed documents."""
    try:
        from src.knowledge.document_processor import get_search_index
        search_index = get_search_index()

        docs = [
            {
                "doc_id": doc_id,
                "filename": doc.get("filename"),
                "file_type": doc.get("file_type"),
                "extracted_at": doc.get("extracted_at")
            }
            for doc_id, doc in search_index.documents.items()
        ]

        return jsonify({
            'documents': docs,
            'total': len(docs)
        })

    except Exception as e:
        logger.error(f"Error listing documents: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/documents/<doc_id>', methods=['GET'])
def get_document(doc_id):
    """Get a specific document by ID."""
    try:
        from src.knowledge.document_processor import get_search_index
        search_index = get_search_index()

        doc = search_index.documents.get(doc_id)
        if not doc:
            return jsonify({'error': 'Document not found'}), 404

        return jsonify({'document': doc})

    except Exception as e:
        logger.error(f"Error getting document: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    """Delete a document from the knowledge base."""
    try:
        from src.knowledge.document_processor import get_search_index
        search_index = get_search_index()

        if search_index.delete_document(doc_id):
            return jsonify({'status': 'deleted', 'doc_id': doc_id})
        else:
            return jsonify({'error': 'Document not found'}), 404

    except Exception as e:
        logger.error(f"Error deleting document: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/documents/stats', methods=['GET'])
def document_stats():
    """Get document index statistics."""
    try:
        from src.knowledge.document_processor import get_search_index
        search_index = get_search_index()
        return jsonify(search_index.get_stats())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== Impact Analysis API ====================

@app.route('/api/impact/analyze', methods=['POST'])
def analyze_impact():
    """
    Analyze the impact of a requirement change.

    Request body:
    {
        "requirement": { ... parsed requirement from PM ... },
        "requirement_id": "optional ID"
    }
    """
    try:
        data = request.get_json()
        requirement = data.get('requirement', {})
        requirement_id = data.get('requirement_id')

        if not requirement:
            return jsonify({'error': 'Requirement is required'}), 400

        from src.knowledge.impact_analyzer import ImpactAnalyzer
        from src.knowledge.fe_knowledge import get_knowledge_base
        from src.knowledge.be_knowledge import get_backend_knowledge_base

        analyzer = ImpactAnalyzer(
            fe_knowledge_base=get_knowledge_base(),
            be_knowledge_base=get_backend_knowledge_base()
        )

        report = analyzer.analyze_requirement(requirement, requirement_id)

        return jsonify({
            'status': 'success',
            'report': report.to_dict()
        })

    except Exception as e:
        logger.error(f"Error analyzing impact: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/impact/summary', methods=['GET'])
def impact_summary():
    """
    Get a summary of the most recent impact analysis.

    This is a quick check for UI display.
    """
    try:
        # Return summary of impact capabilities
        return jsonify({
            'capabilities': {
                'analyzes': ['frontend_components', 'backend_apis', 'services', 'database_changes'],
                'provides': ['risk_level', 'affected_modules', 'recommendations'],
                'risk_levels': ['critical', 'high', 'medium', 'low']
            },
            'message': 'Use POST /api/impact/analyze for detailed analysis'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== Defect Report API ====================

@app.route('/api/defects/generate', methods=['POST'])
def generate_defects():
    """
    Generate simulated defect reports from requirement analysis.

    Request body:
    {
        "requirement": { ... parsed requirement ... },
        "ambiguous_points": [ ... ambiguous points ... ]
    }
    """
    try:
        data = request.get_json()
        requirement = data.get('requirement', {})
        ambiguous_points = data.get('ambiguous_points', [])

        if not requirement:
            return jsonify({'error': 'Requirement is required'}), 400

        from src.knowledge.defect_report import DefectGenerator

        generator = DefectGenerator()

        # Generate from requirement and ambiguous points
        defects = generator.generate_from_requirement(requirement, ambiguous_points)

        # Also generate from tech review if FE/BE output available in context
        fe_output = data.get('fe_output', {})
        be_output = data.get('be_output', {})

        if fe_output and be_output:
            tech_defects = generator.generate_from_tech_review(fe_output, be_output)
            defects.extend(tech_defects)

        return jsonify({
            'status': 'success',
            'defects': [d.to_dict() for d in defects],
            'summary': {
                'total_defects': len(defects),
                'critical': sum(1 for d in defects if d.severity.value == 'critical'),
                'high': sum(1 for d in defects if d.severity.value == 'high'),
                'medium': sum(1 for d in defects if d.severity.value == 'medium'),
                'low': sum(1 for d in defects if d.severity.value == 'low')
            }
        })

    except Exception as e:
        logger.error(f"Error generating defects: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/defects/analyze-test-case', methods=['POST'])
def analyze_test_case_defects():
    """
    Generate a defect report from a failed test case.

    Request body:
    {
        "test_case": { ... test case data ... },
        "test_result": "failed"
    }
    """
    try:
        data = request.get_json()
        test_case = data.get('test_case', {})
        test_result = data.get('test_result', 'failed')

        if not test_case:
            return jsonify({'error': 'Test case is required'}), 400

        from src.knowledge.defect_report import DefectGenerator

        generator = DefectGenerator()
        defect = generator.generate_from_test_case(test_case, test_result)

        if defect:
            return jsonify({
                'status': 'success',
                'defect': defect.to_dict()
            })
        else:
            return jsonify({'error': 'Could not generate defect'}), 400

    except Exception as e:
        logger.error(f"Error analyzing test case: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/defects/template', methods=['GET'])
def defect_template():
    """
    Get the defect report template/schema.

    Returns the structure of a defect report for reference.
    """
    return jsonify({
        'defect_template': {
            'defect_id': 'DEF-XXXXXXXX',
            'title': '缺陷标题',
            'description': '详细描述',
            'severity': 'critical | high | medium | low',
            'priority': 'P0 | P1 | P2 | P3',
            'status': 'open | in_progress | resolved | closed | reopened',
            'steps_to_reproduce': [
                {
                    'step_number': 1,
                    'action': '执行的操作',
                    'expected': '预期结果',
                    'actual': '实际结果'
                }
            ],
            'related_requirement_id': 'REQ-XXX',
            'related_test_case_id': 'TC-XXX',
            'assignee': '建议负责人',
            'affected_components': ['file1.js', 'file2.py'],
            'root_cause': '根本原因分析',
            'created_at': 'ISO datetime'
        }
    })


# ==================== Log Viewing API ====================

@app.route('/api/logs', methods=['GET'])
def view_logs():
    """
    View system logs.

    Query params:
    - lines: Number of lines to return (default 100, max 500)
    - search: Optional search filter
    - level: Filter by log level (INFO, WARNING, ERROR)
    """
    try:
        lines = int(request.args.get('lines', 100))
        lines = min(lines, 500)
        search = request.args.get('search', '').lower()
        level = request.args.get('level', '').upper()

        if not Path(LOG_FILE).exists():
            return jsonify({'error': 'Log file not found', 'path': str(LOG_FILE)}), 404

        with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()

        # Filter lines
        filtered_lines = []
        for line in all_lines[-lines:]:
            if search and search not in line.lower():
                continue
            if level and level not in line:
                continue
            filtered_lines.append(line.rstrip())

        return jsonify({
            'log_file': str(LOG_FILE),
            'total_lines': len(all_lines),
            'returned_lines': len(filtered_lines),
            'lines': filtered_lines,
            'filters': {
                'search': search,
                'level': level,
                'lines': lines
            }
        })

    except Exception as e:
        logger.error(f"Error reading logs: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/logs/tail', methods=['GET'])
def tail_logs():
    """
    Tail the log file (get last N lines continuously).

    Query params:
    - lines: Number of lines to return (default 20)
    """
    try:
        lines = int(request.args.get('lines', 20))
        lines = min(lines, 100)

        if not Path(LOG_FILE).exists():
            return jsonify({'lines': [], 'message': 'No logs yet'})

        with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()

        return jsonify({
            'lines': [l.rstrip() for l in all_lines[-lines:]],
            'total_lines': len(all_lines)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    """Clear the log file (with confirmation)."""
    try:
        data = request.get_json() or {}
        confirm = data.get('confirm', False)

        if not confirm:
            return jsonify({'error': 'Confirmation required', 'message': 'Set confirm=true to clear logs'}), 400

        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(f"# Log cleared at {datetime.now().isoformat()}\n")

        return jsonify({'status': 'cleared', 'timestamp': datetime.now().isoformat()})

    except Exception as e:
        return jsonify({'error': str(e)}), 500