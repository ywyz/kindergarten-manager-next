"""Teacher-facing same-class promotion read, submit and receipt routes."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .class_promotion_service import (
    get_promotion,
    query_promotion_operation,
    submit_promotion,
)
from .security import TeacherPrincipal

Grade = Literal["small", "middle", "large"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PromotionTermOut(_StrictModel):
    term_id: UUID
    name: str
    start_date: date
    end_date: date


class PromotionCurrentOut(_StrictModel):
    class_id: UUID
    class_name: str
    grade: Grade
    version: int
    terms: list[PromotionTermOut]


class PromotionSubmitIn(_StrictModel):
    request_id: UUID
    class_id: UUID
    expected_version: int = Field(..., ge=1, strict=True)
    target_grade: Grade
    effective_term_id: UUID


class PromotionReceiptOut(_StrictModel):
    request_id: UUID
    class_id: UUID
    class_name: str
    grade: Grade
    version: int
    effective_term_id: UUID
    replayed: bool


router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])


@router.get(
    "/me/class/promotion",
    response_model=PromotionCurrentOut,
)
def read_promotion(
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> PromotionCurrentOut:
    view = get_promotion(session, principal)
    return PromotionCurrentOut(
        class_id=view.class_id,
        class_name=view.class_name,
        grade=view.grade,
        version=view.version,
        terms=[
            PromotionTermOut(
                term_id=term.term_id,
                name=term.name,
                start_date=term.start_date,
                end_date=term.end_date,
            )
            for term in view.terms
        ],
    )


@router.post(
    "/me/class/promotion",
    response_model=PromotionReceiptOut,
)
def write_promotion(
    data: PromotionSubmitIn,
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> PromotionReceiptOut:
    receipt = submit_promotion(
        session,
        principal,
        request_id=data.request_id,
        class_id=data.class_id,
        expected_version=data.expected_version,
        target_grade=data.target_grade,
        effective_term_id=data.effective_term_id,
    )
    return PromotionReceiptOut(
        request_id=receipt.request_id,
        class_id=receipt.class_id,
        class_name=receipt.class_name,
        grade=receipt.grade,
        version=receipt.version,
        effective_term_id=receipt.effective_term_id,
        replayed=receipt.replayed,
    )


@router.get(
    "/me/class/promotion/operations/{request_id}",
    response_model=PromotionReceiptOut,
)
def read_promotion_operation(
    request_id: UUID,
    session: Session = Depends(get_session),
    principal: TeacherPrincipal = Depends(get_principal),
) -> PromotionReceiptOut:
    receipt = query_promotion_operation(session, principal, request_id)
    return PromotionReceiptOut(
        request_id=receipt.request_id,
        class_id=receipt.class_id,
        class_name=receipt.class_name,
        grade=receipt.grade,
        version=receipt.version,
        effective_term_id=receipt.effective_term_id,
        replayed=receipt.replayed,
    )
