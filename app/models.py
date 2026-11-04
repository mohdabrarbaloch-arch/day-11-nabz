"""ORM models for the Nabz precision-oncology workspace.

The schema separates three things that are usually conflated:

* what the patient *is* (clinical profile),
* what the tumour *has* (molecular variants),
* what could be *done* (therapies and their biomarker requirements).

A match is a derived, stored artefact — never a column on the patient — so a
re-run can be compared against the previous one.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="clinician")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    patients: Mapped[list[Patient]] = relationship(back_populates="owner")


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mrn: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    age: Mapped[int] = mapped_column(Integer)
    sex: Mapped[str] = mapped_column(String(10))
    diagnosis: Mapped[str] = mapped_column(String(160))
    stage: Mapped[str] = mapped_column(String(20))
    ecog: Mapped[int] = mapped_column(Integer, default=0)
    prior_lines: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User] = relationship(back_populates="patients")
    variants: Mapped[list[Variant]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    runs: Mapped[list[MatchRun]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_patients_owner_diagnosis", "owner_id", "diagnosis"),)


class Variant(Base):
    """A single molecular finding from a report."""

    __tablename__ = "variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    gene: Mapped[str] = mapped_column(String(20), index=True)
    protein_change: Mapped[str] = mapped_column(String(80))
    coding_change: Mapped[str | None] = mapped_column(String(80), nullable=True)
    variant_type: Mapped[str] = mapped_column(String(20), default="snv")
    vaf: Mapped[float] = mapped_column(Float, default=0.0)
    read_depth: Mapped[int] = mapped_column(Integer, default=0)
    classification: Mapped[str] = mapped_column(String(30), default="vus")
    report_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    patient: Mapped[Patient] = relationship(back_populates="variants")

    __table_args__ = (UniqueConstraint("patient_id", "gene", "protein_change", name="uq_variant"),)


class Therapy(Base):
    """A candidate therapy and the biomarker it requires."""

    __tablename__ = "therapies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    modality: Mapped[str] = mapped_column(String(30))
    biomarker_gene: Mapped[str] = mapped_column(String(20), index=True)
    requirement: Mapped[str] = mapped_column(String(160))
    #: When set, the variant's protein change must match this exactly (after
    #: normalisation). NULL means "any pathogenic variant in the gene".
    #: Without this, a KRAS G12D tumour would match a G12C-only drug.
    required_protein_change: Mapped[str | None] = mapped_column(String(40), nullable=True)
    indication: Mapped[str] = mapped_column(String(160))
    evidence_level: Mapped[str] = mapped_column(String(2), default="C")
    approval_status: Mapped[str] = mapped_column(String(30), default="off-label")
    line_of_therapy: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class MatchRun(Base):
    """One execution of the matcher against a patient's current profile."""

    __tablename__ = "match_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    variant_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    actionable_count: Mapped[int] = mapped_column(Integer, default=0)

    patient: Mapped[Patient] = relationship(back_populates="runs")
    matches: Mapped[list[Match]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Match(Base):
    """A single therapy considered in a run, with its verdict and reasons."""

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("match_runs.id", ondelete="CASCADE"), index=True)
    therapy_id: Mapped[int] = mapped_column(ForeignKey("therapies.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20))
    tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    blockers: Mapped[str] = mapped_column(Text, default="[]")
    matched_variants: Mapped[str] = mapped_column(Text, default="[]")

    run: Mapped[MatchRun] = relationship(back_populates="matches")
    therapy: Mapped[Therapy] = relationship()
