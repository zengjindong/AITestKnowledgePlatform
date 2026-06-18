"""
LLM Adapter for local Claude CLI integration.

This module provides a subprocess-based adapter to interact with
locally deployed Claude models via command-line interface.
"""
import json
import subprocess
import logging
from typing import Any, Optional, Dict, List
from dataclasses import dataclass
from pathlib import Path

from src.config import LLM_CONFIG, CLAUDE_CLI_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Standardized response from LLM."""
    content: str
    raw_response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    usage: Optional[Dict[str, int]] = None


class LLMAdapter:
    """
    Adapter for interacting with local LLM via subprocess.

    Supports multiple providers (Claude CLI, Ollama, etc.) and provides
    a unified interface for generating completions.
    """

    def __init__(
        self,
        provider: str = None,
        model: str = None,
        config: Dict[str, Any] = None
    ):
        """
        Initialize the LLM Adapter.

        Args:
            provider: LLM provider (claude, ollama, etc.)
            model: Model name to use
            config: Additional configuration overrides
        """
        self.config = config or {}
        self.provider = provider or LLM_CONFIG.get("provider", "claude")
        self.model = model or LLM_CONFIG.get("model", "claude-sonnet-4-20250514")
        self.max_tokens = self.config.get("max_tokens", LLM_CONFIG.get("max_tokens", 4096))
        self.temperature = self.config.get("temperature", LLM_CONFIG.get("temperature", 0.7))
        self.timeout = self.config.get("timeout", LLM_CONFIG.get("timeout", 120))

        logger.info(f"Initialized LLMAdapter with provider={self.provider}, model={self.model}")

    def _build_prompt(
        self,
        system_prompt: str,
        user_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Build the prompt for the LLM.

        Args:
            system_prompt: System prompt defining agent behavior
            user_message: User's input message
            context: Additional context to include

        Returns:
            Formatted prompt string
        """
        parts = [f"<system>{system_prompt}</system>"]

        if context:
            context_str = json.dumps(context, ensure_ascii=False, indent=2)
            parts.append(f"<context>{context_str}</context>")

        parts.append(f"<user>{user_message}</user>")

        return "\n\n".join(parts)

    def _call_claude_cli(self, prompt: str) -> LLMResponse:
        """
        Call Claude CLI via subprocess.

        Args:
            prompt: The formatted prompt

        Returns:
            LLMResponse with content and metadata
        """
        try:
            # Build the CLI command - use stdin to avoid command-line length limits
            cmd = [
                CLAUDE_CLI_CONFIG.get("command", "claude"),
                "-p",  # Print mode (non-interactive)
                "-",   # Read from stdin
            ]

            # Run subprocess with stdin
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.timeout,
                input=prompt.encode('utf-8'),
                shell=True  # Required for Windows
            )

            # Handle encoding - prefer UTF-8, fallback to GBK or errors='replace'
            try:
                stdout = result.stdout.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    stdout = result.stdout.decode('gbk')
                except UnicodeDecodeError:
                    stdout = result.stdout.decode('utf-8', errors='replace')

            stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ""

            if result.returncode != 0:
                logger.error(f"Claude CLI error: {stderr}")
                return LLMResponse(
                    content="",
                    error=f"CLI error: {stderr}"
                )

            # Parse response
            content = stdout.strip()

            # Try to detect if it's JSON
            if content.startswith("{") or content.startswith("["):
                try:
                    response_data = json.loads(content)
                    content = response_data.get("content", content)
                except json.JSONDecodeError:
                    pass

            return LLMResponse(content=content, raw_response={"stdout": stdout})

        except subprocess.TimeoutExpired:
            logger.error(f"Claude CLI timeout after {self.timeout}s")
            return LLMResponse(content="", error=f"Timeout after {self.timeout}s")
        except FileNotFoundError:
            logger.error("Claude CLI not found. Please ensure it's installed and in PATH.")
            return LLMResponse(content="", error="Claude CLI not found")
        except Exception as e:
            logger.error(f"Unexpected error calling Claude CLI: {e}")
            return LLMResponse(content="", error=str(e))

    def _call_ollama(self, prompt: str) -> LLMResponse:
        """
        Call Ollama via subprocess.

        Args:
            prompt: The formatted prompt

        Returns:
            LLMResponse with content and metadata
        """
        try:
            cmd = [
                "ollama", "run",
                self.model,
                prompt
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                shell=True
            )

            if result.returncode != 0:
                return LLMResponse(content="", error=f"Ollama error: {result.stderr}")

            return LLMResponse(content=result.stdout.strip(), raw_response={"stdout": result.stdout})

        except Exception as e:
            return LLMResponse(content="", error=str(e))

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        json_response: bool = False
    ) -> LLMResponse:
        """
        Generate a response from the LLM.

        Args:
            system_prompt: System prompt defining agent behavior
            user_message: User's input message
            context: Additional context to include
            json_response: If True, attempt to parse as JSON

        Returns:
            LLMResponse with generated content
        """
        prompt = self._build_prompt(system_prompt, user_message, context)

        # Call appropriate provider
        if self.provider == "claude":
            response = self._call_claude_cli(prompt)
        elif self.provider == "ollama":
            response = self._call_ollama(prompt)
        else:
            # Default fallback
            response = self._call_claude_cli(prompt)

        # Optionally parse as JSON
        if json_response and response.content:
            try:
                response.raw_response = json.loads(response.content)
            except json.JSONDecodeError:
                logger.warning("Response is not valid JSON despite json_response=True")

        return response

    def generate_structured(
        self,
        system_prompt: str,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        schema: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a structured JSON response from the LLM.

        Args:
            system_prompt: System prompt defining agent behavior
            user_message: User's input message
            context: Additional context to include
            schema: JSON schema to validate against (optional)

        Returns:
            Parsed JSON response or None if parsing fails
        """
        # Add JSON formatting instruction to system prompt
        enhanced_system = system_prompt + (
            "\n\nIMPORTANT: You must respond with valid JSON only. "
            "Do not include any text before or after the JSON."
        )

        response = self.generate(enhanced_system, user_message, context, json_response=True)

        if response.error:
            logger.error(f"Structured generation error: {response.error}")
            return None

        if response.raw_response:
            return response.raw_response

        # Try to extract JSON from content
        try:
            # Handle markdown code blocks
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return None

    def test_connection(self) -> bool:
        """
        Test if the LLM connection is working.

        Returns:
            True if connection is successful, False otherwise
        """
        try:
            response = self.generate(
                system_prompt="You are a helpful assistant.",
                user_message="Reply with 'OK' if you can hear me.",
            )
            return response.error is None and "OK" in response.content.upper()
        except Exception:
            return False


class MockLLMAdapter(LLMAdapter):
    """
    Mock LLM Adapter for testing without actual LLM calls.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.responses: List[str] = []
        self.call_count = 0

    def set_mock_response(self, response: str):
        """Set a predefined mock response."""
        self.responses.append(response)

    def _call_claude_cli(self, prompt: str) -> LLMResponse:
        self.call_count += 1
        if self.responses:
            return LLMResponse(content=self.responses.pop(0))
        return LLMResponse(
            content=f"Mock response #{self.call_count}: This is a simulated response."
        )

    def generate(self, system_prompt: str, user_message: str, context: Optional[Dict[str, Any]] = None, json_response: bool = False) -> LLMResponse:
        return self._call_claude_cli(system_prompt + user_message)

    def generate_structured(self, system_prompt: str, user_message: str, context: Optional[Dict[str, Any]] = None, schema: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Generate a structured JSON mock response."""
        import json
        response = self._call_claude_cli(system_prompt + user_message)
        if response.error:
            return None
        try:
            return json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            # Return a default structure
            return {
                "requirement_id": "REQ_001",
                "title": "Mock Requirement",
                "description": "Mock requirement for testing",
                "user_stories": [],
                "business_rules": [],
                "acceptance_criteria": [],
                "ambiguous_points": [],
                "entities": []
            }