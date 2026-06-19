"""
Orchestrator for coordinating the multi-agent workflow.

The Orchestrator manages the SOP workflow:
1. PM: Parse requirements -> (optional) User clarifications
2. FE/BE: Analyze based on parsed requirements
3. QA: Review, challenge, and generate test cases with evidence chains
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable

from src.agents.base_agent import AgentRole, AgentState, AgentMessage
from src.agents.pm_agent import ProductManagerAgent
from src.agents.fe_agent import FrontendEngineerAgent
from src.agents.be_agent import BackendEngineerAgent
from src.agents.qa_agent import QAEngineerAgent
from src.adapters.llm_adapter import LLMAdapter, MockLLMAdapter
from src.memory.storage import MemoryStorage, MemoryUnit, QARecord
from src.config import WORKFLOW_CONFIG

logger = logging.getLogger(__name__)


class WorkflowStage(str, Enum):
    """Workflow stages."""
    START = "start"
    PM_PARSING = "pm_parsing"
    PM_CLARIFICATION = "pm_clarification"
    FE_BE_ANALYSIS = "fe_be_analysis"
    QA_REVIEW = "qa_review"
    QA_CHALLENGE = "qa_challenge"
    CHALLENGE_RESPONSE = "challenge_response"
    GENERATING_TEST_CASES = "generating_test_cases"
    DONE = "done"
    ERROR = "error"


@dataclass
class WorkflowState:
    """Current state of the workflow."""
    stage: WorkflowStage = WorkflowStage.START
    requirement_id: str = ""
    original_requirement: str = ""
    pm_output: Optional[Dict[str, Any]] = None
    fe_output: Optional[Dict[str, Any]] = None
    be_output: Optional[Dict[str, Any]] = None
    qa_output: Optional[Dict[str, Any]] = None
    pm_thinking: Optional[Dict[str, Any]] = None
    fe_thinking: Optional[Dict[str, Any]] = None
    be_thinking: Optional[Dict[str, Any]] = None
    qa_thinking: Optional[Dict[str, Any]] = None
    # Challenge/response tracking
    challenges: List[Dict[str, Any]] = field(default_factory=list)  # QA challenges to agents
    responses: List[Dict[str, Any]] = field(default_factory=list)  # Agent responses to challenges
    clarification_questions: List[str] = field(default_factory=list)
    iteration_count: int = 0
    messages: List[AgentMessage] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "requirement_id": self.requirement_id,
            "stage_history": [m.to_dict() for m in self.messages[-10:]],
            "iteration_count": self.iteration_count,
            "started_at": self.started_at,
            "completed_at": self.completed_at
        }


class Orchestrator:
    """
    Orchestrator for coordinating the multi-agent workflow.

    Manages the complete SOP:
    1. PM Agent parses requirements
    2. If ambiguous, ask user for clarifications
    3. FE and BE agents analyze based on requirements
    4. QA Agent reviews, challenges, and generates test cases
    5. Return final test cases with evidence chains
    """

    def __init__(
        self,
        llm_adapter: Optional[LLMAdapter] = None,
        memory_storage: Optional[MemoryStorage] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the Orchestrator.

        Args:
            llm_adapter: LLM adapter for agent communication
            memory_storage: Memory storage for persistence
            config: Additional configuration
        """
        self.config = config or {}
        self.llm_adapter = llm_adapter or LLMAdapter()
        self.memory_storage = memory_storage or MemoryStorage()

        # Initialize agents
        self._init_agents()

        # Workflow state
        self.state = WorkflowState()

        # Callbacks for UI updates
        self.on_state_change: Optional[Callable[[WorkflowState], None]] = None
        self.on_message: Optional[Callable[[AgentMessage], None]] = None

        logger.info("Orchestrator initialized")

    def _init_agents(self) -> None:
        """Initialize all agents."""
        # Create agents with shared LLM adapter
        self.pm_agent = ProductManagerAgent(llm_adapter=self.llm_adapter)
        self.fe_agent = FrontendEngineerAgent(
            llm_adapter=self.llm_adapter,
            codebase_path=self.config.get("codebase_path", ".")
        )
        self.be_agent = BackendEngineerAgent(
            llm_adapter=self.llm_adapter,
            codebase_path=self.config.get("codebase_path", ".")
        )
        self.qa_agent = QAEngineerAgent(llm_adapter=self.llm_adapter)

        # Connect agents to memory
        for agent in [self.pm_agent, self.fe_agent, self.be_agent, self.qa_agent]:
            agent.memory = self.memory_storage

        logger.info("All agents initialized")

    def _notify_state_change(self) -> None:
        """Notify listeners of state change."""
        if self.on_state_change:
            self.on_state_change(self.state)

    def _notify_message(self, message: AgentMessage) -> None:
        """Notify listeners of new message."""
        self.state.messages.append(message)
        if self.on_message:
            self.on_message(message)

    def run(self, requirement: str) -> Dict[str, Any]:
        """
        Run the complete workflow with a requirement.

        Implements the SOP:
        1. PM Parsing - parse requirement, ask clarifications if ambiguous
        2. FE/BE Analysis - analyze with knowledge base
        3. QA Review & Challenge - QA reviews, challenges agents, they respond
        4. Generate Test Cases - after consensus is reached

        Args:
            requirement: Natural language requirement from user

        Returns:
            Final result with test cases or pending questions
        """
        self.state = WorkflowState()
        self.state.original_requirement = requirement
        self.state.stage = WorkflowStage.PM_PARSING
        self._notify_state_change()

        try:
            # ─── Stage 1: PM Parsing ───────────────────────────────
            self._run_pm_stage(requirement)

            if self.state.stage == WorkflowStage.PM_CLARIFICATION:
                return self._make_result("needs_clarification", questions=self.state.clarification_questions)

            # ─── Stage 2: FE/BE Analysis ──────────────────────────
            self._run_fe_be_stage()

            # ─── Stage 3: QA Review & Challenge Cycle ───────────
            # Run multi-turn challenge/response until consensus or max iterations
            max_iterations = WORKFLOW_CONFIG.get("max_iterations", 3)
            self.state.iteration_count = 0

            while self.state.iteration_count < max_iterations:
                self.state.iteration_count += 1
                self._run_qa_stage()

                if self.state.stage == WorkflowStage.QA_CHALLENGE:
                    # QA has challenges - run challenge/response cycle
                    self.state.stage = WorkflowStage.CHALLENGE_RESPONSE
                    self._run_challenge_response_cycle()

                    # Check if consensus reached after responses
                    if self._check_consensus():
                        break
                else:
                    # No challenges, consensus reached
                    break

            if self.state.stage == WorkflowStage.QA_CHALLENGE:
                # Still have unresolved challenges after max iterations
                return self._make_result("needs_clarification",
                    questions=[f"经过{max_iterations}轮仍未达成共识，请人工确认以下问题:",
                              *[c.get("question", c.get("challenge", "")) for c in self.state.challenges]])

            # ─── Stage 4: QA Re-review with consensus ──────────────
            # After challenge/response cycle, re-run QA so it sees the responses
            # and generates test cases with full evidence context
            self.state.stage = WorkflowStage.QA_REVIEW
            self._notify_state_change()

            # Re-run QA with updated context (responses are stored in state)
            self._run_qa_stage()

            # ─── Stage 5: Generate Test Cases ────────────────────
            self._run_test_generation_stage()

            # Complete
            self.state.stage = WorkflowStage.DONE
            self.state.completed_at = datetime.now().isoformat()
            self._notify_state_change()

            return self._make_result("success")

        except Exception as e:
            logger.error(f"Workflow error: {e}")
            self.state.stage = WorkflowStage.ERROR
            self.state.error = str(e)
            self._notify_state_change()
            return self._make_result("error", error=str(e))

    def _make_result(self, status: str, questions: List[str] = None, error: str = None) -> Dict[str, Any]:
        """Build a standardized result dict."""
        result = {
            "status": status,
            "stage": self.state.stage.value,
            "test_cases": self.state.qa_output,
            "pm_output": self.state.pm_output,
            "fe_output": self.state.fe_output,
            "be_output": self.state.be_output,
            "pm_thinking": self.state.pm_thinking,
            "fe_thinking": self.state.fe_thinking,
            "be_thinking": self.state.be_thinking,
            "qa_thinking": self.state.qa_thinking,
            "challenges": self.state.challenges,
            "responses": self.state.responses,
            "iteration_count": self.state.iteration_count,
        }
        if questions:
            result["questions"] = questions
        if error:
            result["error"] = error
        return result

    def _check_consensus(self) -> bool:
        """Check if QA consensus is reached (no remaining challenges or all answered)."""
        if not self.state.challenges:
            return True
        # Consensus reached if all challenges have been responded to
        answered_refs = {r.get("challenge_id") for r in self.state.responses}
        pending = [c for c in self.state.challenges if c.get("challenge_id") not in answered_refs]
        return len(pending) == 0

    def _run_challenge_response_cycle(self) -> None:
        """
        Run one round of challenge/response between QA and other agents.
        Each challenge is sent to the target agent, which provides a response.
        """
        logger.info(f"Running challenge/response cycle, {len(self.state.challenges)} challenges")

        for challenge in self.state.challenges:
            target = challenge.get("target")  # AgentRole of challenged agent
            challenge_text = challenge.get("question", challenge.get("challenge", ""))
            challenge_id = challenge.get("challenge_id", challenge_text)

            response_content = None

            # Route challenge to the appropriate agent
            if target == AgentRole.PM:
                # PM responds to challenge
                response = self.pm_agent.respond_to_challenge(challenge_text, challenge_id)
                response_content = response.content if response else None
            elif target == AgentRole.FE:
                response = self.fe_agent.respond_to_challenge(challenge_text, challenge_id)
                response_content = response.content if response else None
            elif target == AgentRole.BE:
                response = self.be_agent.respond_to_challenge(challenge_text, challenge_id)
                response_content = response.content if response else None
            else:
                # Fallback: log as unanswered challenge
                response_content = None

            # Record response
            self.state.responses.append({
                "challenge_id": challenge_id,
                "target": target.value if target else "unknown",
                "response": response_content,
                "challenge": challenge_text,
            })

        self._notify_state_change()

    def _run_pm_stage(self, requirement: str) -> None:
        """Run the PM parsing stage."""
        logger.info("Running PM parsing stage")

        output = self.pm_agent.act(requirement)
        self.state.pm_output = output.content
        self.state.pm_thinking = output.thinking
        self._notify_message(AgentMessage(
            sender=AgentRole.PM,
            receiver=AgentRole.QA,
            content=output.content,
            message_type="pm_output"
        ))

        # Check for clarification questions
        if output.has_questions():
            self.state.stage = WorkflowStage.PM_CLARIFICATION
            self.state.clarification_questions = output.questions
            logger.info(f"PM needs clarifications: {len(output.questions)} questions")
        else:
            # Store parsed requirement in memory
            self._store_requirement_memory()

        self._notify_state_change()

    def _run_fe_be_stage(self) -> None:
        """Run the FE and BE analysis stage."""
        logger.info("Running FE/BE analysis stage")
        self.state.stage = WorkflowStage.FE_BE_ANALYSIS
        self._notify_state_change()

        # Run FE analysis
        fe_output = self.fe_agent.act(self.state.pm_output)
        self.state.fe_output = fe_output.content
        self.state.fe_thinking = fe_output.thinking
        self._notify_message(AgentMessage(
            sender=AgentRole.FE,
            receiver=AgentRole.QA,
            content=fe_output.content,
            message_type="fe_output"
        ))

        # Run BE analysis
        be_output = self.be_agent.act(self.state.pm_output)
        self.state.be_output = be_output.content
        self.state.be_thinking = be_output.thinking
        self._notify_message(AgentMessage(
            sender=AgentRole.BE,
            receiver=AgentRole.QA,
            content=be_output.content,
            message_type="be_output"
        ))

        self._notify_state_change()

    def _run_qa_stage(self) -> None:
        """Run the QA review and challenge stage."""
        logger.info("Running QA review stage")
        self.state.stage = WorkflowStage.QA_REVIEW
        self._notify_state_change()

        # QA receives all inputs
        self.qa_agent.receive_inputs(
            self.state.pm_output,
            self.state.fe_output,
            self.state.be_output
        )

        qa_output = self.qa_agent.act()
        self.state.qa_output = qa_output.content
        self.state.qa_thinking = qa_output.thinking

        # Extract challenges from QA thinking into orchestrator state
        qa_challenges = qa_output.thinking.get("challenges", []) if qa_output.thinking else []
        if qa_challenges:
            self.state.challenges.extend(qa_challenges)

        # Check for questions from QA
        if qa_output.has_questions() or qa_challenges:
            self.state.stage = WorkflowStage.QA_CHALLENGE
            self.state.clarification_questions = qa_output.questions
            logger.info(f"QA has challenges: {len(qa_challenges)} challenges, {len(qa_output.questions)} questions")

        self._notify_state_change()

    def _run_test_generation_stage(self) -> None:
        """Run the test case generation stage."""
        logger.info("Generating test cases")
        self.state.stage = WorkflowStage.GENERATING_TEST_CASES
        self._notify_state_change()

        # Pass challenge/response context to QA for evidence chain
        # QA needs to know what was challenged and how it was resolved
        challenge_response_context = {
            "challenges": self.state.challenges,
            "responses": self.state.responses,
        }

        # Generate test cases with evidence chains
        # Pass context so QA can build evidence chains referencing the responses
        qa_output = self.qa_agent.act_with_context(challenge_response_context)

        if qa_output.error:
            raise Exception(f"QA generation error: {qa_output.error}")

        self.state.qa_output = qa_output.content
        self.state.qa_thinking = qa_output.thinking

        # Defensive fallback: some LLM backends may return questions or an
        # incomplete JSON object without test_suites. The product contract is
        # that a successful workflow returns test cases, so build a conservative
        # evidence-backed suite from PM/FE/BE outputs instead of returning empty.
        if not self._has_generated_test_cases(self.state.qa_output):
            logger.warning("QA output has no test_suites; building fallback test cases")
            self.state.qa_output = self._build_fallback_test_cases()
            self.state.qa_thinking = {
                **(self.state.qa_thinking or {}),
                "fallback_generated": True,
                "reason": "QA output missing test_suites/test_cases"
            }

        # Store test cases in memory
        self._store_test_cases()

        self._notify_state_change()

    def _has_generated_test_cases(self, output: Dict[str, Any]) -> bool:
        """Return True when QA output contains at least one test case."""
        if not isinstance(output, dict):
            return False
        suites = output.get("test_suites") or []
        for suite in suites:
            if suite.get("test_cases"):
                return True
        return False

    def _build_fallback_test_cases(self) -> Dict[str, Any]:
        """Build conservative fallback test cases from available evidence.

        This is used only when the QA LLM returns no test_suites. It keeps the
        evidence-chain contract by attaching requirement/business/API/code refs
        to every generated case.
        """
        pm = self.state.pm_output or {}
        fe = self.state.fe_output or {}
        be = self.state.be_output or {}

        req_id = pm.get("requirement_id") or "REQ_FALLBACK"
        title = pm.get("title") or "需求测试用例"
        business_rules = pm.get("business_rules") or []
        acceptance = pm.get("acceptance_criteria") or []
        user_stories = pm.get("user_stories") or []

        evidence_chain = []
        evidence_chain.append({
            "type": "REQ_STRUCT",
            "ref_id": req_id,
            "content": title,
        })
        for i, rule in enumerate(business_rules[:5], 1):
            evidence_chain.append({
                "type": "BIZ_RULE",
                "ref_id": rule.get("id") or f"BR_{i}",
                "content": rule.get("rule") or rule.get("description") or str(rule),
            })
        for i, api in enumerate((be.get("api_definitions") or be.get("apis") or [])[:5], 1):
            evidence_chain.append({
                "type": "API_DEF",
                "ref_id": f"API_{i}",
                "content": f"{api.get('method', '')} {api.get('path', api.get('url', ''))}".strip(),
            })
        for i, comp in enumerate((fe.get("components") or fe.get("affected_components") or [])[:5], 1):
            evidence_chain.append({
                "type": "CODE_ANALYZE",
                "ref_id": f"FE_{i}",
                "content": comp.get("name") if isinstance(comp, dict) else str(comp),
            })
        if not evidence_chain:
            evidence_chain.append({"type": "REQ_RAW", "ref_id": "REQ_RAW", "content": self.state.original_requirement})

        base_ref = evidence_chain[0]["ref_id"]
        test_cases = []
        idx = 1

        def add_case(title_text: str, priority: str, steps: List[Dict[str, str]], evidence=None):
            nonlocal idx
            chain = evidence or evidence_chain
            test_cases.append({
                "test_case_id": f"TC_FALLBACK_{idx:03d}",
                "title": title_text,
                "priority": priority,
                "preconditions": ["测试环境可用", "用户/权限/数据已按需求准备"],
                "test_steps": steps,
                "evidence_chain": chain,
            })
            idx += 1

        add_case(
            f"{title} - 正向主流程",
            "high",
            [
                {"step_number": 1, "action": "按需求描述进入对应功能入口", "expected_result": "页面/接口入口可正常访问", "evidence_ref": base_ref},
                {"step_number": 2, "action": "输入/提交一组满足需求条件的有效数据", "expected_result": "系统按业务规则成功处理", "evidence_ref": base_ref},
                {"step_number": 3, "action": "检查页面反馈、接口响应、数据落库/状态变化", "expected_result": "结果与需求和已确认边界一致", "evidence_ref": base_ref},
            ],
        )

        if acceptance:
            for ac in acceptance[:3]:
                content = ac.get("criteria") or ac.get("description") or str(ac)
                ref = ac.get("id") or base_ref
                ac_chain = evidence_chain + [{"type": "REQ_STRUCT", "ref_id": ref, "content": content}]
                add_case(
                    f"验收条件校验 - {content[:40]}",
                    "high",
                    [
                        {"step_number": 1, "action": f"构造满足验收条件的数据/场景：{content}", "expected_result": "场景可执行", "evidence_ref": ref},
                        {"step_number": 2, "action": "执行对应操作", "expected_result": "系统输出符合验收条件", "evidence_ref": ref},
                    ],
                    ac_chain,
                )

        if business_rules:
            for rule in business_rules[:3]:
                content = rule.get("rule") or rule.get("description") or str(rule)
                ref = rule.get("id") or base_ref
                add_case(
                    f"业务规则校验 - {content[:40]}",
                    "medium",
                    [
                        {"step_number": 1, "action": f"准备触发业务规则的数据：{content}", "expected_result": "测试数据准备完成", "evidence_ref": ref},
                        {"step_number": 2, "action": "执行功能操作", "expected_result": "系统严格按业务规则处理", "evidence_ref": ref},
                    ],
                )

        # Always include one negative/boundary case.
        add_case(
            f"{title} - 异常/边界场景",
            "medium",
            [
                {"step_number": 1, "action": "输入缺失、非法、越界或未授权的数据", "expected_result": "系统拒绝处理并给出明确错误提示/错误码", "evidence_ref": base_ref},
                {"step_number": 2, "action": "检查数据状态和副作用", "expected_result": "不产生错误落库、重复提交或越权访问", "evidence_ref": base_ref},
            ],
        )

        return {
            "test_plan": {
                "test_plan_id": "TP_FALLBACK_001",
                "requirement_id": req_id,
                "summary": f"{title} 的兜底测试计划",
                "scope": "正向主流程、验收条件、业务规则、异常/边界场景",
                "out_of_scope": "未在需求/人工确认/知识库中出现的外部系统行为",
            },
            "test_suites": [
                {
                    "suite_id": "TS_FALLBACK_001",
                    "suite_name": f"{title} 测试套件",
                    "test_cases": test_cases,
                }
            ],
            "questions": [],
            "fallback_generated": True,
        }

    def provide_clarification(self, answers: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Provide answers to clarification questions.

        Args:
            answers: List of {"question": "...", "answer": "..."} dicts

        Returns:
            Workflow result after applying clarifications
        """
        if self.state.stage == WorkflowStage.PM_CLARIFICATION:
            # Apply to PM agent
            self.pm_agent.apply_clarifications(answers)

            # Save Q&A to memory
            for answer in answers:
                self.memory_storage.save_qa_record(
                    QARecord(
                        context=self.state.original_requirement,
                        question=answer["question"],
                        answer=answer["answer"]
                    )
                )

            # Update state
            self.state.pm_output = self.pm_agent.parsed_requirements
            self.state.clarification_questions = []
            self.state.stage = WorkflowStage.FE_BE_ANALYSIS

            # Continue workflow
            return self.run(self.state.original_requirement)

        elif self.state.stage == WorkflowStage.QA_CHALLENGE:
            # Apply to QA agent (handle challenges)
            # This would involve re-running analysis with clarifications
            self.state.clarification_questions = []
            self.state.stage = WorkflowStage.QA_REVIEW

            # Continue workflow
            return self.run(self.state.original_requirement)

        return {
            "status": "error",
            "error": "No pending clarifications"
        }

    def _store_requirement_memory(self) -> None:
        """Store requirement-related data in memory."""
        if not self.state.pm_output:
            return

        # Store business rules as memory units
        for br in self.state.pm_output.get("business_rules", []):
            self.memory_storage.save_memory_unit(
                MemoryUnit(
                    content=br.get("rule", ""),
                    source_type="pm_requirement",
                    metadata={
                        "requirement_id": self.state.pm_output.get("requirement_id"),
                        "rule_id": br.get("id")
                    }
                )
            )

    def _store_test_cases(self) -> None:
        """Store generated test cases in memory."""
        if not self.state.qa_output:
            return

        for suite in self.state.qa_output.get("test_suites", []):
            for tc in suite.get("test_cases", []):
                self.memory_storage.save_test_case(
                    TestCaseRecord(
                        tc_id=tc.get("test_case_id", ""),
                        requirement_id=self.state.pm_output.get("requirement_id", ""),
                        title=tc.get("title", ""),
                        content=json.dumps(tc, ensure_ascii=False),
                        evidence_chain=json.dumps(
                            tc.get("built_evidence_chain", {}),
                            ensure_ascii=False
                        )
                    )
                )

        # Save conversation history
        self.memory_storage.save_conversation_message(
            role="pm",
            content=json.dumps(self.state.pm_output, ensure_ascii=False),
            metadata={"stage": "pm_parsing"}
        )
        self.memory_storage.save_conversation_message(
            role="fe",
            content=json.dumps(self.state.fe_output, ensure_ascii=False),
            metadata={"stage": "fe_analysis"}
        )
        self.memory_storage.save_conversation_message(
            role="be",
            content=json.dumps(self.state.be_output, ensure_ascii=False),
            metadata={"stage": "be_analysis"}
        )
        self.memory_storage.save_conversation_message(
            role="qa",
            content=json.dumps(self.state.qa_output, ensure_ascii=False),
            metadata={"stage": "qa_review"}
        )

    def get_workflow_state(self) -> WorkflowState:
        """Get current workflow state."""
        return self.state

    def get_history(self) -> List[Dict[str, Any]]:
        """Get conversation history from memory."""
        return self.memory_storage.get_conversation_history(limit=100)

    def reset(self) -> None:
        """Reset the workflow state."""
        self.state = WorkflowState()
        for agent in [self.pm_agent, self.fe_agent, self.be_agent, self.qa_agent]:
            agent.reset()
        logger.info("Workflow reset")


class MockOrchestrator(Orchestrator):
    """
    Mock Orchestrator for testing without actual LLM calls.
    """

    def _init_agents(self) -> None:
        """Initialize agents with mock LLM adapter."""
        mock_adapter = MockLLMAdapter()
        mock_adapter.set_mock_response(json.dumps({
            "requirement_id": "REQ_001",
            "title": "Mock Requirement",
            "description": "This is a mock requirement for testing",
            "user_stories": [{"id": "US_001", "as_a": "user", "i_want": "to test", "so_that": "it works"}],
            "business_rules": [{"id": "BR_001", "rule": "Mock business rule", "source": "mock"}],
            "acceptance_criteria": [],
            "ambiguous_points": [],
            "entities": []
        }))

        self.pm_agent = ProductManagerAgent(llm_adapter=mock_adapter)
        self.fe_agent = FrontendEngineerAgent(llm_adapter=MockLLMAdapter())
        self.be_agent = BackendEngineerAgent(llm_adapter=MockLLMAdapter())
        self.qa_agent = QAEngineerAgent(llm_adapter=MockLLMAdapter())

        for agent in [self.pm_agent, self.fe_agent, self.be_agent, self.qa_agent]:
            agent.memory = self.memory_storage

        logger.info("Mock agents initialized")