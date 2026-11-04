"""Demo data.

The therapy catalogue is a small, hand-curated set of real biomarker→drug
relationships, written down so the matcher has something honest to reason
over. It is deliberately short: a real deployment would load this from a
licensed knowledge base (OncoKB, CIViC, ESMO guidelines) and version it.

The patients are synthetic. Names are obviously fictional and the MRNs are
sequential — nothing here is derived from a real record.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from .database import session_scope
from .models import Patient, Therapy, User, Variant
from .security import hash_password

logger = logging.getLogger(__name__)

DEMO_EMAIL = "demo@nabz.pk"
DEMO_PASSWORD = "nabz-demo-2026"

#: (name, modality, gene, required_protein, requirement, indication, evidence, approval, line)
THERAPY_CATALOGUE: list[tuple[str, str, str, str | None, str, str, str, str, int]] = [
    (
        "Osimertinib",
        "TKI",
        "EGFR",
        None,
        "Activating EGFR sensitising mutation (ex19del, L858R)",
        "Non-small cell lung cancer",
        "A",
        "approved",
        1,
    ),
    (
        "Sotorasib",
        "TKI",
        "KRAS",
        "G12C",
        "KRAS G12C substitution",
        "Non-small cell lung cancer",
        "A",
        "approved",
        2,
    ),
    (
        "Olaparib",
        "PARP inhibitor",
        "BRCA1",
        None,
        "Pathogenic BRCA1 loss-of-function variant",
        "Ovarian / breast / pancreatic",
        "A",
        "approved",
        1,
    ),
    (
        "Olaparib (BRCA2)",
        "PARP inhibitor",
        "BRCA2",
        None,
        "Pathogenic BRCA2 loss-of-function variant",
        "Ovarian / breast / pancreatic",
        "A",
        "approved",
        1,
    ),
    (
        "Trastuzumab deruxtecan",
        "ADC",
        "ERBB2",
        None,
        "ERBB2 amplification or activating mutation",
        "HER2-expressing solid tumours",
        "A",
        "approved",
        2,
    ),
    (
        "Pembrolizumab (MSI-H)",
        "Checkpoint inhibitor",
        "MSI",
        None,
        "Microsatellite instability-high / dMMR",
        "Tumour-agnostic",
        "A",
        "approved",
        2,
    ),
    (
        "Alpelisib",
        "PI3K inhibitor",
        "PIK3CA",
        None,
        "PIK3CA activating mutation (H1047R, E545K)",
        "HR-positive breast cancer",
        "A",
        "approved",
        2,
    ),
    (
        "Dabrafenib + trametinib",
        "BRAF/MEK inhibitor",
        "BRAF",
        "V600E",
        "BRAF V600E/K mutation",
        "Melanoma, NSCLC, thyroid",
        "A",
        "approved",
        1,
    ),
    (
        "Ivosidenib",
        "IDH1 inhibitor",
        "IDH1",
        "R132C",
        "IDH1 R132 mutation",
        "AML, cholangiocarcinoma",
        "B",
        "approved",
        2,
    ),
    (
        "Entrectinib",
        "TRK inhibitor",
        "NTRK1",
        None,
        "NTRK1 fusion",
        "Tumour-agnostic",
        "A",
        "approved",
        2,
    ),
    (
        "Palbociclib",
        "CDK4/6 inhibitor",
        "CDKN2A",
        None,
        "CDKN2A loss with intact RB1",
        "Investigational across solid tumours",
        "C",
        "off-label",
        3,
    ),
    (
        "Adagrasib",
        "TKI",
        "KRAS",
        "G12C",
        "KRAS G12C substitution",
        "Colorectal / NSCLC",
        "B",
        "off-label",
        3,
    ),
]

#: (mrn, name, age, sex, diagnosis, stage, ecog, prior_lines,
#:  [(gene, protein, vaf, class, variant_type)])
PATIENTS: list[
    tuple[str, str, int, str, str, str, int, int, list[tuple[str, str, float, str, str]]]
] = [
    (
        "NABZ-0001",
        "Patient A. Rahman",
        58,
        "female",
        "Non-small cell lung cancer",
        "IV",
        1,
        0,
        [
            ("EGFR", "p.L858R", 0.34, "pathogenic", "snv"),
            ("TP53", "p.R273H", 0.41, "pathogenic", "snv"),
        ],
    ),
    (
        "NABZ-0002",
        "Patient S. Iqbal",
        64,
        "male",
        "Non-small cell lung cancer",
        "IV",
        2,
        2,
        [("KRAS", "p.G12C", 0.28, "pathogenic", "snv")],
    ),
    (
        "NABZ-0003",
        "Patient M. Fatima",
        47,
        "female",
        "High-grade serous ovarian carcinoma",
        "III",
        0,
        1,
        [("BRCA1", "p.Q1756fs", 0.62, "pathogenic", "indel")],
    ),
    (
        "NABZ-0004",
        "Patient R. Khan",
        52,
        "male",
        "Metastatic melanoma",
        "IV",
        1,
        0,
        [("BRAF", "p.V600E", 0.45, "pathogenic", "snv")],
    ),
    (
        "NABZ-0005",
        "Patient N. Siddiqui",
        61,
        "female",
        "Colorectal adenocarcinoma",
        "IV",
        1,
        1,
        [("MSI", "MSI-high", 0.0, "pathogenic", "msi")],
    ),
    (
        "NABZ-0006",
        "Patient H. Ali",
        39,
        "female",
        "HR-positive breast cancer",
        "II",
        0,
        0,
        [
            ("PIK3CA", "p.H1047R", 0.31, "pathogenic", "snv"),
            ("CDKN2A", "p.deletion", 0.55, "pathogenic", "cnv"),
        ],
    ),
    (
        "NABZ-0007",
        "Patient T. Bukhari",
        71,
        "male",
        "Cholangiocarcinoma",
        "IV",
        3,
        3,
        [("IDH1", "p.R132C", 0.38, "pathogenic", "snv")],
    ),
    (
        "NABZ-0008",
        "Patient Z. Hussain",
        44,
        "female",
        "Breast carcinoma",
        "III",
        0,
        1,
        [
            ("ERBB2", "p.S310F", 0.22, "pathogenic", "snv"),
            ("BRCA2", "p.E1308*", 0.48, "pathogenic", "snv"),
        ],
    ),
    (
        "NABZ-0009",
        "Patient F. Malik",
        55,
        "male",
        "Soft-tissue sarcoma",
        "IV",
        1,
        2,
        [("NTRK1", "fusion", 0.0, "pathogenic", "fusion")],
    ),
    (
        "NABZ-0010",
        "Patient K. Nawaz",
        66,
        "male",
        "Non-small cell lung cancer",
        "IV",
        2,
        1,
        [
            ("EGFR", "p.T790M", 0.12, "vus", "snv"),
            ("KRAS", "p.G12D", 0.19, "pathogenic", "snv"),
        ],
    ),
]


def seed_if_empty() -> dict[str, int]:
    """Populate the database only when it is genuinely empty."""
    created = {"users": 0, "therapies": 0, "patients": 0, "variants": 0}

    with session_scope() as db:
        if db.scalar(select(func.count()).select_from(User)) > 0:
            return created

        user = User(
            email=DEMO_EMAIL,
            full_name="Dr. Demo Clinician",
            password_hash=hash_password(DEMO_PASSWORD),
            role="clinician",
        )
        db.add(user)
        db.flush()
        created["users"] = 1

        for (
            name,
            modality,
            gene,
            required_protein,
            requirement,
            indication,
            evidence,
            approval,
            line,
        ) in THERAPY_CATALOGUE:
            db.add(
                Therapy(
                    name=name,
                    modality=modality,
                    biomarker_gene=gene,
                    required_protein_change=required_protein,
                    requirement=requirement,
                    indication=indication,
                    evidence_level=evidence,
                    approval_status=approval,
                    line_of_therapy=line,
                )
            )
            created["therapies"] += 1

        for mrn, name, age, sex, diagnosis, stage, ecog, prior, variants in PATIENTS:
            patient = Patient(
                owner_id=user.id,
                mrn=mrn,
                display_name=name,
                age=age,
                sex=sex,
                diagnosis=diagnosis,
                stage=stage,
                ecog=ecog,
                prior_lines=prior,
            )
            db.add(patient)
            db.flush()
            created["patients"] += 1

            for gene, protein, vaf, classification, variant_type in variants:
                db.add(
                    Variant(
                        patient_id=patient.id,
                        gene=gene,
                        protein_change=protein,
                        vaf=vaf,
                        read_depth=420,
                        classification=classification,
                        variant_type=variant_type,
                    )
                )
                created["variants"] += 1

    return created


if __name__ == "__main__":  # pragma: no cover
    from .database import init_db

    init_db()
    print(seed_if_empty())
