"""The biomarker → therapy matching engine.

This is a deterministic rules engine over a curated knowledge base. It is
*not* a clinical decision support tool and it does not predict response. What
it does is take a patient's structured molecular findings and answer one
narrow question honestly:

    Given these variants, which therapies in the catalogue have their
    biomarker requirement satisfied, and which do not — and why?

Every verdict carries its reasons. A therapy is never silently dropped: it
comes back as `eligible`, `blocked` or `not_applicable`, each with a
human-readable rationale, so a clinician can disagree with the engine on the
evidence rather than having to guess what it did.

Tiering
-------
Tier 1  biomarker satisfied, evidence level A, on-label, patient fits the
        line-of-therapy window.
Tier 2  biomarker satisfied, evidence A or B, but off-label or beyond the
        labelled line.
Tier 3  biomarker satisfied but evidence level C/D — worth a tumour board
        discussion, not a default.
Blocked biomarker absent, or a clinical exclusion applies (ECOG, prior lines).

Scoring is deliberately simple and monotonic: it orders within a tier, it does
not pretend to be a probability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..models import Patient, Therapy, Variant


class Status(str, Enum):
    ELIGIBLE = "eligible"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


#: Variant classifications that count as a real, reportable finding.
ACTIONABLE_CLASSIFICATIONS = {"pathogenic", "likely_pathogenic"}

#: Variant types that carry no meaningful allele fraction. An MSI-high status
#: or a gene fusion is present or absent; applying a VAF floor to them would
#: silently discard the most actionable findings in the panel.
VAF_EXEMPT_TYPES = {"msi", "fusion", "cnv"}

#: Anything below this VAF is treated as a subclonal / artefact-level call and
#: is reported but not used to justify a therapy on its own.
MIN_VAF_FOR_MATCH = 0.05

#: ECOG 0-2 is generally therapy-eligible; 3+ is not.
MAX_ECOG = 2

EVIDENCE_WEIGHT = {"A": 1.0, "B": 0.75, "C": 0.5, "D": 0.25}


@dataclass
class MatchResult:
    """One therapy's verdict for one patient."""

    therapy_id: int
    therapy_name: str
    modality: str
    status: Status
    tier: int | None
    score: float
    rationale: str
    blockers: list[str] = field(default_factory=list)
    matched_variants: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "therapy_id": self.therapy_id,
            "therapy_name": self.therapy_name,
            "modality": self.modality,
            "status": self.status.value,
            "tier": self.tier,
            "score": round(self.score, 4),
            "rationale": self.rationale,
            "blockers": self.blockers,
            "matched_variants": self.matched_variants,
        }


@dataclass
class MatchSummary:
    results: list[MatchResult]
    variant_count: int

    @property
    def eligible(self) -> list[MatchResult]:
        return [r for r in self.results if r.status is Status.ELIGIBLE]

    @property
    def actionable_count(self) -> int:
        return len(self.eligible)

    def ranked(self) -> list[MatchResult]:
        """Eligible first, then by tier, then by score, then by name."""
        return sorted(
            self.results,
            key=lambda r: (
                0 if r.status is Status.ELIGIBLE else 1,
                r.tier if r.tier is not None else 99,
                -r.score,
                r.therapy_name,
            ),
        )


def _normalise_protein(change: str) -> str:
    """'p.G12C' and 'G12C' are the same finding."""
    text = change.strip()
    if text.lower().startswith("p."):
        text = text[2:]
    return text.upper()


def _is_actionable(variant: Variant) -> bool:
    if variant.classification not in ACTIONABLE_CLASSIFICATIONS:
        return False
    if variant.variant_type in VAF_EXEMPT_TYPES:
        return True
    return variant.vaf >= MIN_VAF_FOR_MATCH


def _satisfies_requirement(therapy: Therapy, variant: Variant) -> bool:
    """Gene match is necessary but not sufficient.

    A therapy that names a specific substitution (KRAS G12C) must not be
    satisfied by a different one in the same gene (KRAS G12D).
    """
    required = therapy.required_protein_change
    if not required:
        return True
    return _normalise_protein(required) == _normalise_protein(variant.protein_change)


def _describe_variant(variant: Variant) -> str:
    if variant.variant_type in VAF_EXEMPT_TYPES:
        return f"{variant.gene} {variant.protein_change}"
    return f"{variant.gene} {variant.protein_change} (VAF {variant.vaf:.1%})"


def _clinical_blockers(patient: Patient, therapy: Therapy) -> list[str]:
    """Exclusions that apply regardless of biomarker status."""
    blockers: list[str] = []
    if patient.ecog > MAX_ECOG:
        blockers.append(
            f"ECOG {patient.ecog} exceeds the supported performance-status window "
            f"(0-{MAX_ECOG})"
        )
    if patient.prior_lines >= therapy.line_of_therapy + 2:
        blockers.append(
            f"{patient.prior_lines} prior lines of therapy — this agent is positioned "
            f"at line {therapy.line_of_therapy}"
        )
    return blockers


def _tier_for(therapy: Therapy, patient: Patient) -> int:
    evidence = therapy.evidence_level.upper()
    on_label = therapy.approval_status.lower() in {"approved", "on-label"}
    within_line = patient.prior_lines < therapy.line_of_therapy

    if evidence == "A" and on_label and within_line:
        return 1
    if evidence in {"A", "B"}:
        return 2
    return 3


def match_patient(patient: Patient, therapies: list[Therapy]) -> MatchSummary:
    """Evaluate every therapy in the catalogue against one patient."""
    variants = list(patient.variants)
    actionable = [v for v in variants if _is_actionable(v)]

    by_gene: dict[str, list[Variant]] = {}
    for variant in actionable:
        by_gene.setdefault(variant.gene.upper(), []).append(variant)

    results: list[MatchResult] = []

    for therapy in therapies:
        gene = therapy.biomarker_gene.upper()
        gene_hits = by_gene.get(gene, [])
        hits = [v for v in gene_hits if _satisfies_requirement(therapy, v)]
        clinical = _clinical_blockers(patient, therapy)

        if not hits:
            # Distinguish "gene tested, nothing found" from "gene never tested",
            # and from "right gene, wrong substitution".
            gene_tested = any(v.gene.upper() == gene for v in variants)
            if gene_hits:
                found = ", ".join(_describe_variant(v) for v in gene_hits)
                reason = (
                    f"{gene} is altered ({found}) but not in the way this agent "
                    f"requires: {therapy.requirement}."
                )
            elif gene_tested:
                reason = (
                    f"{gene} was reported but no pathogenic or likely-pathogenic "
                    f"variant at VAF >= {MIN_VAF_FOR_MATCH:.0%} was found, so the "
                    f"biomarker requirement is not met."
                )
            else:
                reason = (
                    f"{gene} has no reported variant for this patient. The biomarker "
                    f"requirement is unmet — consider whether {gene} was covered by "
                    f"the assay before excluding this option."
                )
            results.append(
                MatchResult(
                    therapy_id=therapy.id,
                    therapy_name=therapy.name,
                    modality=therapy.modality,
                    status=Status.NOT_APPLICABLE,
                    tier=None,
                    score=0.0,
                    rationale=reason,
                    blockers=clinical,
                )
            )
            continue

        matched = [_describe_variant(v) for v in hits]
        best_vaf = max(v.vaf for v in hits)

        if clinical:
            results.append(
                MatchResult(
                    therapy_id=therapy.id,
                    therapy_name=therapy.name,
                    modality=therapy.modality,
                    status=Status.BLOCKED,
                    tier=None,
                    score=0.0,
                    rationale=(
                        f"Biomarker requirement met by {', '.join(matched)}, but a "
                        f"clinical exclusion applies."
                    ),
                    blockers=clinical,
                    matched_variants=matched,
                )
            )
            continue

        tier = _tier_for(therapy, patient)
        evidence = EVIDENCE_WEIGHT.get(therapy.evidence_level.upper(), 0.25)
        # Score: evidence dominates, VAF modulates, tier penalises.
        score = evidence * (0.6 + 0.4 * min(best_vaf / 0.5, 1.0)) * (1.0 - 0.1 * (tier - 1))

        rationale = (
            f"{therapy.requirement} satisfied by {', '.join(matched)}. "
            f"Evidence level {therapy.evidence_level.upper()}, "
            f"{therapy.approval_status}, positioned at line {therapy.line_of_therapy}."
        )

        results.append(
            MatchResult(
                therapy_id=therapy.id,
                therapy_name=therapy.name,
                modality=therapy.modality,
                status=Status.ELIGIBLE,
                tier=tier,
                score=score,
                rationale=rationale,
                matched_variants=matched,
            )
        )

    return MatchSummary(results=results, variant_count=len(variants))


def cohort_stats(patients: list[Patient]) -> dict[str, object]:
    """Aggregate view used by the analytics dashboard.

    Deliberately reports *coverage* rather than outcomes: we know which genes
    were tested and which therapies were reachable, not whether anyone
    responded.
    """
    gene_counts: dict[str, int] = {}
    diagnosis_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    tested_genes: set[str] = set()

    for patient in patients:
        diagnosis_counts[patient.diagnosis] = diagnosis_counts.get(patient.diagnosis, 0) + 1
        stage_counts[patient.stage] = stage_counts.get(patient.stage, 0) + 1
        for variant in patient.variants:
            gene = variant.gene.upper()
            tested_genes.add(gene)
            if _is_actionable(variant):
                gene_counts[gene] = gene_counts.get(gene, 0) + 1

    total = len(patients)
    with_actionable = sum(1 for p in patients if any(_is_actionable(v) for v in p.variants))

    return {
        "patient_count": total,
        "patients_with_actionable_variant": with_actionable,
        "actionable_rate": round(with_actionable / total, 4) if total else 0.0,
        "genes_tested": sorted(tested_genes),
        "actionable_variant_counts": dict(
            sorted(gene_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "by_diagnosis": dict(sorted(diagnosis_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_stage": dict(sorted(stage_counts.items())),
    }
