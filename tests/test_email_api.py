import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from fastapi.testclient import TestClient

from app.main import create_app


def test_import_categorizes_payment_due_email():
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/emails/import",
            json={
                "emails": [
                    {
                        "provider_message_id": "msg-1",
                        "sender": "billing@example.com",
                        "subject": "Payment due tomorrow",
                        "body": "Action required: Please pay your invoice of $149 tomorrow.",
                    }
                ]
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["imported"] == 1
        email = data["emails"][0]
        assert email["category"] in {"payment_due", "invoice"}
        assert email["urgent"] is True
        assert email["priority_score"] >= 70


def test_list_and_summary():
    with TestClient(create_app()) as client:
        client.post(
            "/api/v1/emails/import",
            json={
                "emails": [
                    {
                        "provider_message_id": "msg-2",
                        "sender": "billing@example.com",
                        "subject": "Payment due tomorrow",
                        "body": "Action required: Please pay your invoice of $149 tomorrow.",
                    }
                ]
            },
        )

        list_response = client.get("/api/v1/emails?urgent=true")
        assert list_response.status_code == 200
        assert len(list_response.json()) >= 1

        summary_response = client.get("/api/v1/categories/summary")
        assert summary_response.status_code == 200
        assert summary_response.json()["total"] >= 1


def test_profiles_keep_duplicate_provider_message_ids_separate():
    with TestClient(create_app()) as client:
        payload = {
            "emails": [
                {
                    "provider_message_id": "shared-gmail-message-id",
                    "sender": "billing@example.com",
                    "subject": "Invoice due tomorrow",
                    "body": "Your invoice is due tomorrow.",
                }
            ]
        }

        alice_response = client.post("/api/v1/emails/import?profile=alice", json=payload)
        bob_response = client.post("/api/v1/emails/import?profile=bob", json=payload)

        assert alice_response.status_code == 200
        assert bob_response.status_code == 200
        assert alice_response.json()["imported"] == 1
        assert bob_response.json()["imported"] == 1
        assert alice_response.json()["emails"][0]["profile"] == "alice"
        assert bob_response.json()["emails"][0]["profile"] == "bob"

        alice_list = client.get("/api/v1/emails?profile=alice").json()
        bob_list = client.get("/api/v1/emails?profile=bob").json()

        assert {email["profile"] for email in alice_list} == {"alice"}
        assert {email["profile"] for email in bob_list} == {"bob"}

        alice_summary = client.get("/api/v1/categories/summary?profile=alice")
        bob_summary = client.get("/api/v1/categories/summary?profile=bob")

        assert alice_summary.json()["total"] == 1
        assert bob_summary.json()["total"] == 1
