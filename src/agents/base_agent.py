"""
Base Agent class for the Multi-Agent AI Test Engineer System.

This module provides the abstract base class that all agents (PM, FE, BE, QA)
must inherit from, implementing the think() and act() pattern.
"""
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
import uuid

from src.adapters.llm_adapter import LLMAdapter, LLMResponse
from src.agents.evidence_chain import EvidenceChain, EvidenceChainBuilder
from src.config import AGENT_CONFIG

logger = logging.getLogger(__name__)


class AgentRole(str, Enum):
    """Enumeration of agent roles."""
    PM = "pm"
    FE = "fe"
    BE = "be"
    QA = "qa"


class AgentState(str, Enum):
    """States an agent can be in."""
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    WAITING = "waiting"
    DONE = "done"
    ERROR = "error"


@dataclass
class AgentMessage:
    """
    Message passed between agents.

    Attributes:
        sender: The role of the sending agent
        receiver: The role of the receiving agent (or "all")
        content: The message content
        message_type: Type of message (e.g., "request", "response", "question", "clarification")
        metadata: Additional metadata
        timestamp: When the message was created
    """
    sender: AgentRole
    receiver: AgentRole
    content: Any
    message_type: str = "request"
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "sender": self.sender.value,
            "receiver": self.receiver.value,
            "content": self.content,
            "message_type": self.message_type,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


@dataclass
class AgentOutput:
    """
    Output produced by an agent after thinking and acting.

    Attributes:
        role: The agent's role
        state: Final state after processing
        content: The output content
        thinking: The thinking/reasoning process
        evidence_chain: Evidence chain if applicable
        questions: Clarification questions (if any)
        messages: Messages to send to other agents
        error: Error message if any
    """
    role: AgentRole
    state: AgentState
    content: Any = None
    thinking: Dict[str, Any] = field(default_factory=dict)
    evidence_chain: Optional[EvidenceChain] = None
    questions: List[str] = field(default_factory=list)
    messages: List[AgentMessage] = field(default_factory=list)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_questions(self) -> bool:
        """Check if there are pending clarification questions."""
        return len(self.questions) > 0

    def is_successful(self) -> bool:
        """Check if the agent completed successfully."""
        return self.state == AgentState.DONE and self.error is None


class BaseAgent(ABC):
    """
    Abstract base class for all agents in the system.

    Each agent must implement:
    - think(): Analyze inputs and prepare for action
    - act(): Execute the agent's specific task

    The agent follows a think-then-act pattern where:
    1. think() processes inputs and determines what needs to be done
    2. act() performs the actual work and generates output
    """

    def __init__(
        self,
        role: AgentRole,
        llm_adapter: Optional[LLMAdapter] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the agent.

        Args:
            role: The agent's role (PM, FE, BE, QA)
            llm_adapter: LLM adapter for generating responses
            config: Agent-specific configuration
        """
        self.role = role
        self.config = config or {}
        self.llm_adapter = llm_adapter or LLMAdapter()

        # Load agent configuration
        agent_config = AGENT_CONFIG.get(role.value, {})
        self.name = agent_config.get("name", role.value.upper())
        self.system_prompt = agent_config.get("system_prompt", "")

        # State management
        self.state = AgentState.IDLE
        self.context: Dict[str, Any] = {}
        self.output: Optional[AgentOutput] = None
        self.messages: List[AgentMessage] = []

        # Memory reference
        self.memory = None  # Set by orchestrator

        logger.info(f"Initialized {self.name} agent")

    def set_context(self, context: Dict[str, Any]) -> None:
        """Set the execution context for this agent."""
        self.context = context

    def add_message(self, message: AgentMessage) -> None:
        """Add a message to the agent's message queue."""
        self.messages.append(message)
        logger.debug(f"{self.name} received message from {message.sender.value}")

    def think(self, input_data: Any) -> Dict[str, Any]:
        """
        Analyze inputs and prepare for action.

        This method processes the input, reviews context, and determines
        what actions need to be taken. It may generate clarification questions.

        Args:
            input_data: The input to process

        Returns:
            A dictionary containing processed thoughts and any questions
        """
        self.state = AgentState.THINKING

        thoughts = {
            "input_summary": self._summarize_input(input_data),
            "context_review": self._review_context(),
            "action_plan": [],
            "questions": [],
            "evidence_needed": []
        }

        return thoughts

    @abstractmethod
    def _think_impl(self, input_data: Any) -> Dict[str, Any]:
        """
        Agent-specific thinking implementation.

        Override this in subclasses to implement specific agent behavior.

        Args:
            input_data: The input to process

        Returns:
            A dictionary with think results
        """
        pass

    def act(self, input_data: Any) -> AgentOutput:
        """
        Execute the agent's primary function.

        This method implements the think-act pattern:
        1. First calls think() to prepare
        2. Then performs the actual work
        3. Returns an AgentOutput with results

        Args:
            input_data: The input to process

        Returns:
            AgentOutput containing the results
        """
        self.state = AgentState.ACTING
        self.output = AgentOutput(role=self.role, state=AgentState.ACTING)

        try:
            # Step 1: Think - capture reasoning process
            thoughts = self._think_impl(input_data)
            self.output.thinking = thoughts  # Store thinking for display

            # Step 2: Check for questions (ambiguous requirements)
            if thoughts.get("questions"):
                self.output.questions = thoughts["questions"]
                self.output.state = AgentState.WAITING
                return self.output

            # Step 3: Generate response via LLM
            response = self._generate_response(input_data, thoughts)

            # Step 4: Build output
            self.output.content = response.content if hasattr(response, 'content') else response
            self.output.state = AgentState.DONE

            # Step 5: Build evidence chain if applicable
            if thoughts.get("evidence_needed"):
                self._build_evidence_chain(thoughts)

        except Exception as e:
            logger.error(f"{self.name} error during act(): {e}")
            self.output.error = str(e)
            self.output.state = AgentState.ERROR

        return self.output

    def _summarize_input(self, input_data: Any) -> str:
        """Create a summary of the input for thinking."""
        if isinstance(input_data, str):
            return input_data[:500] + "..." if len(str(input_data)) > 500 else str(input_data)
        elif isinstance(input_data, dict):
            return json.dumps(input_data, ensure_ascii=False)[:500]
        else:
            return str(type(input_data))

    def _review_context(self) -> Dict[str, Any]:
        """Review current context and determine what to use."""
        return {
            "has_history": bool(self.context.get("history")),
            "has_requirements": bool(self.context.get("requirements")),
            "memory_available": self.memory is not None
        }

    def _generate_response(self, input_data: Any, thoughts: Dict[str, Any]) -> LLMResponse:
        """Generate response using the LLM adapter."""
        user_message = self._format_user_message(input_data, thoughts)
        return self.llm_adapter.generate(
            system_prompt=self.system_prompt,
            user_message=user_message,
            context=thoughts
        )

    def _format_user_message(self, input_data: Any, thoughts: Dict[str, Any]) -> str:
        """Format the user message for the LLM."""
        return f"""Process the following input and provide your output:

Input:
{json.dumps(input_data, ensure_ascii=False, indent=2)}

Your thoughts:
{json.dumps(thoughts, ensure_ascii=False, indent=2)}
"""

    def _build_evidence_chain(self, thoughts: Dict[str, Any]) -> None:
        """Build an evidence chain from the thinking process."""
        # Override in subclasses as needed
        pass

    def ask_question(self, question: str) -> AgentMessage:
        """
        Create a question message to be sent to the user or other agents.

        Args:
            question: The question to ask

        Returns:
            An AgentMessage containing the question
        """
        return AgentMessage(
            sender=self.role,
            receiver=AgentRole.PM,  # Default to PM for questions
            content=question,
            message_type="question"
        )

    def send_message(
        self,
        receiver: AgentRole,
        content: Any,
        message_type: str = "request"
    ) -> AgentMessage:
        """
        Create a message to send to another agent.

        Args:
            receiver: The agent to send to
            content: Message content
            message_type: Type of message

        Returns:
            The created message
        """
        msg = AgentMessage(
            sender=self.role,
            receiver=receiver,
            content=content,
            message_type=message_type
        )
        self.messages.append(msg)
        return msg

    def receive_message(self, message: AgentMessage) -> None:
        """Receive and process a message from another agent."""
        self.add_message(message)

    def respond_to_challenge(self, challenge: str, challenge_id: str) -> AgentOutput:
        """
        Respond to a challenge from QA or another agent.

        Args:
            challenge: The challenge/question text
            challenge_id: Unique identifier for this challenge

        Returns:
            AgentOutput with the response
        """
        self.state = AgentState.ACTING
        self.output = AgentOutput(role=self.role, state=AgentState.ACTING)

        try:
            # Build prompt for the challenge response
            system_prompt = (
                f"You are a {self.name}. You have been challenged by the QA Agent. "
                f"Please provide a clear, evidence-based response to the challenge below. "
                f"If you disagree with the challenge, provide your reasoning. "
                f"If you agree, acknowledge and explain how you will address it."
            )
            user_message = f"Challenge from QA:\n{challenge}"

            # Generate response via LLM
            response = self.llm_adapter.generate(
                system_prompt=system_prompt,
                user_message=user_message,
                context={"challenge_id": challenge_id}
            )

            self.output.content = response.content if hasattr(response, 'content') else response
            self.output.state = AgentState.DONE
            self.output.metadata["challenge_id"] = challenge_id

        except Exception as e:
            logger.error(f"{self.name} error responding to challenge: {e}")
            self.output.error = str(e)
            self.output.state = AgentState.ERROR

        return self.output

    def get_output(self) -> AgentOutput:
        """Get the agent's output."""
        return self.output

    def reset(self) -> None:
        """Reset the agent to idle state."""
        self.state = AgentState.IDLE
        self.context = {}
        self.output = None
        self.messages = []

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(role={self.role.value}, state={self.state.value})"