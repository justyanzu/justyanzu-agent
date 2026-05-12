"""
Planner 输出 JSON 的 Pydantic 校验（与 prompts 中 plan 结构一致，可扩展）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_ALLOWED_AGENTS = frozenset({"coder", "file", "casual", "memory"})


class PlanStep(BaseModel):
    """单步计划。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    agent: str
    id: str
    task: str
    need: list[str] = Field(default_factory=list)

    @field_validator("need", mode="before")
    @classmethod
    def normalize_need(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v]
        raise ValueError("need 必须为 JSON 数组或 null")

    @field_validator("agent")
    @classmethod
    def agent_must_be_known(cls, v: str) -> str:
        s = v.strip()
        if s.lower() not in _ALLOWED_AGENTS:
            raise ValueError(f"agent 必须是 {_ALLOWED_AGENTS} 之一（大小写不敏感）")
        return s


class PlanDocument(BaseModel):
    """
    Planner 应输出的 JSON 根对象。
    reasoning 可选：用于替代正文里的「规划前分析」，便于仍只输出一整段 JSON。
    """

    model_config = ConfigDict(extra="ignore")

    reasoning: str | None = None
    plan: list[PlanStep] = Field(min_length=1)


def plan_document_to_agent_dicts(doc: PlanDocument) -> list[dict]:
    """转为 planner_agent.process 使用的 task 字典列表。"""
    out: list[dict] = []
    for step in doc.plan:
        out.append(
            {
                "agent": step.agent,
                "id": step.id,
                "task": step.task,
                "need": list(step.need),
            }
        )
    return out


__all__ = [
    "PlanDocument",
    "PlanStep",
    "ValidationError",
    "plan_document_to_agent_dicts",
]
