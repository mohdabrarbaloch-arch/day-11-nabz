# API Reference

Base URL: `http://localhost:8000`. Interactive docs at `/docs` (Swagger) and
`/redoc`.

All endpoints except `/api/health`, `/api/auth/register` and `/api/auth/login`
require a bearer token:

```
Authorization: Bearer <access_token>
```

---

## Meta

### `GET /api/health`

```json
{ "status": "ok", "service": "nabz", "version": "1.0.0" }
```

---

## Auth

### `POST /api/auth/register` → `201`

```json
{ "email": "you@clinic.pk", "full_name": "Dr. A. Baloch", "password": "strongpass123" }
```

Password rules: 10–128 characters, at least one digit, not on a small
common-password list. Returns a token immediately — no email confirmation step.

| Status | When |
|---|---|
| `201` | Created |
| `409` | Email already registered |
| `422` | Password too short, no digit, or invalid email |

### `POST /api/auth/login` → `200`

```json
{ "email": "demo@nabz.pk", "password": "nabz-demo-2026" }
```

Returns `401` with the same message whether the email is unknown or the
password is wrong — the response never reveals which half failed.

Rate limited to 10 requests/minute per IP.

### `GET /api/auth/me` → `200`

Returns the authenticated user.

**Response shape for all three:**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": { "id": 1, "email": "demo@nabz.pk", "full_name": "Dr. Demo Clinician", "role": "clinician" }
}
```

---

## Patients

### `GET /api/patients` → `200`

| Query | Type | Default | Notes |
|---|---|---|---|
| `diagnosis` | string | — | Case-insensitive substring match |
| `limit` | int | 50 | 1–200 |
| `offset` | int | 0 | ≥ 0 |

Returns only the caller's own patients.

### `POST /api/patients` → `201`

```json
{
  "mrn": "NABZ-0011",
  "display_name": "Patient L. Ahmed",
  "age": 62,
  "sex": "male",
  "diagnosis": "Non-small cell lung cancer",
  "stage": "IV",
  "ecog": 1,
  "prior_lines": 0,
  "notes": "Biopsy confirmed adenocarcinoma."
}
```

`mrn` must match `^[A-Za-z0-9\-]+$` and is **globally unique** — a database
constraint, not a per-clinician one, because an MRN identifies a patient across
the institution. `age` 0–120, `ecog` 0–5, `prior_lines` 0–20.

| Status | When |
|---|---|
| `201` | Created |
| `409` | MRN already in use |
| `422` | Invalid MRN characters, age out of range, unknown stage/sex |

### `GET /api/patients/{id}` → `200`

Returns the patient with their variants embedded.

### `PATCH /api/patients/{id}` → `200`

Any subset of the create fields. Only the fields you send are changed.

### `DELETE /api/patients/{id}` → `204`

Cascades to variants and match runs.

**A patient belonging to another clinician returns `404`, not `403`.** A 403
would confirm the record exists, which leaks its presence.

---

## Variants

### `POST /api/patients/{id}/variants` → `201`

```json
{
  "gene": "EGFR",
  "protein_change": "p.L858R",
  "coding_change": "c.2573T>G",
  "variant_type": "snv",
  "vaf": 0.34,
  "read_depth": 420,
  "classification": "pathogenic"
}
```

`gene` is upper-cased on the way in. `vaf` must be 0–1. `classification` is one
of `pathogenic`, `likely_pathogenic`, `vus`, `likely_benign`, `benign`.
`variant_type` is one of `snv`, `indel`, `cnv`, `fusion`, `msi`, `other`.

| Status | When |
|---|---|
| `201` | Created |
| `409` | Same gene + protein change already recorded for this patient |
| `422` | VAF outside 0–1, unknown classification or variant type |

### `GET /api/patients/{id}/variants` → `200`

Ordered by VAF descending.

### `DELETE /api/patients/{id}/variants/{variant_id}` → `204`

---

## Matching

### `GET /api/therapies` → `200`

| Query | Type | Notes |
|---|---|---|
| `gene` | string | Filter by biomarker gene, e.g. `EGFR` |

Returns the whole catalogue, ordered by gene then name.

### `POST /api/patients/{id}/match` → `201`

Runs the matcher and persists the result. No request body.

```json
{
  "id": 7,
  "patient_id": 1,
  "created_at": "2026-11-05T00:12:44",
  "variant_count": 2,
  "candidate_count": 12,
  "actionable_count": 1,
  "matches": [
    {
      "therapy_id": 1,
      "therapy_name": "Osimertinib",
      "modality": "TKI",
      "status": "eligible",
      "tier": 1,
      "score": 0.872,
      "rationale": "Activating EGFR sensitising mutation (ex19del, L858R) satisfied by EGFR p.L858R (VAF 34.0%). Evidence level A, approved, positioned at line 1.",
      "blockers": [],
      "matched_variants": ["EGFR p.L858R (VAF 34.0%)"]
    },
    {
      "therapy_id": 2,
      "therapy_name": "Sotorasib",
      "modality": "TKI",
      "status": "not_applicable",
      "tier": null,
      "score": 0.0,
      "rationale": "KRAS has no reported variant for this patient. The biomarker requirement is unmet — consider whether KRAS was covered by the assay before excluding this option.",
      "blockers": [],
      "matched_variants": []
    }
  ]
}
```

`status` is one of `eligible`, `blocked`, `not_applicable`. Every therapy in the
catalogue appears in `matches` — nothing is silently dropped.

| Status | When |
|---|---|
| `201` | Run completed |
| `409` | The therapy catalogue is empty |

### `GET /api/patients/{id}/matches` → `200`

All previous runs for a patient, newest first, each with its full match list.

---

## Analytics

### `GET /api/analytics/cohort` → `200`

```json
{
  "patient_count": 10,
  "patients_with_actionable_variant": 10,
  "actionable_rate": 1.0,
  "genes_tested": ["BRAF", "BRCA1", "BRCA2", "CDKN2A", "EGFR", "ERBB2", "IDH1", "KRAS", "MSI", "NTRK1", "PIK3CA", "TP53"],
  "actionable_variant_counts": { "EGFR": 1, "KRAS": 2, "BRCA1": 1 },
  "by_diagnosis": { "Non-small cell lung cancer": 3 },
  "by_stage": { "II": 1, "III": 2, "IV": 7 }
}
```

Scoped to the caller's own patients. Reports **coverage, not outcomes**.

---

## Errors

Every error is `{"detail": "..."}`.

| Status | Meaning |
|---|---|
| `401` | Missing, malformed or expired token |
| `404` | Not found, or not yours |
| `409` | Conflict — duplicate MRN, duplicate variant, empty catalogue |
| `422` | Validation failure (Pydantic, with field-level detail) |
| `429` | Rate limited. `Retry-After` header carries the wait in seconds |
| `500` | Internal error. Logged server-side; the client gets a generic message |

---

## Rate limits

| Scope | Limit |
|---|---|
| All routes | 120 requests/minute per IP |
| `/api/auth/login` | 10 requests/minute per IP |

State is per-process, so N workers allow N times the configured rate. A shared
Redis counter is the production answer; see `ARCHITECTURE.md` §8.
