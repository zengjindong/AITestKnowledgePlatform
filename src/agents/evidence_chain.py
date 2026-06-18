"""
Evidence Chain module for tracking decision依据 (evidence) in test case generation.

This module provides the EvidenceChain class that maintains a traceable
record of all evidence used in generating test cases.
"""
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

from src.config import EVIDENCE_TYPES


class EvidenceType(str, Enum):
    """Types of evidence (Section 5.2.1 from PRD)"""
    REQ_RAW = "REQ_RAW"              # Raw user input
    REQ_STRUCT = "REQ_STRUCT"          # Structured requirement from PM
    BIZ_RULE = "BIZ_RULE"            # Business rule
    QA_PAIR = "QA_PAIR"              # Question & Answer clarification
    FE_PLAN = "FE_PLAN"              # FE implementation plan
    BE_PLAN = "BE_PLAN"              # BE implementation plan
    API_DEF = "API_DEF"              # API definition
    CODE_ANALYZE = "CODE_ANALYZE"    # Code analysis result
    MEMORY = "MEMORY"                # From long-term memory
    KB = "KB"                       # From knowledge base
    QA_REVIEW = "QA_REVIEW"          # QA review comments
    USER_ANSWER = "USER_ANSWER"      # User answer
    FE_ANALYSIS = "FE_ANALYSIS"      # FE analysis result
    BE_ANALYSIS = "BE_ANALYSIS"      # BE analysis result


@dataclass
class EvidenceItem:
    """
    A single piece of evidence in the chain.

    Attributes:
        type: The type of evidence (see EvidenceType)
        ref_id: Reference ID for this evidence (e.g., "pm_doc_001")
        content: The actual evidence content
        source: Optional source file or location
        timestamp: When this evidence was captured
    """
    type: str
    ref_id: str
    content: str
    source: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceItem":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class EvidenceChain:
    """
    A chain of evidence that traces all decisions made during test generation.

    This class maintains a complete audit trail of:
    - Requirements that led to a test case
    - Business rules applied
    - API definitions used
    - Code analysis results
    - User clarifications

    Example:
        chain = EvidenceChain(test_case_id="TC_001")
        chain.add_evidence(EvidenceType.REQ_STRUCT, "pm_doc_001", "User must login first")
        chain.add_evidence(EvidenceType.BIZ_RULE, "mem_rule_005", "Session expires after 30 minutes")
        chain.add_evidence(EvidenceType.API_DEF, "api_login", "POST /api/auth/login")
    """

    test_case_id: str
    evidence_items: List[EvidenceItem] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    chain_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def add_evidence(
        self,
        evidence_type: str,
        ref_id: str,
        content: str,
        source: Optional[str] = None
    ) -> EvidenceItem:
        """
        Add a piece of evidence to the chain.

        Args:
            evidence_type: Type of evidence (should be from EvidenceType or EVIDENCE_TYPES)
            ref_id: Reference ID for this evidence
            content: The evidence content
            source: Optional source file or location

        Returns:
            The created EvidenceItem
        """
        item = EvidenceItem(
            type=evidence_type,
            ref_id=ref_id,
            content=content,
            source=source
        )
        self.evidence_items.append(item)
        self.updated_at = datetime.now().isoformat()
        return item

    def add_evidence_item(self, item: EvidenceItem) -> None:
        """Add an EvidenceItem directly to the chain."""
        self.evidence_items.append(item)
        self.updated_at = datetime.now().isoformat()

    def get_evidence_by_type(self, evidence_type: str) -> List[EvidenceItem]:
        """Get all evidence items of a specific type."""
        return [e for e in self.evidence_items if e.type == evidence_type]

    def get_evidence_by_ref(self, ref_id: str) -> Optional[EvidenceItem]:
        """Get evidence item by its reference ID."""
        for item in self.evidence_items:
            if item.ref_id == ref_id:
                return item
        return None

    def has_sufficient_evidence(self, required_types: List[str] = None) -> bool:
        """
        Check if the chain has sufficient evidence.

        Args:
            required_types: List of required evidence types. If None, checks for any evidence.

        Returns:
            True if evidence chain meets requirements
        """
        if not self.evidence_items:
            return False

        if required_types is None:
            return len(self.evidence_items) > 0

        present_types = {e.type for e in self.evidence_items}
        return all(t in present_types for t in required_types)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the entire chain to a dictionary."""
        return {
            "chain_id": self.chain_id,
            "test_case_id": self.test_case_id,
            "evidence_chain": [e.to_dict() for e in self.evidence_items],
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceChain":
        """Create an EvidenceChain from a dictionary."""
        chain = cls(
            test_case_id=data["test_case_id"],
            chain_id=data.get("chain_id", str(uuid.uuid4())),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat())
        )
        for item_data in data.get("evidence_chain", []):
            chain.add_evidence_item(EvidenceItem.from_dict(item_data))
        return chain

    @classmethod
    def from_json(cls, json_str: str) -> "EvidenceChain":
        """Create an EvidenceChain from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    def validate(self) -> List[str]:
        """
        Validate the evidence chain for completeness.

        Returns:
            List of validation error messages. Empty if valid.
        """
        errors = []

        if not self.test_case_id:
            errors.append("test_case_id is required")

        if not self.evidence_items:
            errors.append("evidence_chain must contain at least one evidence item")

        for i, item in enumerate(self.evidence_items):
            if not item.type:
                errors.append(f"Evidence item {i} missing type")
            if not item.ref_id:
                errors.append(f"Evidence item {i} missing ref_id")
            if not item.content:
                errors.append(f"Evidence item {i} missing content")

        return errors

    def __len__(self) -> int:
        """Return the number of evidence items."""
        return len(self.evidence_items)

    def __repr__(self) -> str:
        return f"EvidenceChain(test_case_id={self.test_case_id}, items={len(self.evidence_items)})"


class EvidenceChainBuilder:
    """
    Helper class to build evidence chains step by step.

    Usage:
        builder = EvidenceChainBuilder("TC_001")
        builder.add_requirement("pm_doc_001", "User must login before placing order")
        builder.add_api("api_order", "POST /api/orders")
        chain = builder.build()
    """

    def __init__(self, test_case_id: str):
        self.chain = EvidenceChain(test_case_id=test_case_id)

    def add_requirement(self, ref_id: str, content: str, source: str = None) -> "EvidenceChainBuilder":
        """Add a requirement evidence item."""
        self.chain.add_evidence(EvidenceType.REQ_STRUCT.value, ref_id, content, source)
        return self

    def add_business_rule(self, ref_id: str, content: str, source: str = None) -> "EvidenceChainBuilder":
        """Add a business rule evidence item."""
        self.chain.add_evidence(EvidenceType.BIZ_RULE.value, ref_id, content, source)
        return self

    def add_api(self, ref_id: str, content: str, source: str = None) -> "EvidenceChainBuilder":
        """Add an API definition evidence item."""
        self.chain.add_evidence(EvidenceType.API_DEF.value, ref_id, content, source)
        return self

    def add_code_analysis(self, ref_id: str, content: str, source: str = None) -> "EvidenceChainBuilder":
        """Add a code analysis evidence item."""
        self.chain.add_evidence(EvidenceType.CODE_ANALYZE.value, ref_id, content, source)
        return self

    def add_user_answer(self, ref_id: str, content: str) -> "EvidenceChainBuilder":
        """Add a user clarification answer."""
        self.chain.add_evidence(EvidenceType.USER_ANSWER.value, ref_id, content)
        return self

    def add_fe_analysis(self, ref_id: str, content: str, source: str = None) -> "EvidenceChainBuilder":
        """Add a frontend analysis result."""
        self.chain.add_evidence(EvidenceType.FE_ANALYSIS.value, ref_id, content, source)
        return self

    def add_be_analysis(self, ref_id: str, content: str, source: str = None) -> "EvidenceChainBuilder":
        """Add a backend analysis result."""
        self.chain.add_evidence(EvidenceType.BE_ANALYSIS.value, ref_id, content, source)
        return self

    # PRD Section 5.2.1 new evidence types
    def add_raw_requirement(self, ref_id: str, content: str) -> "EvidenceChainBuilder":
        """Add raw user requirement (REQ_RAW)."""
        self.chain.add_evidence(EvidenceType.REQ_RAW.value, ref_id, content)
        return self

    def add_qa_pair(self, question: str, answer: str) -> "EvidenceChainBuilder":
        """Add Q&A clarification pair (QA_PAIR)."""
        self.chain.add_evidence(
            EvidenceType.QA_PAIR.value,
            f"qa_{len(self.chain.evidence_items)}",
            f"Q: {question}\nA: {answer}"
        )
        return self

    def add_fe_plan(self, ref_id: str, content: str) -> "EvidenceChainBuilder":
        """Add FE implementation plan (FE_PLAN)."""
        self.chain.add_evidence(EvidenceType.FE_PLAN.value, ref_id, content)
        return self

    def add_be_plan(self, ref_id: str, content: str) -> "EvidenceChainBuilder":
        """Add BE implementation plan (BE_PLAN)."""
        self.chain.add_evidence(EvidenceType.BE_PLAN.value, ref_id, content)
        return self

    def add_memory(self, ref_id: str, content: str) -> "EvidenceChainBuilder":
        """Add evidence from long-term memory (MEMORY)."""
        self.chain.add_evidence(EvidenceType.MEMORY.value, ref_id, content)
        return self

    def add_kb(self, ref_id: str, content: str) -> "EvidenceChainBuilder":
        """Add evidence from knowledge base (KB)."""
        self.chain.add_evidence(EvidenceType.KB.value, ref_id, content)
        return self

    def add_qa_review(self, ref_id: str, content: str) -> "EvidenceChainBuilder":
        """Add QA review comments (QA_REVIEW)."""
        self.chain.add_evidence(EvidenceType.QA_REVIEW.value, ref_id, content)
        return self

    def build(self) -> EvidenceChain:
        """Build and return the evidence chain."""
        return self.chain