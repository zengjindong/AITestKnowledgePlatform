"""
Defect Report Module for bug tracking and simulation.

Generates simulated defect reports based on requirement analysis,
test case failures, and code review findings.

PRD Reference: Section 3.4 - QA Agent output includes "缺陷报告（模拟）"
"""
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Bug severity levels."""
    CRITICAL = "critical"  # System crash, data loss
    HIGH = "high"          # Major functionality broken
    MEDIUM = "medium"      # Feature partially working
    LOW = "low"            # Minor issue, cosmetic


class Priority(str, Enum):
    """Bug priority levels."""
    P0 = "P0"  # Critical, fix immediately
    P1 = "P1"  # High priority
    P2 = "P2"  # Medium priority
    P3 = "P3"  # Low priority, fix when possible


class BugStatus(str, Enum):
    """Bug status."""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"


@dataclass
class DefectStep:
    """Steps to reproduce a bug."""
    step_number: int
    action: str
    expected: str
    actual: str


@dataclass
class DefectReport:
    """
    A simulated defect/bug report.

    Attributes:
        defect_id: Unique identifier
        title: Bug title
        description: Detailed description
        severity: Critical/High/Medium/Low
        priority: P0/P1/P2/P3
        status: Current status
        steps_to_reproduce: List of reproduction steps
        related_requirement_id: Associated requirement
        related_test_case_id: Associated test case that found this
        evidence: Evidence supporting this defect
        assignee: Suggested assignee (based on code analysis)
        affected_components: List of affected file paths
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    defect_id: str = field(default_factory=lambda: f"DEF-{uuid.uuid4().hex[:8].upper()}")
    title: str = ""
    description: str = ""
    severity: Severity = Severity.MEDIUM
    priority: Priority = Priority.P2
    status: BugStatus = BugStatus.OPEN
    steps_to_reproduce: List[DefectStep] = field(default_factory=list)
    related_requirement_id: Optional[str] = None
    related_test_case_id: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    assignee: str = ""
    affected_components: List[str] = field(default_factory=list)
    root_cause: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "defect_id": self.defect_id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "steps_to_reproduce": [
                {
                    "step_number": s.step_number,
                    "action": s.action,
                    "expected": s.expected,
                    "actual": s.actual
                }
                for s in self.steps_to_reproduce
            ],
            "related_requirement_id": self.related_requirement_id,
            "related_test_case_id": self.related_test_case_id,
            "evidence": self.evidence,
            "assignee": self.assignee,
            "affected_components": self.affected_components,
            "root_cause": self.root_cause,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }


class DefectGenerator:
    """
    Generate simulated defect reports based on analysis.

    Identifies potential bugs from:
    - Requirement ambiguity
    - Edge cases in business rules
    - API contract violations
    - Frontend/backend contract mismatches
    """

    def __init__(self):
        self.defects: List[DefectReport] = []

    def generate_from_requirement(
        self,
        requirement: Dict[str, Any],
        ambiguous_points: List[Dict[str, str]] = None
    ) -> List[DefectReport]:
        """
        Generate potential defects from ambiguous requirement points.

        Args:
            requirement: Parsed requirement from PM
            ambiguous_points: List of ambiguous points identified

        Returns:
            List of generated defect reports
        """
        defects = []
        req_id = requirement.get("requirement_id", "unknown")

        # Generate defects from ambiguous points
        if ambiguous_points:
            for i, point in enumerate(ambiguous_points):
                defect = DefectReport(
                    title=f"潜在缺陷: {point.get('point', f'模糊点 {i+1}')}",
                    description=f"由于需求不明确可能导致实现与预期不符: {point.get('question', '')}",
                    severity=Severity.HIGH,
                    priority=Priority.P1,
                    related_requirement_id=req_id,
                    root_cause=f"需求模糊: {point.get('point', '')}",
                    evidence={
                        "source": "requirement_ambiguity",
                        "question": point.get("question", "")
                    }
                )
                defects.append(defect)

        # Generate defects from business rules
        for rule in requirement.get("business_rules", []):
            rule_text = rule.get("rule", "")
            if not rule_text:
                continue

            # Check for edge case vulnerabilities
            edge_case_defect = self._analyze_edge_case(rule_text, req_id)
            if edge_case_defect:
                defects.append(edge_case_defect)

            # Check for boundary condition issues
            boundary_defect = self._analyze_boundary(rule_text, req_id)
            if boundary_defect:
                defects.append(boundary_defect)

        self.defects.extend(defects)
        return defects

    def generate_from_test_case(
        self,
        test_case: Dict[str, Any],
        test_result: str = "failed"
    ) -> Optional[DefectReport]:
        """
        Generate a defect report from a failed test case.

        Args:
            test_case: The test case that failed
            test_result: Result of execution

        Returns:
            Generated defect report or None
        """
        defect = DefectReport(
            title=f"测试失败: {test_case.get('title', 'Unknown test')}",
            description=f"测试用例执行失败: {test_case.get('description', '')}",
            severity=Severity.MEDIUM,
            priority=Priority.P2,
            related_test_case_id=test_case.get("test_case_id"),
            related_requirement_id=test_case.get("requirement_id"),
            steps_to_reproduce=[
                DefectStep(
                    step_number=i+1,
                    action=step.get("action", ""),
                    expected=step.get("expected_result", ""),
                    actual=f"测试执行返回: {test_result}"
                )
                for i, step in enumerate(test_case.get("test_steps", []))
            ],
            evidence={
                "source": "test_failure",
                "test_case": test_case.get("title"),
                "test_result": test_result
            }
        )
        self.defects.append(defect)
        return defect

    def generate_from_tech_review(
        self,
        fe_output: Dict[str, Any],
        be_output: Dict[str, Any]
    ) -> List[DefectReport]:
        """
        Generate potential defects from FE/BE technical review.

        Args:
            fe_output: Frontend analysis output
            be_output: Backend analysis output

        Returns:
            List of potential defects
        """
        defects = []

        # Check for API contract mismatches
        fe_apis = set()
        be_apis = set()

        for api in fe_output.get("api_dependencies", []):
            fe_apis.add(f"{api.get('method', 'GET')} {api.get('endpoint', '')}")

        for api in be_output.get("api_definitions", []):
            be_apis.add(f"{api.get('method', 'GET')} {api.get('path', api.get('endpoint', ''))}")

        # Find missing APIs
        missing_in_be = fe_apis - be_apis
        for missing in missing_in_be:
            defect = DefectReport(
                title=f"API 契约不一致: {missing}",
                description=f"前端依赖的 API 后端未提供: {missing}",
                severity=Severity.CRITICAL,
                priority=Priority.P0,
                assignee="Backend Engineer",
                root_cause="API 契约未对齐",
                evidence={
                    "source": "tech_review",
                    "missing_api": missing
                }
            )
            defects.append(defect)

        # Check for parameter mismatches
        # (simplified check - full impl would compare schema)

        # Check for data type mismatches
        fe_components = fe_output.get("affected_components", [])
        for comp in fe_components:
            props = comp.get("props", [])
            # Simplified check for potential type issues
            for prop in props:
                if "id" in prop.lower() and "phone" in prop.lower():
                    defect = DefectReport(
                        title=f"潜在数据验证问题: {comp.get('name', '')}.{prop}",
                        description=f"组件属性 {prop} 可能存在数据类型验证问题",
                        severity=Severity.MEDIUM,
                        priority=Priority.P2,
                        affected_components=[comp.get("file", "")],
                        evidence={
                            "source": "tech_review",
                            "component": comp.get("name"),
                            "property": prop
                        }
                    )
                    defects.append(defect)

        self.defects.extend(defects)
        return defects

    def _analyze_edge_case(self, rule_text: str, req_id: str) -> Optional[DefectReport]:
        """Analyze a business rule for edge case vulnerabilities."""
        rule_lower = rule_text.lower()

        # Check for common edge case keywords
        edge_case_keywords = [
            "为空", "null", "nil", "空值", "边界", "boundary",
            "最大", "maximum", "最小", "minimum", "超过"
        ]

        for keyword in edge_case_keywords:
            if keyword in rule_lower:
                return DefectReport(
                    title=f"边界条件未覆盖: {rule_text[:50]}",
                    description=f"业务规则 '{rule_text}' 存在边界条件 '{keyword}'，需要专门的边界测试",
                    severity=Severity.MEDIUM,
                    priority=Priority.P2,
                    related_requirement_id=req_id,
                    root_cause=f"边界条件处理: {keyword}",
                    evidence={
                        "source": "edge_case_analysis",
                        "rule": rule_text,
                        "keyword": keyword
                    }
                )
        return None

    def _analyze_boundary(self, rule_text: str, req_id: str) -> Optional[DefectReport]:
        """Analyze a business rule for boundary condition issues."""
        rule_lower = rule_text.lower()

        # Check for numeric comparisons
        numbers = [int(n) for n in rule_text.split() if n.isdigit()]
        if numbers:
            # Look for common boundary issues
            if 0 in numbers:
                return DefectReport(
                    title=f"零值边界问题: {rule_text[:50]}",
                    description=f"业务规则涉及 0 的处理，可能存在除零或计数问题",
                    severity=Severity.HIGH,
                    priority=Priority.P1,
                    related_requirement_id=req_id,
                    root_cause="零值边界处理",
                    evidence={
                        "source": "boundary_analysis",
                        "rule": rule_text,
                        "number": 0
                    }
                )

            if any(n > 10000 for n in numbers):
                return DefectReport(
                    title=f"大数值边界问题: {rule_text[:50]}",
                    description=f"业务规则涉及大数值 ({max(numbers)})，可能存在溢出风险",
                    severity=Severity.MEDIUM,
                    priority=Priority.P2,
                    related_requirement_id=req_id,
                    root_cause="大数值边界处理",
                    evidence={
                        "source": "boundary_analysis",
                        "rule": rule_text,
                        "large_number": max(n for n in numbers if n > 10000)
                    }
                )

        return None

    def get_defects(self) -> List[DefectReport]:
        """Get all generated defects."""
        return self.defects

    def get_defects_by_severity(self, severity: Severity) -> List[DefectReport]:
        """Get defects filtered by severity."""
        return [d for d in self.defects if d.severity == severity]

    def get_defects_by_priority(self, priority: Priority) -> List[DefectReport]:
        """Get defects filtered by priority."""
        return [d for d in self.defects if d.priority == priority]

    def export_to_dict(self) -> List[Dict[str, Any]]:
        """Export all defects as dictionaries."""
        return [d.to_dict() for d in self.defects]


# Singleton
_defect_generator: Optional[DefectGenerator] = None


def get_defect_generator() -> DefectGenerator:
    """Get singleton defect generator."""
    global _defect_generator
    if _defect_generator is None:
        _defect_generator = DefectGenerator()
    return _defect_generator