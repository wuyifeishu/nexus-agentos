"""
AgentOS v0.30 Agent技能市场 — 可复用的Agent技能模板。
预置24个专业Agent技能。
"""

from dataclasses import dataclass, field
from enum import StrEnum


class AgentCategory(StrEnum):
    """Agent 分类。"""

    CODE = "code"
    DATA = "data"
    SECURITY = "security"
    WRITING = "writing"
    ANALYSIS = "analysis"
    AUTOMATION = "automation"
    CREATIVE = "creative"
    DEVOPS = "devops"


@dataclass
class AgentSkill:
    """Agent 技能定义。"""

    name: str
    category: AgentCategory
    description: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    model_preference: str = "auto"
    tags: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    author: str = "AgentOS"


class AgentMarket:
    """v0.30 Agent技能市场 — 24个预置技能。"""

    def __init__(self):
        self._skills: dict[str, AgentSkill] = {}
        self._register_defaults()

    def _register_defaults(self):
        skills = [
            # CODE (6)
            AgentSkill(
                "code-reviewer",
                AgentCategory.CODE,
                "代码审查，发现bug/安全漏洞/风格问题",
                "你是一个资深代码审查员。审查代码的：1)逻辑错误 2)安全漏洞 3)性能问题 4)代码风格。输出结构化报告。",
                ["read_text", "write_file", "shell_executor"],
                "kimi-k2.6",
                ["code", "review", "quality"],
            ),
            AgentSkill(
                "architect",
                AgentCategory.CODE,
                "软件架构设计，系统拆分、技术选型",
                "你是一个软件架构师。设计可扩展、高性能的系统架构。输出架构图(ASCII)+关键决策+技术栈推荐。",
                ["read_text", "web_search"],
                "deepseek-r1",
                ["architecture", "design", "system"],
            ),
            AgentSkill(
                "refactor-expert",
                AgentCategory.CODE,
                "代码重构，提升可读性和性能",
                "你是一个重构专家。重构代码：1)提取方法 2)消除重复 3)优化数据结构 4)保持向后兼容。",
                ["read_text", "write_file", "edit_file", "shell_executor"],
                "kimi-k2.6",
                ["refactor", "clean-code"],
            ),
            AgentSkill(
                "test-generator",
                AgentCategory.CODE,
                "自动生成单元测试/集成测试",
                "你是一个测试工程师。为给定代码生成全面的测试用例：1)边界条件 2)异常路径 3)Mock外部依赖。",
                ["read_text", "write_file", "shell_executor"],
                "deepseek-v3.1",
                ["testing", "pytest"],
            ),
            AgentSkill(
                "debug-helper",
                AgentCategory.CODE,
                "调试助手，分析错误日志定位根因",
                "你是一个调试专家。分析错误栈/日志，定位根因，给出修复方案。",
                ["read_text", "shell_executor"],
                "deepseek-r1",
                ["debug", "troubleshoot"],
            ),
            AgentSkill(
                "doc-generator",
                AgentCategory.CODE,
                "API文档/README自动生成",
                "你是一个文档工程师。从代码生成清晰的API文档、README、使用示例。",
                ["read_text", "write_file"],
                "deepseek-v3.1",
                ["docs", "api"],
            ),
            # DATA (4)
            AgentSkill(
                "data-analyst",
                AgentCategory.DATA,
                "数据分析，统计/可视化/洞察",
                "你是一个数据分析师。分析数据：1)描述性统计 2)趋势发现 3)异常检测 4)可视化建议。",
                ["python_executor", "read_text", "write_file"],
                "deepseek-r1",
                ["data", "analytics"],
            ),
            AgentSkill(
                "sql-master",
                AgentCategory.DATA,
                "SQL查询优化/数据库设计",
                "你是一个数据库专家。编写高效SQL、设计表结构、优化查询性能。",
                ["python_executor", "read_text"],
                "deepseek-v3.1",
                ["sql", "database"],
            ),
            AgentSkill(
                "etl-engineer",
                AgentCategory.DATA,
                "数据清洗/ETL管道构建",
                "你是一个数据工程师。构建可靠的数据管道：抽取-转换-加载。处理脏数据、格式转换。",
                ["python_executor", "read_text", "write_file", "shell_executor"],
                "kimi-k2.6",
                ["etl", "pipeline"],
            ),
            AgentSkill(
                "ml-consultant",
                AgentCategory.DATA,
                "机器学习方案咨询，特征工程建议",
                "你是一个ML顾问。推荐合适的模型、特征工程策略、评估指标。",
                ["web_search", "python_executor"],
                "deepseek-r1",
                ["ml", "ai"],
            ),
            # SECURITY (3)
            AgentSkill(
                "security-auditor",
                AgentCategory.SECURITY,
                "安全审计，OWASP Top 10检查",
                "你是一个安全审计员。检查：1)注入攻击 2)认证缺陷 3)敏感数据暴露 4)XXE 5)访问控制。",
                ["read_text", "shell_executor"],
                "deepseek-r1",
                ["security", "audit"],
            ),
            AgentSkill(
                "pentest-advisor",
                AgentCategory.SECURITY,
                "渗透测试建议，漏洞利用分析",
                "你是一个渗透测试顾问。分析系统弱点，提供测试向量。仅用于授权测试。",
                ["shell_executor", "web_search"],
                "deepseek-r1",
                ["pentest", "vulnerability"],
            ),
            AgentSkill(
                "crypto-reviewer",
                AgentCategory.SECURITY,
                "密码学实现审查",
                "你是一个密码学专家。审查加密实现：算法选择、密钥管理、随机数生成。",
                ["read_text"],
                "deepseek-r1",
                ["crypto", "encryption"],
            ),
            # WRITING (3)
            AgentSkill(
                "technical-writer",
                AgentCategory.WRITING,
                "技术文章/博客/白皮书撰写",
                "你是一个技术写作专家。撰写清晰、准确的技术文档：白皮书、技术博客、教程。",
                ["web_search", "write_file"],
                "kimi-k2.6",
                ["writing", "blog"],
            ),
            AgentSkill(
                "spec-writer",
                AgentCategory.WRITING,
                "PRD/技术规格文档撰写",
                "你是一个产品规格撰写人。输出结构化PRD：背景、目标、用户故事、验收标准、非功能需求。",
                ["web_search", "write_file"],
                "deepseek-v3.1",
                ["prd", "specification"],
            ),
            AgentSkill(
                "translator-pro",
                AgentCategory.WRITING,
                "专业文档翻译（中英互译+技术术语准确）",
                "你是一个专业翻译。翻译技术文档，保持术语一致性，保留代码片段和格式。",
                ["read_text", "write_file"],
                "deepseek-v3.1",
                ["translate", "i18n"],
            ),
            # ANALYSIS (3)
            AgentSkill(
                "competitor-analyst",
                AgentCategory.ANALYSIS,
                "竞品分析，SWOT/五力模型",
                "你是一个竞品分析师。输出SWOT分析、功能对比矩阵、市场定位分析。",
                ["web_search", "write_file"],
                "deepseek-r1",
                ["competitive", "market"],
            ),
            AgentSkill(
                "decision-analyst",
                AgentCategory.ANALYSIS,
                "决策分析，多维度权衡/决策矩阵",
                "你是一个决策分析师。构建决策矩阵：列出选项、加权维度、敏感性分析。",
                ["write_file"],
                "deepseek-r1",
                ["decision", "tradeoff"],
            ),
            AgentSkill(
                "trend-watcher",
                AgentCategory.ANALYSIS,
                "技术趋势追踪，科技前沿洞察",
                "你是一个趋势分析师。追踪技术趋势：1)论文解读 2)开源项目热度 3)行业动态。",
                ["web_search", "web_fetch", "write_file"],
                "kimi-k2.6",
                ["trends", "research"],
            ),
            # AUTOMATION (2)
            AgentSkill(
                "workflow-designer",
                AgentCategory.AUTOMATION,
                "工作流自动化方案设计",
                "你是一个自动化专家。设计端到端工作流：触发器→步骤→错误处理→通知。",
                ["write_file"],
                "kimi-k2.6",
                ["workflow", "automation"],
            ),
            AgentSkill(
                "script-writer",
                AgentCategory.AUTOMATION,
                "Shell/Python运维脚本编写",
                "你是一个脚本专家。编写健壮的自动化脚本：错误处理、日志、幂等性。",
                ["shell_executor", "python_executor", "write_file"],
                "kimi-k2.6",
                ["script", "ops"],
            ),
            # CREATIVE (2)
            AgentSkill(
                "canvas-designer",
                AgentCategory.CREATIVE,
                "视觉设计/海报/Logo生成",
                "调用canvas-design skill进行视觉创作。",
                ["use_skill", "write_file"],
                "deepseek-v3.1",
                ["design", "visual"],
            ),
            AgentSkill(
                "frontend-builder",
                AgentCategory.CREATIVE,
                "前端界面/Web页面构建",
                "调用frontend-design skill构建生产级界面。",
                ["use_skill", "write_file"],
                "kimi-k2.6",
                ["frontend", "ui"],
            ),
            # DEVOPS (1)
            AgentSkill(
                "devops-architect",
                AgentCategory.DEVOPS,
                "CI/CD/容器化/监控方案",
                "你是一个DevOps架构师。设计：1)CI/CD Pipeline 2)容器编排 3)监控告警 4)日志聚合。",
                ["shell_executor", "write_file", "web_search"],
                "kimi-k2.6",
                ["devops", "cloud"],
            ),
        ]
        for s in skills:
            self._skills[s.name] = s

    @property
    def skills(self) -> dict[str, AgentSkill]:
        return dict(self._skills)

    def get(self, name: str) -> AgentSkill | None:
        return self._skills.get(name)

    def list_by_category(self, category: AgentCategory) -> list[AgentSkill]:
        return [s for s in self._skills.values() if s.category == category]

    def search(self, query: str) -> list[AgentSkill]:
        q = query.lower()
        results = []
        for s in self._skills.values():
            score = 0
            if q in s.name.lower():
                score += 3
            if q in s.description.lower():
                score += 2
            if any(q in t.lower() for t in s.tags):
                score += 2
            if q in s.category.value:
                score += 1
            if score > 0:
                results.append((s, score))
        results.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in results]

    def register(self, skill: AgentSkill):
        self._skills[skill.name] = skill

    def stats(self) -> dict:
        cats = {}
        for s in self._skills.values():
            cats[s.category.value] = cats.get(s.category.value, 0) + 1
        return {"total": len(self._skills), "by_category": cats}
