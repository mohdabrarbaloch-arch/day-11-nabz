"""API-level tests: auth, ownership isolation, validation, status codes."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestAuth:
    def test_register_returns_token_and_user(self, client: TestClient):
        response = client.post(
            "/api/auth/register",
            json={
                "email": "new@nabz.pk",
                "full_name": "New Clinician",
                "password": "strongpass123",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["email"] == "new@nabz.pk"
        assert "password" not in body["user"]

    def test_duplicate_email_is_409(self, client: TestClient, auth_headers):
        response = client.post(
            "/api/auth/register",
            json={
                "email": "tester@nabz.pk",
                "full_name": "Someone Else",
                "password": "strongpass123",
            },
        )
        assert response.status_code == 409

    def test_short_password_is_rejected(self, client: TestClient):
        response = client.post(
            "/api/auth/register",
            json={"email": "x@nabz.pk", "full_name": "X Y", "password": "short1"},
        )
        assert response.status_code == 422

    def test_password_without_digit_is_rejected(self, client: TestClient):
        response = client.post(
            "/api/auth/register",
            json={"email": "y@nabz.pk", "full_name": "Y Z", "password": "onlyletters"},
        )
        assert response.status_code == 422

    def test_login_with_wrong_password_is_401(self, client: TestClient, auth_headers):
        response = client.post(
            "/api/auth/login",
            json={"email": "tester@nabz.pk", "password": "wrongpassword1"},
        )
        assert response.status_code == 401

    def test_login_with_unknown_email_is_401(self, client: TestClient):
        response = client.post(
            "/api/auth/login",
            json={"email": "ghost@nabz.pk", "password": "strongpass123"},
        )
        assert response.status_code == 401

    def test_login_succeeds_with_correct_credentials(self, client: TestClient, auth_headers):
        response = client.post(
            "/api/auth/login",
            json={"email": "tester@nabz.pk", "password": "strongpass123"},
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    def test_protected_route_without_token_is_401(self, client: TestClient):
        assert client.get("/api/patients").status_code == 401

    def test_protected_route_with_garbage_token_is_401(self, client: TestClient):
        response = client.get("/api/patients", headers={"Authorization": "Bearer not-a-real-token"})
        assert response.status_code == 401

    def test_me_returns_the_caller(self, client: TestClient, auth_headers):
        response = client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["email"] == "tester@nabz.pk"


class TestPatients:
    def _create(self, client: TestClient, headers, mrn: str = "TEST-100"):
        return client.post(
            "/api/patients",
            headers=headers,
            json={
                "mrn": mrn,
                "display_name": "Test Patient",
                "age": 60,
                "sex": "female",
                "diagnosis": "Non-small cell lung cancer",
                "stage": "IV",
                "ecog": 1,
                "prior_lines": 0,
            },
        )

    def test_create_patient_returns_201(self, client: TestClient, auth_headers):
        response = self._create(client, auth_headers)
        assert response.status_code == 201
        assert response.json()["mrn"] == "TEST-100"

    def test_duplicate_mrn_is_409(self, client: TestClient, auth_headers):
        self._create(client, auth_headers)
        assert self._create(client, auth_headers).status_code == 409

    def test_invalid_age_is_422(self, client: TestClient, auth_headers):
        response = client.post(
            "/api/patients",
            headers=auth_headers,
            json={
                "mrn": "TEST-200",
                "display_name": "Bad Age",
                "age": 200,
                "sex": "male",
                "diagnosis": "NSCLC",
            },
        )
        assert response.status_code == 422

    def test_invalid_mrn_characters_are_422(self, client: TestClient, auth_headers):
        response = client.post(
            "/api/patients",
            headers=auth_headers,
            json={
                "mrn": "bad mrn!!",
                "display_name": "Bad MRN",
                "age": 40,
                "sex": "male",
                "diagnosis": "NSCLC",
            },
        )
        assert response.status_code == 422

    def test_list_returns_only_own_patients(self, client: TestClient, auth_headers):
        self._create(client, auth_headers)
        other = client.post(
            "/api/auth/register",
            json={
                "email": "other@nabz.pk",
                "full_name": "Other Clinician",
                "password": "strongpass123",
            },
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}

        assert len(client.get("/api/patients", headers=auth_headers).json()) == 1
        assert client.get("/api/patients", headers=other_headers).json() == []

    def test_other_clinicians_patient_is_404_not_403(self, client: TestClient, auth_headers):
        """404 rather than 403 so the response doesn't confirm the record exists."""
        patient_id = self._create(client, auth_headers).json()["id"]
        other = client.post(
            "/api/auth/register",
            json={
                "email": "third@nabz.pk",
                "full_name": "Third Clinician",
                "password": "strongpass123",
            },
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        response = client.get(f"/api/patients/{patient_id}", headers=other_headers)
        assert response.status_code == 404

    def test_patch_updates_a_field(self, client: TestClient, auth_headers):
        patient_id = self._create(client, auth_headers).json()["id"]
        response = client.patch(
            f"/api/patients/{patient_id}", headers=auth_headers, json={"ecog": 2}
        )
        assert response.status_code == 200
        assert response.json()["ecog"] == 2

    def test_delete_returns_204_then_404(self, client: TestClient, auth_headers):
        patient_id = self._create(client, auth_headers).json()["id"]
        assert client.delete(f"/api/patients/{patient_id}", headers=auth_headers).status_code == 204
        assert client.get(f"/api/patients/{patient_id}", headers=auth_headers).status_code == 404


class TestVariantsAndMatching:
    def _patient(self, client: TestClient, headers) -> int:
        return client.post(
            "/api/patients",
            headers=headers,
            json={
                "mrn": "MATCH-001",
                "display_name": "Match Patient",
                "age": 58,
                "sex": "female",
                "diagnosis": "Non-small cell lung cancer",
                "stage": "IV",
                "ecog": 1,
                "prior_lines": 0,
            },
        ).json()["id"]

    def test_add_variant_returns_201(self, client: TestClient, auth_headers):
        patient_id = self._patient(client, auth_headers)
        response = client.post(
            f"/api/patients/{patient_id}/variants",
            headers=auth_headers,
            json={
                "gene": "egfr",
                "protein_change": "p.L858R",
                "vaf": 0.34,
                "classification": "pathogenic",
            },
        )
        assert response.status_code == 201
        assert response.json()["gene"] == "EGFR"  # normalised to upper case

    def test_vaf_above_one_is_422(self, client: TestClient, auth_headers):
        patient_id = self._patient(client, auth_headers)
        response = client.post(
            f"/api/patients/{patient_id}/variants",
            headers=auth_headers,
            json={"gene": "EGFR", "protein_change": "p.L858R", "vaf": 1.5},
        )
        assert response.status_code == 422

    def test_duplicate_variant_is_409(self, client: TestClient, auth_headers):
        patient_id = self._patient(client, auth_headers)
        payload = {"gene": "EGFR", "protein_change": "p.L858R", "vaf": 0.3}
        client.post(f"/api/patients/{patient_id}/variants", headers=auth_headers, json=payload)
        response = client.post(
            f"/api/patients/{patient_id}/variants", headers=auth_headers, json=payload
        )
        assert response.status_code == 409

    def test_match_with_empty_catalogue_is_409(self, client: TestClient, auth_headers):
        patient_id = self._patient(client, auth_headers)
        response = client.post(f"/api/patients/{patient_id}/match", headers=auth_headers)
        assert response.status_code == 409

    def test_health_endpoint(self, client: TestClient):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_security_headers_present(self, client: TestClient):
        response = client.get("/api/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
