"""Match runs, therapy catalogue and cohort analytics."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import get_current_user, get_owned_patient
from ..models import Match, MatchRun, Patient, Therapy, User
from ..schemas import CohortStatsOut, MatchOut, MatchRunOut, TherapyOut
from ..services.matcher import cohort_stats, match_patient

router = APIRouter(prefix="/api", tags=["matching"])


def _run_to_out(run: MatchRun) -> MatchRunOut:
    matches = [
        MatchOut(
            therapy_id=m.therapy_id,
            therapy_name=m.therapy.name,
            modality=m.therapy.modality,
            status=m.status,
            tier=m.tier,
            score=round(m.score, 4),
            rationale=m.rationale,
            blockers=json.loads(m.blockers) if m.blockers else [],
            matched_variants=json.loads(m.matched_variants) if m.matched_variants else [],
        )
        for m in run.matches
    ]
    return MatchRunOut(
        id=run.id,
        patient_id=run.patient_id,
        created_at=run.created_at,
        variant_count=run.variant_count,
        candidate_count=run.candidate_count,
        actionable_count=run.actionable_count,
        matches=matches,
    )


@router.get("/therapies", response_model=list[TherapyOut])
def list_therapies(
    gene: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[TherapyOut]:
    stmt = select(Therapy).order_by(Therapy.biomarker_gene, Therapy.name)
    if gene:
        stmt = stmt.where(Therapy.biomarker_gene == gene.upper())
    return [TherapyOut.model_validate(t) for t in db.scalars(stmt).all()]


@router.post(
    "/patients/{patient_id}/match",
    response_model=MatchRunOut,
    status_code=status.HTTP_201_CREATED,
)
def run_match(
    patient: Patient = Depends(get_owned_patient), db: Session = Depends(get_db)
) -> MatchRunOut:
    therapies = list(db.scalars(select(Therapy)).all())
    if not therapies:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The therapy catalogue is empty. Seed it before matching.",
        )

    summary = match_patient(patient, therapies)

    run = MatchRun(
        patient_id=patient.id,
        variant_count=summary.variant_count,
        candidate_count=len(summary.results),
        actionable_count=summary.actionable_count,
    )
    db.add(run)
    db.flush()

    for result in summary.results:
        db.add(
            Match(
                run_id=run.id,
                therapy_id=result.therapy_id,
                status=result.status.value,
                tier=result.tier,
                score=result.score,
                rationale=result.rationale,
                blockers=json.dumps(result.blockers),
                matched_variants=json.dumps(result.matched_variants),
            )
        )

    db.commit()
    db.refresh(run)
    return _run_to_out(run)


@router.get("/patients/{patient_id}/matches", response_model=list[MatchRunOut])
def list_runs(
    patient: Patient = Depends(get_owned_patient), db: Session = Depends(get_db)
) -> list[MatchRunOut]:
    stmt = (
        select(MatchRun)
        .where(MatchRun.patient_id == patient.id)
        .options(selectinload(MatchRun.matches).selectinload(Match.therapy))
        .order_by(MatchRun.created_at.desc())
    )
    return [_run_to_out(r) for r in db.scalars(stmt).all()]


@router.get("/analytics/cohort", response_model=CohortStatsOut)
def analytics(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> CohortStatsOut:
    stmt = (
        select(Patient).where(Patient.owner_id == user.id).options(selectinload(Patient.variants))
    )
    patients = list(db.scalars(stmt).all())
    return CohortStatsOut(**cohort_stats(patients))
