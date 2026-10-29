import os
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
TEMP_DATABASE = tempfile.TemporaryDirectory(prefix="chi-tieu-ai-tests-")
DATABASE_PATH = Path(TEMP_DATABASE.name) / "test.db"
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{DATABASE_PATH.as_posix()}",
        "APP_ENV": "development",
        "SECRET_KEY": "automated-test-secret-key-not-for-production",
        "AI_PROVIDER": "mock",
        "ADMIN_EMAIL": "admin@example.com",
        "ADMIN_PASSWORD": "AdminTestPassword123",
    }
)

from fastapi.testclient import TestClient

import main
from services import password_reset_email
from services.financial_analyzer import analyze_system
from services.question_parser import parse_question


class ProjectAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(main.app)
        cls.client = cls.client_context.__enter__()
        response = cls.client.post(
            "/api/auth/register",
            json={
                "email": "audit-user@example.com",
                "password": "AuditUserPassword123",
                "full_name": "Audit User",
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"Unable to create test account: {response.status_code}")
        cls.auth_headers = {
            "Authorization": f"Bearer {response.json()['access_token']}"
        }

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        main.engine.dispose()
        TEMP_DATABASE.cleanup()

    def test_password_limits_match_bcrypt_capacity(self):
        valid = "ValidPass123"
        self.assertEqual(main.RegisterIn(
            email="valid@example.com",
            password=valid,
            full_name="Valid User",
        ).password, valid)

        with self.assertRaises(ValidationError):
            main.RegisterIn(
                email="long@example.com",
                password="A" * 72 + "1",
                full_name="Long Password",
            )
        with self.assertRaises(ValidationError):
            main.ResetPasswordIn(token="t" * 32, new_password="Short1")

        password_hash = main.hash_password(valid)
        self.assertTrue(main.verify_password(valid, password_hash))
        self.assertFalse(main.verify_password("A" * 72 + "1", password_hash))

    def test_budget_alert_is_recalculated_when_transaction_changes(self):
        category_response = self.client.post(
            "/api/categories",
            headers=self.auth_headers,
            json={"name": "Audit expense", "type": "expense"},
        )
        self.assertEqual(category_response.status_code, 200)
        category_id = category_response.json()["id"]

        today = date.today()
        budget_response = self.client.post(
            "/api/budgets",
            headers=self.auth_headers,
            json={
                "category_id": category_id,
                "month": today.month,
                "year": today.year,
                "limit_amount": 100,
            },
        )
        self.assertEqual(budget_response.status_code, 201)

        transaction_response = self.client.post(
            "/api/transactions",
            headers=self.auth_headers,
            json={
                "amount": 50,
                "type": "expense",
                "category_id": category_id,
                "txn_date": today.isoformat(),
                "note": "initial",
            },
        )
        self.assertEqual(transaction_response.status_code, 201)
        transaction_id = transaction_response.json()["id"]
        self.assertIsNone(transaction_response.json()["alert"])

        update_response = self.client.put(
            f"/api/transactions/{transaction_id}",
            headers=self.auth_headers,
            json={
                "amount": 90,
                "type": "expense",
                "category_id": category_id,
                "txn_date": today.isoformat(),
                "note": "updated",
            },
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertIsNotNone(update_response.json()["alert"], update_response.json())
        self.assertEqual(update_response.json()["alert"]["level"], "danger")

        notifications = self.client.get(
            "/api/notifications", headers=self.auth_headers
        ).json()
        self.assertTrue(any("90.0%" in item["message"] for item in notifications))

    def test_compare_rejects_invalid_month_and_year(self):
        response = self.client.get(
            "/api/stats/compare?m1=13&y1=2026&m2=1&y2=2026",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.get(
            "/api/stats/compare?m1=1&y1=1999&m2=1&y2=2026",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_admin_financial_facts_are_filtered_to_requested_period(self):
        with Session(main.engine) as db:
            user = db.query(main.User).filter(
                main.User.email == "audit-user@example.com"
            ).one()
            transactions = [
                main.Transaction(
                    user_id=user.id,
                    amount=10,
                    type="expense",
                    txn_date=date(2001, 1, 1),
                ),
                main.Transaction(
                    user_id=user.id,
                    amount=20,
                    type="expense",
                    txn_date=date(2000, 12, 31),
                ),
            ]
            ai_logs = [
                main.AILog(user_id=user.id, kind="chat", created_at=datetime(2001, 1, 1, 12)),
                main.AILog(user_id=user.id, kind="chat", created_at=datetime(2000, 12, 31, 23, 59, 59)),
            ]
            db.add_all(transactions + ai_logs)
            db.flush()
            transaction_ids = [item.id for item in transactions]
            ai_log_ids = [item.id for item in ai_logs]
            db.commit()
            try:
                parsed = parse_question(
                    "bao nhiêu giao dịch năm nay",
                    today=date(2001, 6, 15),
                )
                facts = analyze_system(db, parsed)
                self.assertEqual(facts["total_transactions"], 1)
                self.assertEqual(facts["ai_requests"], 1)
            finally:
                db.query(main.Transaction).filter(
                    main.Transaction.id.in_(transaction_ids)
                ).delete(synchronize_session=False)
                db.query(main.AILog).filter(
                    main.AILog.id.in_(ai_log_ids)
                ).delete(synchronize_session=False)
                db.commit()

    def test_ai_status_does_not_make_provider_requests(self):
        with patch.object(main, "AI_PROVIDER", "gemini"), patch.dict(
            os.environ, {"GEMINI_API_KEY": "test-key"}
        ), patch(
            "services.gemini_service.ask_gemini",
            side_effect=AssertionError("Status endpoint must not call Gemini"),
        ) as ask_gemini:
            response = self.client.get(
                "/api/ai/status", headers=self.auth_headers
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "configured")
        ask_gemini.assert_not_called()

    def test_legacy_gemini_adapter_sends_api_key_in_header(self):
        from services.ai_service import GeminiService

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-api-key"}):
            service = GeminiService()
        response = Mock()
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "OK"}]}}]
        }
        with patch("services.ai_service.httpx.post", return_value=response) as post:
            self.assertEqual(service.generate("hello"), "OK")

        request_url = post.call_args.args[0]
        request_headers = post.call_args.kwargs["headers"]
        self.assertNotIn("test-api-key", request_url)
        self.assertEqual(request_headers["x-goog-api-key"], "test-api-key")

    def test_image_upload_checks_actual_file_signature(self):
        response = self.client.post(
            "/api/chat/conversations/0/messages/with-image",
            headers=self.auth_headers,
            files={"file": ("fake.jpg", b"not an image", "image/jpeg")},
            data={"content": "Please inspect this"},
        )
        self.assertEqual(response.status_code, 415)

    def test_image_chat_text_is_bounded(self):
        response = self.client.post(
            "/api/chat/conversations/0/messages/with-image",
            headers=self.auth_headers,
            files={"file": ("fake.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
            data={"content": "x" * 4001},
        )
        self.assertEqual(response.status_code, 422)

    def test_smtp_rejects_invalid_port_and_unencrypted_auth(self):
        settings = {
            "APP_BASE_URL": "https://example.com",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_FROM_EMAIL": "no-reply@example.com",
            "SMTP_PORT": "not-a-port",
            "SMTP_TIMEOUT_SECONDS": "10",
            "SMTP_USE_TLS": "true",
            "SMTP_USE_SSL": "false",
            "SMTP_USERNAME": "",
            "SMTP_PASSWORD": "",
        }
        with patch.dict(os.environ, settings, clear=False):
            with self.assertRaises(password_reset_email.PasswordResetEmailConfigurationError):
                password_reset_email.ensure_password_reset_email_configured()

        settings.update(
            SMTP_PORT="587",
            SMTP_USE_TLS="false",
            SMTP_USERNAME="mailer",
            SMTP_PASSWORD="secret",
        )
        with patch.dict(os.environ, settings, clear=False):
            with self.assertRaises(password_reset_email.PasswordResetEmailConfigurationError):
                password_reset_email.ensure_password_reset_email_configured()

    def test_reset_email_escapes_html_link(self):
        smtp_settings = {
            "host": "smtp.example.com",
            "port": 587,
            "username": "",
            "password": "",
            "from_email": "no-reply@example.com",
            "use_tls": True,
            "use_ssl": False,
            "timeout": 10,
        }
        reset_url = 'https://example.com/login#token=x" onmouseover="alert(1)'
        with patch.object(password_reset_email, "_settings", return_value=smtp_settings):
            with patch.object(password_reset_email.smtplib, "SMTP") as smtp_factory:
                smtp_factory.return_value.__enter__.return_value.send_message.return_value = {}
                password_reset_email.send_password_reset_email("user@example.com", reset_url)
        smtp = smtp_factory.return_value.__enter__.return_value
        message = smtp.send_message.call_args.args[0]
        html_body = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("&quot; onmouseover=&quot;", html_body)


if __name__ == "__main__":
    unittest.main()
