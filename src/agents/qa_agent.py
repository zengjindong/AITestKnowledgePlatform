"""
Quality Assurance (QA) Agent for test case generation with evidence chain.

This agent is responsible for:
- Reviewing requirements and technical solutions
- Challenging assumptions and requesting clarifications
- Generating test cases with evidence chains
- Ensuring quality gates are met

As the "Quality Gatekeeper", QA Agent must ensure all test cases
have proper evidence chain support before generating them.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent, AgentRole, AgentOutput, AgentState
from src.agents.evidence_chain import (
    EvidenceChain,
    EvidenceChainBuilder,
    EvidenceType,
    EvidenceItem
)
from src.config import EVIDENCE_TYPES

logger = logging.getLogger(__name__)


class QAOutputSchema:
    """Expected output schema for QA Agent."""

    @staticmethod
    def get_test_case_prompt() -> str:
        return """Generate detailed test cases based on the provided requirements and technical analysis.

IMPORTANT RULES:
1. Every test case MUST have an evidence_chain that traces back to actual requirements, APIs, or code
2. You CANNOT generate test steps without proper evidence
3. If evidence is missing, you MUST ask questions instead of guessing

Output a JSON object with the following structure:
{
    "test_plan": {
        "test_plan_id": "TP_001",
        "requirement_id": "REQ_001",
        "summary": "Test plan summary",
        "scope": "What's included",
        "out_of_scope": "What's excluded"
    },
    "test_suites": [
        {
            "suite_id": "TS_001",
            "suite_name": "Suite name",
            "test_cases": [
                {
                    "test_case_id": "TC_001",
                    "title": "Test case title",
                    "priority": "high|medium|low",
                    "preconditions": ["list of preconditions"],
                    "test_steps": [
                        {
                            "step_number": 1,
                            "action": "Action description",
                            "expected_result": "Expected result",
                            "evidence_ref": "ref_id from evidence chain"
                        }
                    ],
                    "evidence_chain": [
                        {
                            "type": "REQ_STRUCT|BIZ_RULE|API_DEF|CODE_ANALYZE",
                            "ref_id": "reference id",
                            "content": "evidence content"
                        }
                    ]
                }
            ]
        }
    ],
    "questions": [
        {
            "question": "Question text",
            "reason": "Why this question is important"
        }
    ]
}"""


class QAAnalysisResult:
    """Result of QA review."""

    def __init__(self):
        self.test_plan: Dict[str, Any] = {}
        self.test_suites: List[Dict[str, Any]] = []
        self.questions: List[Dict[str, str]] = []
        self.consensus_reached: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_plan": self.test_plan,
            "test_suites": self.test_suites,
            "questions": self.questions,
            "consensus_reached": self.consensus_reached
        }


class QAEngineerAgent(BaseAgent):
    """
    Quality Assurance Engineer Agent responsible for test case generation.

    This agent reviews all inputs from PM, FE, and BE agents, challenges
    assumptions, and generates comprehensive test cases with evidence chains.
    """

    def __init__(self, llm_adapter=None, config: Dict[str, Any] = None):
        super().__init__(role=AgentRole.QA, llm_adapter=llm_adapter, config=config)
        self.analysis_result: Optional[QAAnalysisResult] = None
        self.pending_challenges: List[Dict[str, str]] = []
        self.pm_output: Optional[Dict[str, Any]] = None
        self.fe_output: Optional[Dict[str, Any]] = None
        self.be_output: Optional[Dict[str, Any]] = None
        self._skip_challenges: bool = False  # Skip challenge generation after response cycle

    def receive_inputs(
        self,
        pm_output: Dict[str, Any],
        fe_output: Dict[str, Any],
        be_output: Dict[str, Any]
    ) -> None:
        """
        Receive outputs from other agents for review.

        Args:
            pm_output: Output from PM agent
            fe_output: Output from FE agent
            be_output: Output from BE agent
        """
        self.pm_output = pm_output
        self.fe_output = fe_output
        self.be_output = be_output

        logger.info("QA Agent received inputs from PM, FE, and BE agents")

    def _think_impl(self, input_data: Any) -> Dict[str, Any]:
        """
        Review all inputs and identify gaps or issues.

        Args:
            input_data: Combined inputs or None if using stored inputs

        Returns:
            Review plan with identified issues
        """
        from src.agents.base_agent import AgentRole

        thoughts = {
            "input_review": {
                "pm_received": self.pm_output is not None,
                "fe_received": self.fe_output is not None,
                "be_received": self.be_output is not None
            },
            "action_plan": [],
            "questions": [],
            "challenges": [],  # Will hold structured challenges with targets
            "evidence_available": {
                "requirements": 0,
                "apis": 0,
                "code_references": 0
            }
        }

        if self.pm_output:
            thoughts["evidence_available"]["requirements"] = len(
                self.pm_output.get("business_rules", [])
            ) + len(self.pm_output.get("user_stories", []))

        if self.fe_output:
            thoughts["evidence_available"]["apis"] = len(
                self.fe_output.get("api_dependencies", [])
            )

        if self.be_output:
            thoughts["evidence_available"]["code_references"] = len(
                self.be_output.get("code_references", {})
            )

        # Identify missing evidence and create targeted challenges
        if thoughts["evidence_available"]["requirements"] == 0:
            challenge = {
                "challenge_id": f"qa_challenge_req_{len(thoughts['challenges'])}",
                "target": AgentRole.PM,
                "question": "No requirements found - what are we testing? Please clarify the requirement.",
                "reason": "Cannot generate test cases without clear requirements"
            }
            thoughts["challenges"].append(challenge)

        if thoughts["evidence_available"]["apis"] == 0:
            challenge = {
                "challenge_id": f"qa_challenge_api_{len(thoughts['challenges'])}",
                "target": AgentRole.BE,
                "question": "No API definitions found - what interfaces need testing?",
                "reason": "Backend analysis did not provide sufficient API evidence"
            }
            thoughts["challenges"].append(challenge)

        # Also create challenges from any ambiguous points in PM output
        if self.pm_output and self.pm_output.get("ambiguous_points"):
            for i, amb in enumerate(self.pm_output.get("ambiguous_points", [])):
                challenge = {
                    "challenge_id": f"qa_challenge_amb_{i}",
                    "target": AgentRole.PM,
                    "question": f"Ambiguous point: {amb.get('point', '')}. {amb.get('question', '')}",
                    "reason": "Requirement contains ambiguous points"
                }
                thoughts["challenges"].append(challenge)

        # Also challenge FE if no components analyzed
        if self.fe_output and not self.fe_output.get("affected_components"):
            challenge = {
                "challenge_id": f"qa_challenge_fe_{len(thoughts['challenges'])}",
                "target": AgentRole.FE,
                "question": "No frontend components were identified as affected. Is this purely a backend change?",
                "reason": "Frontend analysis found no relevant components"
            }
            thoughts["challenges"].append(challenge)

        # Skip challenge generation after response cycle - proceed to generation
        if self._skip_challenges:
            thoughts["challenges"] = []
            thoughts["action_plan"].append("generate_test_cases")
            thoughts["consensus_reached"] = True
            return thoughts

        # Check for consensus
        if self._check_consensus() and not thoughts["challenges"]:
            thoughts["action_plan"].append("generate_test_cases")
            thoughts["consensus_reached"] = True
        else:
            thoughts["action_plan"].append("challenge_agents")
            thoughts["consensus_reached"] = False

        return thoughts

    def _check_consensus(self) -> bool:
        """
        Check if consensus has been reached among agents.

        Returns:
            True if all agents agree on the approach
        """
        # Check if all required inputs are present
        if not all([self.pm_output, self.fe_output, self.be_output]):
            return False

        # Check for unanswered questions from PM
        if self.pm_output.get("ambiguous_points"):
            return False

        return True

    def challenge_agent(
        self,
        agent_role: AgentRole,
        challenge: str,
        reason: str
    ) -> AgentMessage:
        """
        Create a challenge message to another agent.

        Args:
            agent_role: The agent to challenge
            challenge: The challenge or question
            reason: Why this is being challenged

        Returns:
            The challenge message
        """
        challenge_data = {
            "challenge": challenge,
            "reason": reason
        }
        self.pending_challenges.append(challenge_data)

        msg = AgentMessage(
            sender=self.role,
            receiver=agent_role,
            content=challenge_data,
            message_type="challenge"
        )

        logger.info(f"QA Agent challenging {agent_role.value}: {challenge}")
        return msg

    def act(self, input_data: Any = None) -> AgentOutput:
        """
        Generate test cases with evidence chains.

        Args:
            input_data: Optional combined inputs

        Returns:
            AgentOutput with test cases
        """
        self.state = AgentState.ACTING
        self.output = AgentOutput(role=self.role, state=AgentState.ACTING)
        self.analysis_result = QAAnalysisResult()

        try:
            thoughts = self._think_impl(input_data)

            # Check consensus
            if not thoughts["consensus_reached"]:
                # Need to challenge agents or wait for clarifications
                if thoughts["questions"]:
                    self.output.questions = thoughts["questions"]
                    self.output.state = AgentState.WAITING
                    return self.output

            # Build comprehensive context for test generation
            context = self._build_test_context()

            # Generate test cases using LLM
            response = self.llm_adapter.generate_structured(
                system_prompt=QAOutputSchema.get_test_case_prompt(),
                user_message=context
            )

            if response is None:
                self.output.error = "Failed to generate test cases"
                self.output.state = AgentState.ERROR
                return self.output

            # Validate evidence chains in generated test cases
            validation_result = self._validate_test_cases(response)
            if not validation_result["valid"]:
                # Return questions instead of generating invalid test cases
                self.output.questions = validation_result["questions"]
                self.output.state = AgentState.WAITING
                return self.output

            # Store results
            self.analysis_result.test_plan = response.get("test_plan", {})
            self.analysis_result.test_suites = response.get("test_suites", [])
            self.analysis_result.questions = response.get("questions", [])
            self.analysis_result.consensus_reached = True

            # Build evidence chains for each test case
            self._build_test_case_evidence_chains(response)

            self.output.content = self.analysis_result.to_dict()
            self.output.state = AgentState.DONE

        except Exception as e:
            logger.error(f"QA Agent error: {e}")
            self.output.error = str(e)
            self.output.state = AgentState.ERROR

        return self.output

    def act_with_context(self, context_data: Dict[str, Any]) -> AgentOutput:
        """
        Generate test cases with full challenge/response context.

        This is called after the challenge/response cycle completes,
        so QA has the full evidence from the responses.

        Args:
            context_data: Dict with challenges and responses from orchestrator

        Returns:
            AgentOutput with test cases
        """
        self.state = AgentState.ACTING
        self.output = AgentOutput(role=self.role, state=AgentState.ACTING)
        self.analysis_result = QAAnalysisResult()
        self._skip_challenges = True  # Don't generate new challenges after response cycle

        try:
            challenges = context_data.get("challenges", [])
            responses = context_data.get("responses", [])

            # Build comprehensive context including challenge/response
            context = self._build_test_context_with_responses(challenges, responses)

            # Generate test cases using LLM
            response = self.llm_adapter.generate_structured(
                system_prompt=QAOutputSchema.get_test_case_prompt(),
                user_message=context
            )

            if response is None:
                self.output.error = "Failed to generate test cases"
                self.output.state = AgentState.ERROR
                return self.output

            # Validate evidence chains in generated test cases
            validation_result = self._validate_test_cases(response)
            if not validation_result["valid"]:
                self.output.questions = validation_result["questions"]
                self.output.state = AgentState.WAITING
                return self.output

            # Store results
            self.analysis_result.test_plan = response.get("test_plan", {})
            self.analysis_result.test_suites = response.get("test_suites", [])
            self.analysis_result.questions = response.get("questions", [])
            self.analysis_result.consensus_reached = True

            # Build evidence chains for each test case
            self._build_test_case_evidence_chains_with_responses(response, challenges, responses)

            self.output.content = self.analysis_result.to_dict()
            self.output.thinking = {
                "action_plan": ["generate_test_cases_with_consensus"],
                "consensus_reached": True,
                "challenges_resolved": len(challenges),
                "responses_received": len(responses)
            }
            self.output.state = AgentState.DONE

        except Exception as e:
            logger.error(f"QA Agent error: {e}")
            self.output.error = str(e)
            self.output.state = AgentState.ERROR

        return self.output

    def _build_test_context_with_responses(
        self,
        challenges: List[Dict[str, Any]],
        responses: List[Dict[str, Any]]
    ) -> str:
        """Build context including challenge/response history."""
        base_context = self._build_test_context()

        # Parse base_context if it's a JSON string
        if isinstance(base_context, str):
            import json
            try:
                base_context = json.loads(base_context)
            except json.JSONDecodeError:
                pass

        if isinstance(base_context, dict):
            base_context["challenge_response_history"] = [
                {
                    "challenge": c.get("question", c.get("challenge", "")),
                    "target": c.get("target", "").value if hasattr(c.get("target"), "value") else str(c.get("target", "")),
                    "response": next(
                        (r.get("response") for r in responses
                         if r.get("challenge_id") == c.get("challenge_id")),
                        None
                    )
                }
                for c in challenges
            ]
            return json.dumps(base_context, ensure_ascii=False, indent=2)

        return str(base_context)

    def _build_test_case_evidence_chains_with_responses(
        self,
        test_cases: Dict[str, Any],
        challenges: List[Dict[str, Any]],
        responses: List[Dict[str, Any]]
    ) -> None:
        """Build evidence chains including challenge/response evidence."""
        for suite in test_cases.get("test_suites", []):
            for tc in suite.get("test_cases", []):
                tc_id = tc.get("test_case_id", "unknown")

                builder = EvidenceChainBuilder(tc_id)

                # Add requirement evidence
                if self.pm_output:
                    for br in self.pm_output.get("business_rules", []):
                        builder.add_business_rule(
                            ref_id=br.get("id", "unknown"),
                            content=br.get("rule", "")
                        )

                # Add API evidence from BE
                if self.be_output:
                    for api in self.be_output.get("api_definitions", []):
                        builder.add_api(
                            ref_id=f"{api.get('method', 'GET')}_{api.get('path', 'unknown')}",
                            content=f"{api.get('method', 'GET')} {api.get('path', '')}"
                        )

                # Add FE analysis evidence
                if self.fe_output:
                    for comp in self.fe_output.get("affected_components", []):
                        builder.add_fe_analysis(
                            ref_id=comp.get("file", comp.get("name", "unknown")),
                            content=f"Component: {comp.get('name', 'unknown')}"
                        )

                # Add challenge/response as evidence
                for c, r in zip(challenges, responses):
                    if r.get("response"):
                        builder.add_evidence(
                            evidence_type="USER_ANSWER",
                            ref_id=c.get("challenge_id", "unknown"),
                            content=f"Q: {c.get('question', c.get('challenge', ''))}\nA: {r.get('response', '')}"
                        )

                tc["built_evidence_chain"] = builder.build().to_dict()

    def _build_test_context(self) -> str:
        """Build comprehensive context for test generation."""
        context = {
            "pm_requirement": self.pm_output,
            "fe_analysis": self.fe_output,
            "be_analysis": self.be_output,
            "memory_context": self._get_memory_context()
        }
        return json.dumps(context, ensure_ascii=False, indent=2)

    def _get_memory_context(self) -> Dict[str, Any]:
        """Get relevant context from memory."""
        # This would query the memory system
        # For now, return empty
        return {}

    def _validate_test_cases(self, test_cases: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate that test cases have proper evidence chains.

        Args:
            test_cases: Generated test cases

        Returns:
            Validation result with questions if invalid
        """
        questions = []
        valid = True

        for suite in test_cases.get("test_suites", []):
            for tc in suite.get("test_cases", []):
                evidence_chain = tc.get("evidence_chain", [])
                test_steps = tc.get("test_steps", [])

                # Check if every test step has evidence
                for step in test_steps:
                    step_num = step.get("step_number")
                    evidence_ref = step.get("evidence_ref")

                    # Verify evidence exists
                    if evidence_ref:
                        found = any(e.get("ref_id") == evidence_ref for e in evidence_chain)
                        if not found:
                            questions.append(
                                f"Test case {tc.get('test_case_id')} step {step_num}: "
                                f"Evidence ref '{evidence_ref}' not found in evidence chain"
                            )
                            valid = False

                # Check for minimum evidence
                if not evidence_chain:
                    questions.append(
                        f"Test case {tc.get('test_case_id')} has no evidence chain - "
                        "this is not allowed. Please provide evidence for all test cases."
                    )
                    valid = False

        return {"valid": valid, "questions": questions}

    def _build_test_case_evidence_chains(self, test_cases: Dict[str, Any]) -> None:
        """Build evidence chains for all test cases."""
        for suite in test_cases.get("test_suites", []):
            for tc in suite.get("test_cases", []):
                tc_id = tc.get("test_case_id", "unknown")

                # Build evidence chain for this test case
                builder = EvidenceChainBuilder(tc_id)

                # Add requirements
                if self.pm_output:
                    for br in self.pm_output.get("business_rules", []):
                        builder.add_business_rule(
                            ref_id=br.get("id", "unknown"),
                            content=br.get("rule", "")
                        )
                    for ac in self.pm_output.get("acceptance_criteria", []):
                        builder.add_requirement(
                            ref_id=ac.get("id", "unknown"),
                            content=ac.get("criteria", "")
                        )

                # Add API definitions from BE
                if self.be_output:
                    for api in self.be_output.get("api_definitions", []):
                        builder.add_api(
                            ref_id=f"{api.get('method', 'GET')}_{api.get('endpoint', 'unknown')}",
                            content=f"{api.get('method', 'GET')} {api.get('endpoint', '')}"
                        )

                # Add frontend analysis
                if self.fe_output:
                    for component in self.fe_output.get("affected_components", []):
                        builder.add_fe_analysis(
                            ref_id=component.get("file", "unknown"),
                            content=f"Component analysis: {component.get('patterns_found', [])}"
                        )

                # Add evidence from the test case itself
                for evidence in tc.get("evidence_chain", []):
                    builder.add_evidence(
                        evidence_type=evidence.get("type", "CODE_ANALYZE"),
                        ref_id=evidence.get("ref_id", "unknown"),
                        content=evidence.get("content", "")
                    )

                # Store in output
                tc["built_evidence_chain"] = builder.build().to_dict()

    def generate_test_cases_with_evidence(
        self,
        pm_output: Dict,
        fe_output: Dict,
        be_output: Dict
    ) -> AgentOutput:
        """
        Convenience method to generate test cases from all inputs.

        Args:
            pm_output: PM agent output
            fe_output: FE agent output
            be_output: BE agent output

        Returns:
            AgentOutput with test cases
        """
        self.receive_inputs(pm_output, fe_output, be_output)
        return self.act()

    def get_test_cases(self) -> Optional[Dict[str, Any]]:
        """Get generated test cases if available."""
        if self.analysis_result and self.analysis_result.test_suites:
            return self.analysis_result.to_dict()
        return None

    def has_pending_questions(self) -> bool:
        """Check if there are pending questions."""
        return (
            len(self.output.questions) > 0 if self.output else False
        ) or (
            len(self.pending_challenges) > 0
        )

    def generate_defect_reports(
        self,
        requirement: Dict[str, Any],
        ambiguous_points: List[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate simulated defect reports based on requirement analysis.

        Args:
            requirement: Parsed requirement from PM
            ambiguous_points: List of ambiguous points identified

        Returns:
            List of defect report dictionaries
        """
        from src.knowledge.defect_report import DefectGenerator

        generator = DefectGenerator()

        # Generate from ambiguous requirement points
        defects = generator.generate_from_requirement(
            requirement,
            ambiguous_points
        )

        # Generate from tech review (FE/BE analysis)
        if self.fe_output and self.be_output:
            tech_defects = generator.generate_from_tech_review(
                self.fe_output,
                self.be_output
            )
            defects.extend(tech_defects)

        return generator.export_to_dict()

    def analyze_test_case_for_defects(
        self,
        test_case: Dict[str, Any],
        test_result: str = "failed"
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a defect report from a failed test case.

        Args:
            test_case: The test case that failed
            test_result: Result of execution

        Returns:
            Defect report dictionary or None
        """
        from src.knowledge.defect_report import DefectGenerator

        generator = DefectGenerator()
        defect = generator.generate_from_test_case(test_case, test_result)

        if defect:
            return defect.to_dict()
        return None