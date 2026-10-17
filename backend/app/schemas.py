from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EvidenceValue(BaseModel):
    value: str | None = None
    evidence_text: str | None = None
    source_field: str | None = None
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ComplaintExtraction(BaseModel):
    subject: EvidenceValue
    action: EvidenceValue
    target_object: EvidenceValue
    topic: EvidenceValue
    primary_category: EvidenceValue
    secondary_category: EvidenceValue
    location: EvidenceValue
    location_type: Literal["事件发生地", "诉求目标地点", "参照地点", "无法判断"]
    review_reasons: list[str] = Field(default_factory=list)


class CategoryDefinition(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    parent_code: str | None = None
    aliases: list[str] = Field(default_factory=list)


class FieldDefinition(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    value_type: Literal["text", "enum", "entity", "integer", "date", "boolean", "location"]
    description: str = Field(default="", max_length=1000)
    multiple: bool = False
    required: bool = False
    enum_values: list[str] = Field(default_factory=list)
    entity_type: str | None = None
    evidence_required: bool = True
    applies_when: list[str] = Field(default_factory=list)


class RuleDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    condition: str = Field(default="", max_length=1000)
    action: str = Field(default="", max_length=1000)
    severity: Literal["info", "review", "block"] = "review"


class ConfigDefinition(BaseModel):
    title: str = Field(default="新建治理配置", max_length=120)
    summary: str = Field(default="", max_length=2000)
    categories: list[CategoryDefinition] = Field(default_factory=list)
    fields: list[FieldDefinition] = Field(default_factory=list)
    rules: list[RuleDefinition] = Field(default_factory=list)


class AssistantTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    draft_id: str | None = None


class DraftTitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class AssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime | None = None


class DraftResponse(BaseModel):
    id: str
    title: str
    status: Literal["draft", "validated", "published"]
    config: ConfigDefinition
    messages: list[AssistantMessage] = Field(default_factory=list)
    validation: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AssistantTurnResponse(BaseModel):
    draft: DraftResponse
    assistant_message: str
    needs_clarification: bool = False
    questions: list[str] = Field(default_factory=list)


class ValidationResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checks: list[dict[str, str]] = Field(default_factory=list)


class PublishRequest(BaseModel):
    publisher: str = Field(min_length=1, max_length=100)


class DataSourceInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["database", "model", "map"]
    provider: str = Field(min_length=1, max_length=40)
    config: dict = Field(default_factory=dict)
    secrets: dict = Field(default_factory=dict)
    is_default: bool = False
    enabled: bool = True


class DataSourceTestRequest(DataSourceInput):
    source_id: str | None = None
    query: str | None = Field(default=None, max_length=5000)
    prompt: str | None = Field(default=None, max_length=500)
