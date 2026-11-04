"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Sex = Literal["female", "male", "other", "unknown"]
Stage = Literal["I", "II", "III", "IV", "unknown"]
Classification = Literal["pathogenic", "likely_pathogenic", "vus", "likely_benign", "benign"]
VariantType = Literal["snv", "indel", "cnv", "fusion", "msi", "other"]


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        if value.lower() in {"password12", "1234567890", "qwertyuiop"}:
            raise ValueError("That password is too common.")
        if not any(c.isdigit() for c in value):
            raise ValueError("Password must contain at least one digit.")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class PatientCreate(BaseModel):
    mrn: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9\-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    age: int = Field(ge=0, le=120)
    sex: Sex
    diagnosis: str = Field(min_length=2, max_length=160)
    stage: Stage = "unknown"
    ecog: int = Field(default=0, ge=0, le=5)
    prior_lines: int = Field(default=0, ge=0, le=20)
    notes: str | None = Field(default=None, max_length=4000)


class PatientUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    age: int | None = Field(default=None, ge=0, le=120)
    sex: Sex | None = None
    diagnosis: str | None = Field(default=None, min_length=2, max_length=160)
    stage: Stage | None = None
    ecog: int | None = Field(default=None, ge=0, le=5)
    prior_lines: int | None = Field(default=None, ge=0, le=20)
    notes: str | None = Field(default=None, max_length=4000)


class VariantCreate(BaseModel):
    gene: str = Field(min_length=1, max_length=20)
    protein_change: str = Field(min_length=1, max_length=80)
    coding_change: str | None = Field(default=None, max_length=80)
    variant_type: VariantType = "snv"
    vaf: float = Field(ge=0.0, le=1.0)
    read_depth: int = Field(default=0, ge=0)
    classification: Classification = "vus"

    @field_validator("gene")
    @classmethod
    def _upper_gene(cls, value: str) -> str:
        return value.strip().upper()


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gene: str
    protein_change: str
    coding_change: str | None
    variant_type: str
    vaf: float
    read_depth: int
    classification: str
    report_date: datetime


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mrn: str
    display_name: str
    age: int
    sex: str
    diagnosis: str
    stage: str
    ecog: int
    prior_lines: int
    notes: str | None
    created_at: datetime
    variants: list[VariantOut] = []


class TherapyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    modality: str
    biomarker_gene: str
    requirement: str
    indication: str
    evidence_level: str
    approval_status: str
    line_of_therapy: int
    notes: str | None


class MatchOut(BaseModel):
    therapy_id: int
    therapy_name: str
    modality: str
    status: str
    tier: int | None
    score: float
    rationale: str
    blockers: list[str]
    matched_variants: list[str]


class MatchRunOut(BaseModel):
    id: int
    patient_id: int
    created_at: datetime
    variant_count: int
    candidate_count: int
    actionable_count: int
    matches: list[MatchOut]


class CohortStatsOut(BaseModel):
    patient_count: int
    patients_with_actionable_variant: int
    actionable_rate: float
    genes_tested: list[str]
    actionable_variant_counts: dict[str, int]
    by_diagnosis: dict[str, int]
    by_stage: dict[str, int]
