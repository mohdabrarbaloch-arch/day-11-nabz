# Nabz — Architecture

> Nabz (نبض) means *pulse*. This is a precision-oncology workspace: it holds a
> patient's clinical profile and molecular findings in one place, then runs a
> transparent biomarker→therapy matcher over them and shows its reasoning.

---

## 1. The problem this actually solves

A molecular tumour board asks one narrow question: *given what we found in this
patient's tumour, which therapies have their biomarker requirement satisfied —
and which do not, and why?*

The hard part is not the matching. It is the **explanation**. A black-box
"recommended: Osimertinib" is useless to a clinician, because they cannot tell
whether the engine considered the alternatives and rejected them, or never
considered them at all. Nabz's design decision is that **no therapy is ever
silently dropped**. Every therapy in the catalogue comes back with a verdict —
`eligible`, `blocked` or `not_applicable` — and a human-readable reason.

That is the whole product. Everything else is plumbing around it.

---

## 2. System diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser — vanilla JS SPA, no build step                             │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────────┐   │
│  │  Sign in   │ │  Patient   │ │  Molecular │ │  Cohort /        │   │
│  │            │ │  roster    │ │  profile   │ │  catalogue       │   │
│  └────────────┘ └────────────┘ └────────────┘ └──────────────────┘   │
└───────────────────────────┬──────────────────────────────────────────┘
                            │  fetch() + Bearer JWT
                            ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI application (app/main.py)                                   │
│                                                                      │
│  Middleware:  CORS allow-list · security headers · rate limiter      │
│                                                                      │
│  Routers (app/routers/)                                              │
│   auth        register · login · me                                  │
│   patients    CRUD + variants                                        │
│   matching    match runs · therapy catalogue · cohort analytics      │
│                            │                                         │
│                            ▼                                         │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Matching engine (app/services/matcher.py)                     │  │
│  │  Pure functions over ORM objects — no I/O, no session          │  │
│  │                                                                │  │
│  │   _is_actionable()          classification + VAF gate          │  │
│  │   _satisfies_requirement()  gene AND specific substitution     │  │
│  │   _clinical_blockers()      ECOG, prior lines                  │  │
│  │   _tier_for()               evidence × label × line            │  │
│  │   match_patient()           → MatchSummary                     │  │
│  │   cohort_stats()            coverage aggregates                │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                            │                                         │
│                            ▼                                         │
│  SQLAlchemy 2.0 ORM (app/models.py)                                  │
└───────────────────────────┬──────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────────────┐
        │  PostgreSQL 16 (docker-compose)           │
        │  SQLite fallback for local dev / tests    │
        └───────────────────────────────────────────┘
```

---

## 3. Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI 0.115 | Typed request/response models, automatic OpenAPI |
| ORM | SQLAlchemy 2.0 (typed `Mapped[]`) | Works on SQLite and Postgres unchanged |
| Validation | Pydantic v2 | Boundary validation; a VAF of 1.4 is rejected at the edge |
| Auth | PyJWT (HS256) + bcrypt (12 rounds) | Stateless; no session store |
| Rate limiting | In-process sliding window | Correct shape without a Redis dependency |
| Frontend | Vanilla JS SPA | No build step — three static files |
| DB | PostgreSQL 16 / SQLite | Postgres in compose, SQLite for dev and tests |
| Tests | pytest | 53 tests, engine-heavy |

**bcrypt is used directly, not through passlib.** passlib's bcrypt backend has
been broken against bcrypt ≥ 4.1 for a while; the direct API is three lines and
has no such problem.

---

## 4. Data model

```
User ──owns──> Patient ──has──> Variant
                  │
                  └──has──> MatchRun ──contains──> Match ──references──> Therapy
```

| Table | Purpose | Key columns |
|---|---|---|
| `users` | Clinicians | email, password_hash, role |
| `patients` | Clinical profile | mrn, display_name, age, sex, diagnosis, stage, ecog, prior_lines |
| `variants` | Molecular findings | patient_id, gene, protein_change, variant_type, vaf, classification |
| `therapies` | Curated knowledge base | name, modality, biomarker_gene, **required_protein_change**, requirement, evidence_level, approval_status, line_of_therapy |
| `match_runs` | One execution of the matcher | patient_id, variant_count, candidate_count, actionable_count |
| `matches` | One therapy's verdict in a run | run_id, therapy_id, status, tier, score, rationale, blockers, matched_variants |

**Why `required_protein_change` exists.** This is the column that makes the
matcher safe. A therapy that names a specific substitution — Sotorasib is
KRAS **G12C** — must not be satisfied by a different substitution in the same
gene. Without this column, a KRAS G12D tumour would match a G12C-only drug,
which is exactly the kind of confident wrong answer that makes a tool
dangerous. Gene match is necessary but not sufficient.

**Why a match is stored, not computed on read.** Unlike a derived score, a
match run is a *clinical event*: it records what the engine said on a given
date. Storing it means a later run can be diffed against an earlier one, which
is how you notice that a new variant changed the picture.

---

## 5. Data flow — from a variant to a verdict

```
1. POST /api/patients/{id}/variants
   body: { gene, protein_change, variant_type, vaf, classification }

2. Pydantic validates at the boundary: vaf ∈ [0,1], gene upper-cased,
   classification restricted to the five ACMG tiers.

3. POST /api/patients/{id}/match
   → matcher.match_patient(patient, therapies)

4. For each therapy in the catalogue:

   a. Is the gene present among the patient's ACTIONABLE variants?
      Actionable = classification ∈ {pathogenic, likely_pathogenic}
                   AND (variant_type ∈ {msi, fusion, cnv} OR vaf ≥ 5%)

   b. If the gene is present, does the specific substitution match?
      _satisfies_requirement() compares normalised protein changes, so
      "p.G12C" and "G12C" are the same finding but "G12D" is not.

   c. Do any clinical exclusions apply? (ECOG > 2, prior lines too far ahead)

   d. Verdict:
        no gene hit          → not_applicable  (with the reason it failed)
        gene hit + exclusion → blocked         (biomarker met, patient doesn't fit)
        gene hit, no block   → eligible        (tiered 1/2/3, scored)

5. The run and its matches are persisted; the response carries every verdict
   with its rationale, blockers and the variants that satisfied it.
```

**The VAF exemption is deliberate.** An MSI-high status or a gene fusion is
present or absent — it has no meaningful allele fraction. Applying a 5% VAF
floor to them would silently discard the most actionable findings in the panel.
`VAF_EXEMPT_TYPES` exists for exactly that reason.

---

## 6. The matching engine

### 6.1 Tiering

| Tier | Condition |
|---|---|
| 1 | Biomarker satisfied, evidence A, on-label, patient within the line window |
| 2 | Biomarker satisfied, evidence A or B, but off-label or beyond the labelled line |
| 3 | Biomarker satisfied, evidence C/D — tumour-board discussion, not a default |
| — | Blocked: biomarker absent, or a clinical exclusion applies |

### 6.2 Scoring

```
score = evidence_weight × (0.6 + 0.4 × min(best_vaf / 0.5, 1)) × (1 − 0.1 × (tier − 1))

evidence_weight:  A = 1.0   B = 0.75   C = 0.5   D = 0.25
```

Deliberately simple and monotonic. It **orders within a tier**; it does not
pretend to be a probability of response. A number that looks like a probability
but isn't one is worse than no number.

### 6.3 The three failure reasons

When a therapy is `not_applicable`, the engine distinguishes three genuinely
different situations, because they call for different actions:

| Situation | Message | What the clinician should do |
|---|---|---|
| Gene altered, wrong substitution | "KRAS is altered (G12D) but not in the way this agent requires: G12C" | Consider a different agent for the same gene |
| Gene reported, nothing actionable | "KRAS was reported but no pathogenic variant at VAF ≥ 5%" | Nothing — the biomarker is genuinely absent |
| Gene never reported | "KRAS has no reported variant — consider whether KRAS was covered by the assay" | **Check assay coverage** — this may be a gap, not a negative |

That third case is the one that matters most in practice. "Not tested" and
"tested negative" look identical in most systems, and conflating them is how a
patient gets excluded from a therapy they were never actually screened for.

---

## 7. Security

- **Passwords**: bcrypt, 12 rounds, never logged.
- **Tokens**: HS256 JWT, 12-hour default expiry, `sub` = email.
- **Secrets**: environment only. `Settings.validate()` refuses to boot in
  production with a placeholder or sub-32-character `SECRET_KEY`.
- **Rate limits**: 120 req/min general, 10 req/min on login.
- **CORS**: explicit allow-list, never `*` with credentials.
- **Headers**: `X-Content-Type-Options`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, `Permissions-Policy`, HSTS in production.
- **Ownership**: a patient belonging to another clinician returns **404, not
  403** — a 403 confirms the record exists, which leaks its presence.
- **Login**: identical message and identical work whether the email is unknown
  or the password is wrong, so timing does not reveal which half failed.
- **Errors**: a global handler logs the traceback and returns a generic 500.
  Stack traces never reach the client.

---

## 8. Scaling notes

**Where this breaks first.** `match_patient()` is O(therapies × variants) per
run, which is trivial at this size (a dozen therapies, a handful of variants).
The real cost is the **cohort analytics** endpoint, which loads every patient
with their variants to compute aggregates. That is fine for hundreds of
patients and wrong for hundreds of thousands.

**The path, in order:**

1. **Push the aggregates into SQL.** `cohort_stats()` currently counts in
   Python. It is a `GROUP BY` waiting to happen — `variants` already carries an
   index on `gene`, and `patients` on `(owner_id, diagnosis)`.
2. **Cache the cohort view.** It is read-mostly and changes only when a patient
   or variant is written. A short TTL keyed by `owner_id` removes almost all of
   the load.
3. **Move match runs to a background job.** A run is a write-heavy operation
   that a clinician does not need to wait on. Queue it, return a run id, poll.
4. **Version the therapy catalogue.** Today a therapy row is edited in place,
   which means a historical match run can no longer be reproduced. A real
   deployment needs `therapies` to be append-only with an effective date, so
   "what did the engine say in March" stays answerable.
5. **Partition `variants` by `patient_id`** once it passes tens of millions of
   rows. The access pattern is always per-patient.

**What does not need to change.** The matcher is pure functions over ORM
objects with no session and no I/O. It can be lifted into a worker, a batch
job, or a different service without modification. That separation is the main
scaling decision already made.

---

## 9. Deliberate limitations

Stated plainly, because a clinical tool that hides its edges is dangerous:

- **Not a medical device.** Nabz is research and portfolio software. It does
  not diagnose, does not predict response, and must not be used for clinical
  decisions.
- **The catalogue is hand-curated and short.** A dozen real biomarker→drug
  relationships, written down so the matcher has something honest to reason
  over. A real deployment would load this from a licensed knowledge base
  (OncoKB, CIViC, ESMO guidelines) and version it.
- **No drug–drug interaction checking.** Out of scope entirely.
- **No variant reclassification.** A VUS stays a VUS until someone edits it.
- **No audit log of who viewed what.** Required for a real deployment; not
  implemented here.
- **The patients are synthetic.** Names are obviously fictional and MRNs are
  sequential. Nothing is derived from a real record.
- **Tiering is a simplification.** Real molecular tumour boards weigh factors
  this engine does not model — prior response, comorbidities, patient
  preference, cost, availability.
