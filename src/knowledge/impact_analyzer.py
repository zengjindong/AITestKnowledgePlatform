"""
Impact Analysis Module for requirement change analysis.

This module analyzes the impact of requirement changes on the codebase:
- Identifies affected modules, functions, and components
- Analyzes dependency chains
- Generates impact reports for QA and developers

PRD Reference: Core Value - "影响分析能力"
"""
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class ImpactLevel(str, Enum):
    """Impact severity levels."""
    CRITICAL = "critical"  # Core business logic, security
    HIGH = "high"          # Important features, API changes
    MEDIUM = "medium"      # UI changes, minor logic
    LOW = "low"            # Cosmetic, documentation


class ChangeType(str, Enum):
    """Types of code changes."""
    ADD = "add"            # New feature
    MODIFY = "modify"      # Change existing
    DELETE = "delete"      # Remove feature
    REFACTOR = "refactor"  # Code restructuring


@dataclass
class ImpactItem:
    """A single impact item."""
    file_path: str
    component_name: str
    change_type: ChangeType
    impact_level: ImpactLevel
    description: str
    affected_functions: List[str] = field(default_factory=list)
    related_entities: List[str] = field(default_factory=list)
    confidence: float = 1.0  # 0-1 confidence score


@dataclass
class ImpactReport:
    """Complete impact analysis report."""
    requirement_id: str
    requirement_title: str
    analyzed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    summary: Dict[str, Any] = field(default_factory=dict)
    impacted_items: List[ImpactItem] = field(default_factory=list)
    affected_api_count: int = 0
    affected_component_count: int = 0
    affected_service_count: int = 0
    database_changes: List[Dict[str, str]] = field(default_factory=list)
    risk_level: ImpactLevel = ImpactLevel.MEDIUM
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "requirement_title": self.requirement_title,
            "analyzed_at": self.analyzed_at,
            "summary": self.summary,
            "impacted_items": [
                {
                    "file_path": item.file_path,
                    "component_name": item.component_name,
                    "change_type": item.change_type.value,
                    "impact_level": item.impact_level.value,
                    "description": item.description,
                    "affected_functions": item.affected_functions,
                    "related_entities": item.related_entities,
                    "confidence": item.confidence
                }
                for item in self.impacted_items
            ],
            "affected_api_count": self.affected_api_count,
            "affected_component_count": self.affected_component_count,
            "affected_service_count": self.affected_service_count,
            "database_changes": self.database_changes,
            "risk_level": self.risk_level.value,
            "recommendations": self.recommendations
        }


class ImpactAnalyzer:
    """
    Analyze the impact of requirement changes on the codebase.

    Usage:
        analyzer = ImpactAnalyzer()
        report = analyzer.analyze_requirement({
            "title": "新增短信登录",
            "entities": ["user", "sms"]
        })
    """

    def __init__(
        self,
        fe_knowledge_base=None,
        be_knowledge_base=None,
        codebase_path: str = None
    ):
        self.codebase_path = codebase_path
        self.fe_kb = fe_knowledge_base
        self.be_kb = be_knowledge_base

    def analyze_requirement(
        self,
        requirement: Dict[str, Any],
        requirement_id: str = None
    ) -> ImpactReport:
        """
        Analyze requirement and generate impact report.

        Args:
            requirement: Parsed requirement from PM agent
            requirement_id: Optional requirement ID

        Returns:
            ImpactReport with all impacted components
        """
        req_id = requirement_id or requirement.get("requirement_id", "unknown")
        title = requirement.get("title", requirement.get("description", ""))
        entities = [e.get("name", "") for e in requirement.get("entities", [])]
        business_rules = requirement.get("business_rules", [])

        report = ImpactReport(
            requirement_id=req_id,
            requirement_title=title
        )

        # Search for affected components/APIs based on entities
        for entity in entities:
            if not entity:
                continue

            # Search FE knowledge base
            if self.fe_kb:
                fe_results = self.fe_kb.search_components(entity, limit=10)
                for result in fe_results:
                    component = result.get("component", {})
                    impact = self._create_impact_item(
                        file_path=component.get("file_path", ""),
                        component_name=component.get("name", ""),
                        change_type=ChangeType.MODIFY,
                        impact_level=self._assess_impact_level(component),
                        description=f"Component related to entity: {entity}",
                        related_entities=[entity]
                    )
                    report.impacted_items.append(impact)
                    report.affected_component_count += 1

            # Search BE knowledge base
            if self.be_kb:
                api_results = self.be_kb.search_apis(entity, limit=10)
                for result in api_results:
                    api = result.get("api", {})
                    impact = self._create_impact_item(
                        file_path=api.get("file_path", ""),
                        component_name=f"{api.get('method', 'GET')} {api.get('path', '')}",
                        change_type=ChangeType.MODIFY,
                        impact_level=ImpactLevel.HIGH,
                        description=f"API related to entity: {entity}",
                        related_entities=[entity]
                    )
                    report.impacted_items.append(impact)
                    report.affected_api_count += 1

                service_results = self.be_kb.search_services(entity, limit=10)
                for result in service_results:
                    service = result.get("service", {})
                    impact = self._create_impact_item(
                        file_path=service.get("file_path", ""),
                        component_name=service.get("name", ""),
                        change_type=ChangeType.MODIFY,
                        impact_level=ImpactLevel.HIGH,
                        description=f"Service related to entity: {entity}",
                        related_entities=[entity]
                    )
                    report.impacted_items.append(impact)
                    report.affected_service_count += 1

        # Analyze business rules for database impact
        for rule in business_rules:
            rule_text = rule.get("rule", rule.get("description", ""))
            db_changes = self._analyze_db_impact(rule_text)
            if db_changes:
                report.database_changes.extend(db_changes)

        # Deduplicate impacts
        report.impacted_items = self._deduplicate_impacts(report.impacted_items)

        # Calculate risk level
        report.risk_level = self._calculate_risk_level(report)

        # Generate summary
        report.summary = {
            "total_impacts": len(report.impacted_items),
            "component_impacts": report.affected_component_count,
            "api_impacts": report.affected_api_count,
            "service_impacts": report.affected_service_count,
            "database_impacts": len(report.database_changes),
            "risk_level": report.risk_level.value
        }

        # Generate recommendations
        report.recommendations = self._generate_recommendations(report)

        logger.info(f"Impact analysis complete: {report.summary}")
        return report

    def _create_impact_item(
        self,
        file_path: str,
        component_name: str,
        change_type: ChangeType,
        impact_level: ImpactLevel,
        description: str,
        related_entities: List[str] = None
    ) -> ImpactItem:
        """Create an impact item."""
        return ImpactItem(
            file_path=file_path,
            component_name=component_name,
            change_type=change_type,
            impact_level=impact_level,
            description=description,
            affected_functions=self._find_affected_functions(file_path),
            related_entities=related_entities or []
        )

    def _assess_impact_level(self, component: Dict) -> ImpactLevel:
        """Assess impact level based on component type."""
        file_path = component.get("file_path", "").lower()
        component_type = component.get("type", "").lower()

        # Core components have higher impact
        if any(kw in file_path for kw in ['core', 'auth', 'payment', 'order']):
            return ImpactLevel.CRITICAL
        if any(kw in file_path for kw in ['api', 'service', 'model']):
            return ImpactLevel.HIGH
        if component_type in ['vue', 'jsx', 'tsx']:
            return ImpactLevel.MEDIUM
        return ImpactLevel.LOW

    def _analyze_db_impact(self, rule_text: str) -> List[Dict[str, str]]:
        """Analyze potential database impact from business rule."""
        changes = []

        rule_lower = rule_text.lower()

        # Detect field additions
        if any(kw in rule_lower for kw in ['新增', 'add', '新增字段', 'add column', 'add field']):
            changes.append({
                "type": "add_column",
                "description": f"可能需要添加新字段: {rule_text[:50]}"
            })

        # Detect field modifications
        if any(kw in rule_lower for kw in ['修改', 'change', 'modify', 'update']):
            changes.append({
                "type": "modify_column",
                "description": f"可能需要修改字段: {rule_text[:50]}"
            })

        # Detect index changes
        if any(kw in rule_lower for kw in ['索引', 'index', '查询优化']):
            changes.append({
                "type": "add_index",
                "description": f"可能需要添加索引: {rule_text[:50]}"
            })

        return changes

    def _find_affected_functions(self, file_path: str) -> List[str]:
        """Find affected functions in a file."""
        if not file_path or not Path(file_path).exists():
            return []

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Extract function definitions
            functions = []

            # Python
            functions.extend(re.findall(r'def\s+(\w+)\s*\(', content))

            # JavaScript/TypeScript
            functions.extend(re.findall(r'function\s+(\w+)\s*\(', content))
            functions.extend(re.findall(r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\w*\s*\(', content))

            # Java
            functions.extend(re.findall(r'public\s+\w+\s+(\w+)\s*\(', content))
            functions.extend(re.findall(r'private\s+\w+\s+(\w+)\s*\(', content))

            return list(set(functions))[:20]  # Limit results

        except Exception as e:
            logger.debug(f"Error finding functions in {file_path}: {e}")
            return []

    def _deduplicate_impacts(self, impacts: List[ImpactItem]) -> List[ImpactItem]:
        """Remove duplicate impact items."""
        seen = {}
        unique = []

        for impact in impacts:
            key = impact.file_path
            if key not in seen:
                seen[key] = True
                unique.append(impact)
            else:
                # Merge related entities
                existing = next(i for i in unique if i.file_path == key)
                for entity in impact.related_entities:
                    if entity not in existing.related_entities:
                        existing.related_entities.append(entity)

        return unique

    def _calculate_risk_level(self, report: ImpactReport) -> ImpactLevel:
        """Calculate overall risk level."""
        critical_count = sum(
            1 for item in report.impacted_items
            if item.impact_level == ImpactLevel.CRITICAL
        )
        high_count = sum(
            1 for item in report.impacted_items
            if item.impact_level == ImpactLevel.HIGH
        )

        if critical_count > 0 or high_count > 5:
            return ImpactLevel.CRITICAL
        elif high_count > 2:
            return ImpactLevel.HIGH
        elif report.database_changes:
            return ImpactLevel.MEDIUM
        return ImpactLevel.LOW

    def _generate_recommendations(self, report: ImpactReport) -> List[str]:
        """Generate recommendations based on impact analysis."""
        recommendations = []

        if report.affected_api_count > 0:
            recommendations.append(f"需要测试 {report.affected_api_count} 个 API 端点")

        if report.affected_component_count > 0:
            recommendations.append(f"需要回归测试 {report.affected_component_count} 个前端组件")

        if report.database_changes:
            recommendations.append("需要关注数据库变更，建议进行 DDL 测试")

        if report.risk_level in [ImpactLevel.CRITICAL, ImpactLevel.HIGH]:
            recommendations.append("建议进行全面的回归测试")
            recommendations.append("建议安排 code review")

        if report.affected_service_count > 0:
            recommendations.append(f"需要测试 {report.affected_service_count} 个后端服务")

        return recommendations


# Singleton
_analyzer: Optional[ImpactAnalyzer] = None


def get_impact_analyzer() -> ImpactAnalyzer:
    """Get singleton impact analyzer."""
    global _analyzer
    if _analyzer is None:
        _analyzer = ImpactAnalyzer()
    return _analyzer