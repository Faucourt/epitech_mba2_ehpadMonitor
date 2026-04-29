from typing import Any, Literal

from pydantic import BaseModel, Field


class LLMReport(BaseModel):
    resume: str
    points_vigilance: list[str]
    actions_soignants: list[str]
    niveau_risque: Literal["faible", "modere", "eleve"]
    sources_kb: list[str] = Field(default_factory=list)

    synthese_clinique: str | None = None
    prediction_30_60min: dict[str, Any] = Field(default_factory=dict)
    preuves: list[dict[str, Any]] = Field(default_factory=list)
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    actions_prioritaires: list[dict[str, Any]] = Field(default_factory=list)
    plan_surveillance: list[dict[str, Any]] = Field(default_factory=list)
    complications_possibles: list[dict[str, Any]] = Field(default_factory=list)
    donnees_a_verifier: list[str] = Field(default_factory=list)
    conduite_a_tenir_kb: list[dict[str, Any]] = Field(default_factory=list)
    signaux_rassurants: list[str] = Field(default_factory=list)
    incertitudes: list[str] = Field(default_factory=list)
    message_famille: str | None = None
    rapport_medical: dict[str, Any] = Field(default_factory=dict)
    llm_trace: dict[str, Any] = Field(default_factory=dict)
