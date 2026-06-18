"""
Tests for the Multi-Agent AI Test Engineer System.
"""
import json
import unittest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents.evidence_chain import EvidenceChain, EvidenceChainBuilder, EvidenceType
from src.agents.base_agent import AgentRole, AgentState, AgentOutput, AgentMessage
from src.adapters.llm_adapter import MockLLMAdapter, LLMResponse
from src.memory.storage import MemoryStorage, MemoryUnit, QARecord


class TestEvidenceChain(unittest.TestCase):
    """Test evidence chain functionality."""

    def test_create_evidence_chain(self):
        """Test creating an evidence chain."""
        chain = EvidenceChain(test_case_id="TC_001")
        self.assertEqual(chain.test_case_id, "TC_001")
        self.assertEqual(len(chain), 0)

    def test_add_evidence(self):
        """Test adding evidence to a chain."""
        chain = EvidenceChain(test_case_id="TC_001")
        item = chain.add_evidence(
            evidence_type=EvidenceType.REQ_STRUCT.value,
            ref_id="pm_doc_001",
            content="User must login first"
        )
        self.assertEqual(len(chain), 1)
        self.assertEqual(item.ref_id, "pm_doc_001")

    def test_evidence_chain_builder(self):
        """Test evidence chain builder."""
        builder = EvidenceChainBuilder("TC_002")
        builder.add_requirement("pm_001", "Login required")
        builder.add_business_rule("br_001", "Session expires in 30 minutes")
        builder.add_api("api_login", "POST /api/login")

        chain = builder.build()
        self.assertEqual(chain.test_case_id, "TC_002")
        self.assertEqual(len(chain), 3)

    def test_serialize_deserialize(self):
        """Test JSON serialization."""
        chain = EvidenceChain(test_case_id="TC_001")
        chain.add_evidence(EvidenceType.BIZ_RULE.value, "br_001", "Test rule")

        json_str = chain.to_json()
        restored = EvidenceChain.from_json(json_str)

        self.assertEqual(restored.test_case_id, "TC_001")
        self.assertEqual(len(restored), 1)


class TestAgentMessage(unittest.TestCase):
    """Test agent message functionality."""

    def test_create_message(self):
        """Test creating an agent message."""
        msg = AgentMessage(
            sender=AgentRole.PM,
            receiver=AgentRole.QA,
            content={"test": "data"},
            message_type="request"
        )
        self.assertEqual(msg.sender, AgentRole.PM)
        self.assertEqual(msg.receiver, AgentRole.QA)
        self.assertEqual(msg.message_type, "request")

    def test_message_to_dict(self):
        """Test message serialization."""
        msg = AgentMessage(
            sender=AgentRole.PM,
            receiver=AgentRole.QA,
            content="Test message"
        )
        data = msg.to_dict()
        self.assertEqual(data["sender"], "pm")
        self.assertEqual(data["receiver"], "qa")


class TestMockLLMAdapter(unittest.TestCase):
    """Test mock LLM adapter."""

    def test_mock_response(self):
        """Test mock adapter returns predefined response."""
        adapter = MockLLMAdapter()
        adapter.set_mock_response("Test response")

        response = adapter.generate(
            system_prompt="You are a test.",
            user_message="Hello"
        )
        self.assertEqual(response.content, "Test response")

    def test_mock_call_count(self):
        """Test mock adapter tracks call count."""
        adapter = MockLLMAdapter()

        adapter.generate("prompt1", "msg1")
        adapter.generate("prompt2", "msg2")

        self.assertEqual(adapter.call_count, 2)


class TestMemoryStorage(unittest.TestCase):
    """Test memory storage functionality."""

    def setUp(self):
        """Set up test storage."""
        self.storage = MemoryStorage(":memory:")

    def test_save_memory_unit(self):
        """Test saving a memory unit."""
        memory = MemoryUnit(
            content="Test business rule",
            source_type="user_answer"
        )
        result = self.storage.save_memory_unit(memory)
        self.assertTrue(result)

    def test_search_memory_units(self):
        """Test searching memory units."""
        memory = MemoryUnit(
            content="Login required for all users",
            source_type="pm_requirement"
        )
        self.storage.save_memory_unit(memory)

        results = self.storage.search_memory_units(query="Login")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "Login required for all users")

    def test_save_qa_record(self):
        """Test saving Q&A record."""
        record = QARecord(
            context="Login requirement",
            question="What is the password min length?",
            answer="Minimum 8 characters"
        )
        result = self.storage.save_qa_record(record)
        self.assertTrue(result)

    def test_storage_stats(self):
        """Test getting storage statistics."""
        memory = MemoryUnit(content="Test", source_type="test")
        self.storage.save_memory_unit(memory)

        stats = self.storage.get_stats()
        self.assertIn("memory_units", stats)


class TestIntegration(unittest.TestCase):
    """Integration tests."""

    def test_full_workflow_mock(self):
        """Test full workflow with mock agents."""
        from src.orchestrator.workflow import MockOrchestrator
        from src.memory.storage import MemoryStorage

        storage = MemoryStorage(":memory:")
        orchestrator = MockOrchestrator(memory_storage=storage)

        # Run with a simple requirement
        result = orchestrator.run("Test requirement for login")

        # Check result structure
        self.assertIn("status", result)


if __name__ == "__main__":
    unittest.main()