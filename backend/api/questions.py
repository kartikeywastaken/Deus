"""Targeted ambiguity-question endpoints."""

from __future__ import annotations

from enum import Enum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.db.repositories import PostgresInvestigationRepository
from backend.investigation.orchestrator import SearchOrchestrator

from .dependencies import get_orchestrator, get_repository
from .schemas import (
    QuestionAnswerCreate,
    QuestionEnvelope,
    QuestionOption,
    QuestionRead,
    SearchRead,
)

router = APIRouter(prefix="/api/searches", tags=["questions"])


@router.get("/{search_id}/question", response_model=QuestionEnvelope)
async def get_question(
    search_id: UUID,
    repository: Annotated[PostgresInvestigationRepository, Depends(get_repository)],
) -> QuestionEnvelope:
    if await repository.get_search(search_id) is None:
        raise HTTPException(status_code=404, detail="search not found")
    question = await repository.get_pending_question(search_id)
    return QuestionEnvelope(item=_question_read(question) if question else None)


@router.post("/{search_id}/question-answer", response_model=SearchRead)
async def answer_question(
    search_id: UUID,
    payload: QuestionAnswerCreate,
    orchestrator: Annotated[SearchOrchestrator, Depends(get_orchestrator)],
) -> SearchRead:
    try:
        search = await orchestrator.answer_question(
            search_id,
            payload.question_id,
            payload.value,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SearchRead.model_validate(search)


def _question_read(question: object) -> QuestionRead:
    return QuestionRead(
        id=question.id,
        question_type=_enum_value(question.question_type),
        question_text=question.question_text,
        options=[QuestionOption.model_validate(item) for item in question.options],
        reason=question.reason,
        expected_information_gain=question.expected_information_gain,
        sensitivity_level=_enum_value(question.sensitivity_level),
        status=_enum_value(question.status),
        context=getattr(question, "context", {}) or {},
    )


def _enum_value(value: object) -> str:
    return str(value.value) if isinstance(value, Enum) else str(value)
