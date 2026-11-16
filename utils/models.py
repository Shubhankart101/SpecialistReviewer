from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


EXPECTED_OUTPUT = "A typed decision, concise summary, and required corrections."


class Decision(str, Enum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specialist_id: str
    decision: Decision
    summary: str
    corrections: tuple[str, ...] = ()

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value

    @field_validator("corrections")
    @classmethod
    def validate_corrections(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("corrections must not be blank")
        return value

    @model_validator(mode="after")
    def validate_decision_contract(self):
        if self.decision is Decision.REQUEST_CHANGES and not self.corrections:
            raise ValueError("request_changes requires a correction")
        if self.decision is not Decision.REQUEST_CHANGES and self.corrections:
            raise ValueError("approve must not include corrections")
        return self


@dataclass(frozen=True)
class SpecialistConfig:
    id: str
    role: str
    goal: str
    private_context: dict[str, Any]


@dataclass(frozen=True)
class ReviewInput:
    release_id: str
    change_summary: str


@dataclass(frozen=True)
class Factories:
    agent_factory: Callable[..., Any]
    task_factory: Callable[..., Any]


@dataclass(frozen=True)
class ReviewFailure:
    specialist_id: str
    error: str
