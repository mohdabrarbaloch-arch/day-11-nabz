"""End-to-end smoke test against a RUNNING Nabz server.

This is not a unit test. It talks to a real uvicorn process over HTTP and
prints what actually came back, so the numbers in the README can be checked
against a live system rather than a fixture.

    python scripts/smoke.py http://127.0.0.1:8011
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"

PASS = 0
FAIL = 0


def call(method: str, path: str, body: dict | None = None, token: str | None = None):
    """Make one HTTP call and return (status, parsed_body)."""
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode(errors="replace")
            return resp.status, _maybe_json(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        return exc.code, _maybe_json(raw)


def _maybe_json(raw: str):
    """Parse JSON when the body is JSON; otherwise return the raw text.

    Static assets (HTML, CSS, JS) are not JSON, and a smoke test that crashes
    on them is a broken smoke test.
    """
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


print(f"\n=== Nabz smoke test against {BASE} ===\n")

# ── health ────────────────────────────────────────────────────────────────
print("[health]")
status, body = call("GET", "/api/health")
check("GET /api/health is 200", status == 200, f"got {status}")
check("service is nabz", isinstance(body, dict) and body.get("service") == "nabz", str(body))

# ── auth ──────────────────────────────────────────────────────────────────
print("\n[auth]")
status, body = call(
    "POST", "/api/auth/login", {"email": "demo@nabz.pk", "password": "nabz-demo-2026"}
)
check("demo login is 200", status == 200, f"got {status} {body}")
token = body.get("access_token") if isinstance(body, dict) else None
check("login returns a token", bool(token))

status, _ = call(
    "POST", "/api/auth/login", {"email": "demo@nabz.pk", "password": "wrong-password"}
)
check("wrong password is 401", status == 401, f"got {status}")

status, _ = call("GET", "/api/patients")
check("unauthenticated /api/patients is 401", status == 401, f"got {status}")

status, me = call("GET", "/api/auth/me", token=token)
check("GET /api/auth/me is 200", status == 200, f"got {status}")
check("me returns the demo clinician", isinstance(me, dict) and me.get("email") == "demo@nabz.pk")

# ── patients ──────────────────────────────────────────────────────────────
print("\n[patients]")
status, patients = call("GET", "/api/patients", token=token)
check("GET /api/patients is 200", status == 200, f"got {status}")
check("10 seeded patients", isinstance(patients, list) and len(patients) == 10, f"got {len(patients) if isinstance(patients, list) else patients}")

# ── therapies ─────────────────────────────────────────────────────────────
print("\n[catalogue]")
status, therapies = call("GET", "/api/therapies", token=token)
check("GET /api/therapies is 200", status == 200, f"got {status}")
check("12 therapies in catalogue", isinstance(therapies, list) and len(therapies) == 12, f"got {len(therapies) if isinstance(therapies, list) else therapies}")

# ── the match that matters: EGFR L858R → Osimertinib tier 1 ───────────────
print("\n[match — NABZ-0001, EGFR L858R]")
rahman = next((p for p in patients if p["mrn"] == "NABZ-0001"), None)
check("NABZ-0001 exists", rahman is not None)
if rahman:
    status, run = call("POST", f"/api/patients/{rahman['id']}/match", token=token)
    check("POST match is 201", status == 201, f"got {status} {run}")
    if isinstance(run, dict):
        check("every therapy is reported", len(run["matches"]) == 12, f"got {len(run['matches'])}")
        osi = next((m for m in run["matches"] if m["therapy_name"] == "Osimertinib"), None)
        check("Osimertinib is eligible", osi is not None and osi["status"] == "eligible", str(osi))
        check("Osimertinib is tier 1", osi is not None and osi["tier"] == 1, str(osi))
        check(
            "Osimertinib rationale names the variant",
            osi is not None and "L858R" in osi["rationale"],
            str(osi.get("rationale") if osi else None),
        )
        # The safety property: KRAS G12C drug must NOT match an EGFR patient.
        sot = next((m for m in run["matches"] if m["therapy_name"] == "Sotorasib"), None)
        check("Sotorasib is not_applicable", sot is not None and sot["status"] == "not_applicable", str(sot))
        check(
            "Sotorasib reason mentions assay coverage",
            sot is not None and "covered by the assay" in sot["rationale"],
            str(sot.get("rationale") if sot else None),
        )

# ── the substitution guard: KRAS G12D must not match a G12C drug ──────────
print("\n[match — NABZ-0010, KRAS G12D (must NOT match G12C drugs)]")
nawaz = next((p for p in patients if p["mrn"] == "NABZ-0010"), None)
check("NABZ-0010 exists", nawaz is not None)
if nawaz:
    status, run = call("POST", f"/api/patients/{nawaz['id']}/match", token=token)
    check("POST match is 201", status == 201, f"got {status}")
    if isinstance(run, dict):
        sot = next((m for m in run["matches"] if m["therapy_name"] == "Sotorasib"), None)
        check(
            "Sotorasib does NOT match KRAS G12D",
            sot is not None and sot["status"] == "not_applicable",
            str(sot),
        )
        check(
            "reason names the wrong substitution",
            sot is not None and "G12D" in sot["rationale"] and "G12C" in sot["rationale"],
            str(sot.get("rationale") if sot else None),
        )

# ── clinical exclusion: NABZ-0007 has ECOG 3 ──────────────────────────────
print("\n[match — NABZ-0007, ECOG 3 (biomarker met, patient excluded)]")
bukhari = next((p for p in patients if p["mrn"] == "NABZ-0007"), None)
check("NABZ-0007 exists", bukhari is not None)
if bukhari:
    status, run = call("POST", f"/api/patients/{bukhari['id']}/match", token=token)
    check("POST match is 201", status == 201, f"got {status}")
    if isinstance(run, dict):
        ivo = next((m for m in run["matches"] if m["therapy_name"] == "Ivosidenib"), None)
        check("Ivosidenib is blocked, not eligible", ivo is not None and ivo["status"] == "blocked", str(ivo))
        check(
            "blocker names the ECOG value",
            ivo is not None and any("ECOG" in b for b in ivo["blockers"]),
            str(ivo.get("blockers") if ivo else None),
        )

# ── MSI: VAF-exempt variant type must still match ─────────────────────────
print("\n[match — NABZ-0005, MSI-high (VAF 0.0, must still match)]")
siddiqui = next((p for p in patients if p["mrn"] == "NABZ-0005"), None)
check("NABZ-0005 exists", siddiqui is not None)
if siddiqui:
    status, run = call("POST", f"/api/patients/{siddiqui['id']}/match", token=token)
    check("POST match is 201", status == 201, f"got {status}")
    if isinstance(run, dict):
        pembro = next(
            (m for m in run["matches"] if m["therapy_name"] == "Pembrolizumab (MSI-H)"), None
        )
        check(
            "Pembrolizumab matches despite VAF 0.0",
            pembro is not None and pembro["status"] == "eligible",
            str(pembro),
        )

# ── analytics ─────────────────────────────────────────────────────────────
print("\n[analytics]")
status, cohort = call("GET", "/api/analytics/cohort", token=token)
check("GET /api/analytics/cohort is 200", status == 200, f"got {status}")
if isinstance(cohort, dict):
    check("cohort counts 10 patients", cohort["patient_count"] == 10, str(cohort.get("patient_count")))
    check("genes_tested is populated", len(cohort["genes_tested"]) > 0, str(cohort.get("genes_tested")))
    print(f"        genes tested: {', '.join(cohort['genes_tested'])}")
    print(f"        by stage: {cohort['by_stage']}")

# ── validation ────────────────────────────────────────────────────────────
print("\n[validation]")
status, _ = call(
    "POST",
    "/api/patients",
    {"mrn": "BAD MRN!", "display_name": "X", "age": 40, "sex": "male", "diagnosis": "Test"},
    token=token,
)
check("invalid MRN characters are 422", status == 422, f"got {status}")

status, _ = call(
    "POST",
    "/api/patients",
    {"mrn": "NABZ-0001", "display_name": "Dup", "age": 40, "sex": "male", "diagnosis": "Test"},
    token=token,
)
check("duplicate MRN is 409", status == 409, f"got {status}")

status, _ = call(
    "POST",
    f"/api/patients/{rahman['id']}/variants" if rahman else "/api/patients/1/variants",
    {"gene": "TEST", "protein_change": "p.X1Y", "vaf": 1.4, "classification": "vus"},
    token=token,
)
check("VAF above 1.0 is 422", status == 422, f"got {status}")

# ── static assets ─────────────────────────────────────────────────────────
print("\n[static assets]")
for asset in ("/", "/static/styles.css", "/static/app.js"):
    status, _ = call("GET", asset)
    check(f"GET {asset} is 200", status == 200, f"got {status}")

# ── security headers ──────────────────────────────────────────────────────
print("\n[security headers]")
req = urllib.request.Request(f"{BASE}/api/health")
with urllib.request.urlopen(req, timeout=10) as resp:
    # HTTP header names are case-insensitive; normalise before comparing.
    headers = {k.lower(): v for k, v in resp.headers.items()}
check("X-Content-Type-Options is nosniff", headers.get("x-content-type-options") == "nosniff", str(headers.get("x-content-type-options")))
check("X-Frame-Options is DENY", headers.get("x-frame-options") == "DENY", str(headers.get("x-frame-options")))
check("Referrer-Policy is set", headers.get("referrer-policy") == "no-referrer", str(headers.get("referrer-policy")))

# ── summary ───────────────────────────────────────────────────────────────
print(f"\n=== {PASS} passed, {FAIL} failed ===\n")
sys.exit(1 if FAIL else 0)
