# Usage

A walkthrough of what Nabz does, in the order you'd actually use it.

---

## 1. Sign in

Open <http://localhost:8000>. The demo account is pre-filled:

```
demo@nabz.pk
nabz-demo-2026
```

You land on the **Patients** tab with ten synthetic patients already seeded.

---

## 2. Read a patient

Click any patient in the left list. The detail pane shows:

- **Header** — name, MRN, age, sex, diagnosis, stage, ECOG, prior lines.
- **Molecular profile** — every variant, with gene, protein change, VAF and
  ACMG classification. Pathogenic and likely-pathogenic findings are tagged in
  red; a VUS is grey.
- **Therapy matches** — the result of the last match run, if one exists.

Try **Patient A. Rahman** (`NABZ-0001`). She has an EGFR L858R at 34% VAF and a
TP53 R273H. Run a match and you'll see Osimertinib come back as **Tier 1** —
biomarker satisfied, evidence A, on-label, first line.

---

## 3. Run a match

Click **Run match**. The engine evaluates every therapy in the catalogue and
returns three groups:

| Group | Meaning |
|---|---|
| **Eligible** | Biomarker satisfied, no clinical exclusion. Tiered 1–3. |
| **Blocked** | Biomarker satisfied, but a clinical exclusion applies (ECOG, prior lines). |
| **Not applicable** | Biomarker requirement unmet — with the specific reason. |

The third group is the point of the whole tool. Read the reasons carefully;
they distinguish three genuinely different situations:

- *"KRAS is altered (G12D) but not in the way this agent requires: G12C"* —
  the gene is altered, just not usefully for **this** drug.
- *"KRAS was reported but no pathogenic variant at VAF ≥ 5%"* — genuinely
  negative.
- *"KRAS has no reported variant — consider whether KRAS was covered by the
  assay"* — **possibly never tested.** This is the one to act on.

---

## 4. Add a variant

On a patient's detail pane, use **Add variant**:

| Field | Notes |
|---|---|
| Gene | Upper-cased automatically. `egfr` → `EGFR` |
| Protein change | `p.L858R` and `L858R` are treated as the same finding |
| Variant type | `snv`, `indel`, `cnv`, `fusion`, `msi`, `other` |
| VAF | 0–1. Rejected outside that range |
| Classification | ACMG tier. Only pathogenic / likely-pathogenic are actionable |

**VAF is ignored for `msi`, `fusion` and `cnv`.** An MSI-high status is present
or absent — it has no meaningful allele fraction, and applying a 5% floor to it
would silently discard the most actionable finding in the panel.

---

## 5. Cohort view

The **Cohort** tab aggregates across your patients. It reports **coverage, not
outcomes** — what was tested and what was reachable, never whether anyone
responded. Specifically:

- Patient count and the share with at least one actionable variant
- Actionable variants by gene
- Breakdown by diagnosis and by stage
- The full list of genes tested

That last one is quietly the most useful. If a gene appears in the catalogue
but never in the tested list, nobody in your cohort has been screened for it.

---

## 6. Catalogue view

The **Catalogue** tab lists every therapy the matcher reasons over, with its
biomarker requirement, evidence level, approval status and line of therapy.

It is deliberately short — twelve real biomarker→drug relationships. A real
deployment would load this from a licensed knowledge base (OncoKB, CIViC, ESMO
guidelines) and version it. See `ARCHITECTURE.md` §9.

---

## 7. Reading a tier

| Tier | What it means | What to do |
|---|---|---|
| **1** | Evidence A, on-label, within the line window | Standard-of-care option |
| **2** | Evidence A/B, but off-label or beyond the labelled line | Reasonable, document the rationale |
| **3** | Evidence C/D | Tumour-board discussion, not a default |

Tier is not a probability. The score orders **within** a tier; it does not
estimate the chance of response.

---

## 8. What Nabz will not do

- It will not diagnose anything.
- It will not predict whether a therapy will work.
- It will not check drug–drug interactions.
- It will not reclassify a VUS.

It answers one narrow question — *which therapies have their biomarker
requirement satisfied, and why not the others* — and it answers it with its
reasoning attached. Everything else is a clinician's call.

**Nabz is research and portfolio software. It is not a medical device and must
not be used for clinical decisions.**
