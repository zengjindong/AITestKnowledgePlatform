"""
Product Manager (PM) Agent for requirements parsing and analysis.

This agent is responsible for:
- Parsing natural language requirements into structured documentation
- Identifying business rules and extracting user stories
- Defining acceptance criteria
- Detecting ambiguous requirements and asking clarification questions
"""
import json
import logging
from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent, AgentRole, AgentOutput, AgentState
from src.agents.evidence_chain import EvidenceChain, EvidenceChainBuilder

logger = logging.getLogger(__name__)


class PMInputSchema:
    """Expected input schema for PM Agent."""

    @staticmethod
    def get_requirement_parsing_prompt() -> str:
        return """Parse the user's natural language requirement into a structured format.

Output a JSON object with the following structure:
{
    "requirement_id": "REQ_001",
    "title": "Brief title of the requirement",
    "description": "Detailed description",
    "user_stories": [
        {
            "id": "US_001",
            "as_a": "type of user",
            "i_want": "what they want",
            "so_that": "benefit"
        }
    ],
    "business_rules": [
        {
            "id": "BR_001",
            "rule": "The business rule text",
            "source": "where this rule comes from"
        }
    ],
    "acceptance_criteria": [
        {
            "id": "AC_001",
            "criteria": "The acceptance criteria text",
            "given": "precondition",
            "when": "action",
            "then": "expected result"
        }
    ],
    "ambiguous_points": [
        {
            "point": "description of ambiguity",
            "question": "question to resolve it"
        }
    ],
    "entities": [
        {
            "name": "Entity name",
            "attributes": ["list of attributes"]
        }
    ]
}

IMPORTANT: If there are any ambiguous or unclear points in the requirements,
you MUST include them in the "ambiguous_points" array with specific questions.
DO NOT guess or make assumptions - ask questions instead."""

    @staticmethod
    def get_clarification_prompt(existing_requirement: Dict, questions: List[str]) -> str:
        return f"""The following requirement has been analyzed but has unclear points:

{json.dumps(existing_requirement, ensure_ascii=False, indent=2)}

Please answer the following clarification questions:
{chr(10).join(f"- {q}" for q in questions)}

Provide your answers in JSON format:
{{
    "answers": [
        {{
            "question_id": "the question",
            "answer": "the user's answer"
        }}
    ]
}}"""


class PMOutputSchema:
    """Expected output schema for PM Agent."""

    @staticmethod
    def validate(data: Dict[str, Any]) -> List[str]:
        """Validate PM output and return list of errors."""
        errors = []

        required_fields = ["requirement_id", "title", "user_stories", "business_rules"]
        for field in required_fields:
            if field not in data:
                errors.append(f"Missing required field: {field}")

        if "ambiguous_points" in data and data["ambiguous_points"]:
            errors.append("Requirements contain ambiguous points that need clarification")

        return errors

    @staticmethod
    def is_complete(data: Dict[str, Any]) -> bool:
        """Check if the requirement parsing is complete (no ambiguous points)."""
        return (
            PMOutputSchema.validate(data) == [] and
            data.get("ambiguous_points", []) == []
        )


class ProductManagerAgent(BaseAgent):
    """
    Product Manager Agent responsible for requirement parsing.

    This agent transforms natural language requirements into structured
    documentation and identifies any ambiguities that need clarification.
    """

    def __init__(self, llm_adapter=None, config: Dict[str, Any] = None):
        super().__init__(role=AgentRole.PM, llm_adapter=llm_adapter, config=config)
        self.parsed_requirements: Dict[str, Any] = {}
        self.questions_asked: List[str] = []

    def _think_impl(self, input_data: Any) -> Dict[str, Any]:
        """
        Analyze the input requirement and determine parsing strategy.

        Args:
            input_data: Natural language requirement from user

        Returns:
            Dictionary containing thought process and identified issues
        """
        thoughts = {
            "input_type": type(input_data).__name__,
            "action_plan": ["parse_requirement"],
            "questions": [],
            "evidence_needed": ["user_input"],
            "key_entities": [],
            "potential_ambiguities": []
        }

        # Check if this is a follow-up with answers to previous questions
        if isinstance(input_data, dict) and "answers" in input_data:
            thoughts["is_clarification"] = True
            thoughts["action_plan"] = ["update_requirement"]
        else:
            thoughts["is_clarification"] = False
            thoughts["original_requirement"] = str(input_data)[:200]

        return thoughts

    def act(self, input_data: Any) -> AgentOutput:
        """
        Parse the requirement and generate structured output.

        Args:
            input_data: Natural language requirement

        Returns:
            AgentOutput with structured requirements or clarification questions
        """
        self.state = AgentState.ACTING
        self.output = AgentOutput(role=self.role, state=AgentState.ACTING)

        try:
            thoughts = self._think_impl(input_data)

            # Generate structured output
            user_message = self._format_for_llm(input_data, thoughts)
            response = self.llm_adapter.generate_structured(
                system_prompt=PMInputSchema.get_requirement_parsing_prompt(),
                user_message=user_message
            )

            if response is None:
                self.output.error = "Failed to parse requirements"
                self.output.state = AgentState.ERROR
                return self.output

            # Validate output
            validation_errors = PMOutputSchema.validate(response)
            if validation_errors:
                # Check if there are ambiguous points
                if "ambiguous_points" in response and response["ambiguous_points"]:
                    self._handle_ambiguous_requirements(response)
                else:
                    self.output.error = f"Validation errors: {validation_errors}"
                    self.output.state = AgentState.ERROR

            # Check for ambiguous points
            if response.get("ambiguous_points"):
                self._handle_ambiguous_requirements(response)
            else:
                # Complete requirement parsed
                self.parsed_requirements = response
                self.output.content = response
                self.output.state = AgentState.DONE

                # Build evidence chain
                self._build_evidence_chain(response)

        except Exception as e:
            logger.error(f"PM Agent error: {e}")
            self.output.error = str(e)
            self.output.state = AgentState.ERROR

        return self.output

    def _format_for_llm(self, input_data: Any, thoughts: Dict[str, Any]) -> str:
        """Format input for LLM processing."""
        if isinstance(input_data, dict) and "answers" in input_data:
            return PMInputSchema.get_clarification_prompt(
                self.parsed_requirements,
                [a["question"] for a in input_data.get("previous_questions", [])]
            )
        return str(input_data)

    def _handle_ambiguous_requirements(self, response: Dict[str, Any]) -> None:
        """Handle requirements with ambiguous points."""
        ambiguous = response.get("ambiguous_points", [])
        self.questions_asked = [a["question"] for a in ambiguous]

        self.output.questions = self.questions_asked
        self.output.content = response  # Store partial parse
        self.output.state = AgentState.WAITING

        logger.info(f"PM Agent identified {len(ambiguous)} ambiguous points")

    def _build_evidence_chain(self, requirement: Dict[str, Any]) -> None:
        """Build evidence chain for the parsed requirement."""
        builder = EvidenceChainBuilder(f"pm_{requirement.get('requirement_id', 'unknown')}")
        builder.add_requirement(
            ref_id=requirement.get("requirement_id", "unknown"),
            content=f"Title: {requirement.get('title', 'N/A')}\nDescription: {requirement.get('description', 'N/A')}"
        )

        # Add business rules
        for br in requirement.get("business_rules", []):
            builder.add_business_rule(
                ref_id=br.get("id", "unknown"),
                content=br.get("rule", "")
            )

        # Add user stories
        for us in requirement.get("user_stories", []):
            builder.add_requirement(
                ref_id=us.get("id", "unknown"),
                content=f"User Story: As a {us.get('as_a')} I want {us.get('i_want')} so that {us.get('so_that')}"
            )

        self.output.evidence_chain = builder.build()

    def get_parsed_requirement(self) -> Optional[Dict[str, Any]]:
        """Get the parsed requirement if complete."""
        if PMOutputSchema.is_complete(self.parsed_requirements):
            return self.parsed_requirements
        return None

    def has_pending_questions(self) -> bool:
        """Check if there are pending clarification questions."""
        return len(self.questions_asked) > 0

    def apply_clarifications(self, answers: List[Dict[str, str]]) -> None:
        """
        Apply user's clarification answers to the requirement.

        Args:
            answers: List of {"question": "...", "answer": "..."} dicts
        """
        for answer in answers:
            # Find the matching ambiguous point and resolve it
            for ambiguous in self.parsed_requirements.get("ambiguous_points", []):
                if ambiguous["question"] == answer["question"]:
                    # Remove from ambiguous points
                    self.parsed_requirements["ambiguous_points"].remove(ambiguous)

                    # Add the clarification as a business rule
                    self.parsed_requirements.setdefault("business_rules", []).append({
                        "id": f"BR_CLARIFIED_{len(answers)}",
                        "rule": f"{answer['question']} -> {answer['answer']}",
                        "source": "user_clarification"
                    })

                    # Add to evidence chain
                    if self.output and self.output.evidence_chain:
                        self.output.evidence_chain.add_evidence(
                            evidence_type="USER_ANSWER",
                            ref_id=f"clarification_{len(answers)}",
                            content=f"Q: {answer['question']}\nA: {answer['answer']}"
                        )

        # Update questions asked
        self.questions_asked = []

        logger.info(f"Applied {len(answers)} clarification answers")