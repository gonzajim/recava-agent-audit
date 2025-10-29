"""Pydantic schemas for advisor API."""

from typing import Any, Dict, List

from pydantic import BaseModel


class AdvisorRequest(BaseModel):
    question: str


class Citation(BaseModel):
    title: str = ""
    source: str = ""
    url: str = ""
    quote: str = ""
    date: str = ""
    section: str = ""


class AdvisorResponse(BaseModel):
    status: str
    answer: str
    citations: List[Citation] = []
    meta: Dict[str, Any] = {}

