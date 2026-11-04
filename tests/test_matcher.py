"""Tests for the matching engine — the part that must be right.

These are the tests that matter. Everything else in the app is plumbing
around this logic, so the assertions here are written against hand-checked
clinical expectations rather than against whatever the code happens to do.
"""

from __future__ import annotations

import pytest

from app.models import Patient, Therapy, Variant
from app.services.matcher import (
    MIN_VAF_FOR_MATCH,
    Status,
    cohort_stats,
    match_patient,
)


def make_therapy(**overrides) -> Therapy:
    defaults = dict(
        id=1,
        name="Test Drug",
        modality="TKI",
        biomarker_gene="EGFR",
        required_protein_change=None,
        requirement="Activating EGFR mutation",
        indication="NSCLC",
        evidence_level="A",
        approval_status="approved",
        line_of_therapy=1,
    )
    defaults.update(overrides)
    return Therapy(**defaults)


def make_patient(variants: list[Variant], **overrides) -> Patient:
    defaults = dict(
        id=1,
        mrn="TEST-001",
        display_name="Test Patient",
        age=55,
        sex="female",
        diagnosis="NSCLC",
        stage="IV",
        ecog=0,
        prior_lines=0,
    )
    defaults.update(overrides)
    patient = Patient(**defaults)
    patient.variants = variants
    return patient


def make_variant(**overrides) -> Variant:
    defaults = dict(
        id=1,
        gene="EGFR",
        protein_change="p.L858R",
        variant_type="snv",
        vaf=0.35,
        read_depth=500,
        classification="pathogenic",
    )
    defaults.update(overrides)
    return Variant(**defaults)


class TestGeneMatching:
    def test_matching_gene_and_pathogenic_variant_is_eligible(self):
        patient = make_patient([make_variant()])
        summary = match_patient(patient, [make_therapy()])
        assert len(summary.eligible) == 1
        assert summary.eligible[0].status is Status.ELIGIBLE

    def test_absent_gene_is_not_applicable(self):
        patient = make_patient([make_variant(gene="BRAF", protein_change="p.V600E")])
        summary = match_patient(patient, [make_therapy()])
        assert summary.eligible == []
        assert summary.results[0].status is Status.NOT_APPLICABLE

    def test_vus_is_not_actionable(self):
        """A variant of uncertain significance must not justify a therapy."""
        patient = make_patient([make_variant(classification="vus")])
        summary = match_patient(patient, [make_therapy()])
        assert summary.eligible == []

    def test_benign_variant_is_not_actionable(self):
        patient = make_patient([make_variant(classification="benign")])
        summary = match_patient(patient, [make_therapy()])
        assert summary.eligible == []

    def test_likely_pathogenic_counts(self):
        patient = make_patient([make_variant(classification="likely_pathogenic")])
        summary = match_patient(patient, [make_therapy()])
        assert len(summary.eligible) == 1


class TestSpecificSubstitution:
    """The bug this class exists to prevent: gene-only matching."""

    def test_wrong_substitution_does_not_match(self):
        therapy = make_therapy(
            biomarker_gene="KRAS",
            required_protein_change="G12C",
            requirement="KRAS G12C",
        )
        patient = make_patient([make_variant(gene="KRAS", protein_change="p.G12D")])
        summary = match_patient(patient, [therapy])
        assert summary.eligible == []
        assert "not in the way this agent requires" in summary.results[0].rationale

    def test_correct_substitution_matches(self):
        therapy = make_therapy(
            biomarker_gene="KRAS",
            required_protein_change="G12C",
            requirement="KRAS G12C",
        )
        patient = make_patient([make_variant(gene="KRAS", protein_change="p.G12C")])
        summary = match_patient(patient, [therapy])
        assert len(summary.eligible) == 1

    def test_p_prefix_is_normalised(self):
        """'p.G12C' and 'G12C' must be treated as the same finding."""
        therapy = make_therapy(
            biomarker_gene="KRAS", required_protein_change="p.G12C", requirement="KRAS G12C"
        )
        patient = make_patient([make_variant(gene="KRAS", protein_change="G12C")])
        summary = match_patient(patient, [therapy])
        assert len(summary.eligible) == 1


class TestVafHandling:
    def test_below_vaf_floor_is_not_actionable(self):
        patient = make_patient([make_variant(vaf=MIN_VAF_FOR_MATCH - 0.01)])
        summary = match_patient(patient, [make_therapy()])
        assert summary.eligible == []

    def test_at_vaf_floor_is_actionable(self):
        patient = make_patient([make_variant(vaf=MIN_VAF_FOR_MATCH)])
        summary = match_patient(patient, [make_therapy()])
        assert len(summary.eligible) == 1

    @pytest.mark.parametrize("variant_type", ["msi", "fusion", "cnv"])
    def test_vaf_exempt_types_ignore_the_floor(self, variant_type: str):
        """MSI-high and fusions have no meaningful VAF — a 0.0 must not exclude them."""
        patient = make_patient(
            [make_variant(variant_type=variant_type, vaf=0.0, protein_change="MSI-high")]
        )
        summary = match_patient(patient, [make_therapy()])
        assert len(summary.eligible) == 1


class TestClinicalExclusions:
    def test_high_ecog_blocks_an_otherwise_eligible_therapy(self):
        patient = make_patient([make_variant()], ecog=3)
        summary = match_patient(patient, [make_therapy()])
        assert summary.eligible == []
        assert summary.results[0].status is Status.BLOCKED
        assert any("ECOG" in b for b in summary.results[0].blockers)

    def test_ecog_two_is_still_eligible(self):
        patient = make_patient([make_variant()], ecog=2)
        summary = match_patient(patient, [make_therapy()])
        assert len(summary.eligible) == 1

    def test_many_prior_lines_blocks(self):
        patient = make_patient([make_variant()], prior_lines=5)
        summary = match_patient(patient, [make_therapy(line_of_therapy=1)])
        assert summary.eligible == []
        assert summary.results[0].status is Status.BLOCKED


class TestTiering:
    def test_evidence_a_on_label_first_line_is_tier_one(self):
        patient = make_patient([make_variant()])
        summary = match_patient(patient, [make_therapy()])
        assert summary.eligible[0].tier == 1

    def test_off_label_is_not_tier_one(self):
        patient = make_patient([make_variant()])
        therapy = make_therapy(approval_status="off-label")
        summary = match_patient(patient, [therapy])
        assert summary.eligible[0].tier == 2

    def test_evidence_c_is_tier_three(self):
        patient = make_patient([make_variant()])
        therapy = make_therapy(evidence_level="C", approval_status="off-label")
        summary = match_patient(patient, [therapy])
        assert summary.eligible[0].tier == 3

    def test_ranking_puts_eligible_before_not_applicable(self):
        patient = make_patient([make_variant()])
        therapies = [
            make_therapy(id=1, name="Zeta", biomarker_gene="BRAF"),
            make_therapy(id=2, name="Alpha", biomarker_gene="EGFR"),
        ]
        summary = match_patient(patient, therapies)
        ranked = summary.ranked()
        assert ranked[0].therapy_name == "Alpha"
        assert ranked[0].status is Status.ELIGIBLE


class TestScoring:
    def test_higher_vaf_scores_higher_within_a_tier(self):
        low = match_patient(make_patient([make_variant(vaf=0.10)]), [make_therapy()])
        high = match_patient(make_patient([make_variant(vaf=0.50)]), [make_therapy()])
        assert high.eligible[0].score > low.eligible[0].score

    def test_score_is_bounded(self):
        summary = match_patient(make_patient([make_variant(vaf=1.0)]), [make_therapy()])
        assert 0.0 < summary.eligible[0].score <= 1.0

    def test_blocked_scores_zero(self):
        summary = match_patient(make_patient([make_variant()], ecog=4), [make_therapy()])
        assert summary.results[0].score == 0.0


class TestRationale:
    def test_every_result_has_a_non_empty_rationale(self):
        patient = make_patient([make_variant()])
        therapies = [
            make_therapy(id=1, name="A", biomarker_gene="EGFR"),
            make_therapy(id=2, name="B", biomarker_gene="BRAF"),
        ]
        summary = match_patient(patient, therapies)
        assert all(r.rationale.strip() for r in summary.results)

    def test_untested_gene_says_so(self):
        patient = make_patient([make_variant(gene="EGFR")])
        summary = match_patient(patient, [make_therapy(biomarker_gene="ALK")])
        assert "no reported variant" in summary.results[0].rationale

    def test_no_therapy_is_silently_dropped(self):
        patient = make_patient([make_variant()])
        therapies = [make_therapy(id=i, name=f"T{i}", biomarker_gene="BRAF") for i in range(5)]
        summary = match_patient(patient, therapies)
        assert len(summary.results) == 5


class TestCohortStats:
    def test_counts_patients_and_actionable_rate(self):
        patients = [
            make_patient([make_variant()], id=1, mrn="A"),
            make_patient([make_variant(classification="vus")], id=2, mrn="B"),
        ]
        stats = cohort_stats(patients)
        assert stats["patient_count"] == 2
        assert stats["patients_with_actionable_variant"] == 1
        assert stats["actionable_rate"] == 0.5

    def test_empty_cohort_does_not_divide_by_zero(self):
        stats = cohort_stats([])
        assert stats["patient_count"] == 0
        assert stats["actionable_rate"] == 0.0

    def test_genes_tested_includes_non_actionable(self):
        patients = [make_patient([make_variant(gene="TP53", classification="vus")])]
        stats = cohort_stats(patients)
        assert "TP53" in stats["genes_tested"]
        assert "TP53" not in stats["actionable_variant_counts"]
