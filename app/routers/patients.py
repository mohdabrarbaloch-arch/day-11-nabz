"""Patient CRUD and molecular findings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import get_current_user, get_owned_patient
from ..models import Patient, User, Variant
from ..schemas import (
    PatientCreate,
    PatientOut,
    PatientUpdate,
    VariantCreate,
    VariantOut,
)

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.get("", response_model=list[PatientOut])
def list_patients(
    diagnosis: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PatientOut]:
    stmt = (
        select(Patient)
        .where(Patient.owner_id == user.id)
        .options(selectinload(Patient.variants))
        .order_by(Patient.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if diagnosis:
        stmt = stmt.where(Patient.diagnosis.ilike(f"%{diagnosis}%"))
    return [PatientOut.model_validate(p) for p in db.scalars(stmt).all()]


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PatientOut:
    patient = Patient(owner_id=user.id, **payload.model_dump())
    db.add(patient)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"MRN {payload.mrn!r} is already in use.",
        ) from None
    db.refresh(patient)
    return PatientOut.model_validate(patient)


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient: Patient = Depends(get_owned_patient)) -> PatientOut:
    return PatientOut.model_validate(patient)


@router.patch("/{patient_id}", response_model=PatientOut)
def update_patient(
    payload: PatientUpdate,
    patient: Patient = Depends(get_owned_patient),
    db: Session = Depends(get_db),
) -> PatientOut:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(patient, key, value)
    db.commit()
    db.refresh(patient)
    return PatientOut.model_validate(patient)


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_patient(
    patient: Patient = Depends(get_owned_patient), db: Session = Depends(get_db)
) -> Response:
    db.delete(patient)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{patient_id}/variants",
    response_model=VariantOut,
    status_code=status.HTTP_201_CREATED,
)
def add_variant(
    payload: VariantCreate,
    patient: Patient = Depends(get_owned_patient),
    db: Session = Depends(get_db),
) -> VariantOut:
    variant = Variant(patient_id=patient.id, **payload.model_dump())
    db.add(variant)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{payload.gene} {payload.protein_change} is already recorded for " f"this patient."
            ),
        ) from None
    db.refresh(variant)
    return VariantOut.model_validate(variant)


@router.get("/{patient_id}/variants", response_model=list[VariantOut])
def list_variants(
    patient: Patient = Depends(get_owned_patient), db: Session = Depends(get_db)
) -> list[VariantOut]:
    stmt = select(Variant).where(Variant.patient_id == patient.id).order_by(Variant.vaf.desc())
    return [VariantOut.model_validate(v) for v in db.scalars(stmt).all()]


@router.delete(
    "/{patient_id}/variants/{variant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_variant(
    variant_id: int,
    patient: Patient = Depends(get_owned_patient),
    db: Session = Depends(get_db),
) -> Response:
    variant = db.scalar(
        select(Variant).where(Variant.id == variant_id, Variant.patient_id == patient.id)
    )
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found.")
    db.delete(variant)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
