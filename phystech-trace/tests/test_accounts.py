import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway.accounts import Credentials, create_auth_router, password_hash, password_matches


class AccountTests(unittest.TestCase):
    def test_short_password_and_simple_email_are_allowed(self):
        credentials = Credentials(email="demo", password="1")
        self.assertEqual(credentials.password, "1")

    def test_password_is_salted_and_can_be_verified(self):
        first, second = password_hash("1"), password_hash("1")
        self.assertNotEqual(first, second)
        self.assertTrue(password_matches("1", first))
        self.assertFalse(password_matches("2", first))
        self.assertFalse(password_matches("1", "invalid"))

    def setUp(self):
        def unexpected_database():
            raise AssertionError("Rejected requests must not access the database")
        app = FastAPI()
        app.include_router(create_auth_router(unexpected_database))
        self.client = TestClient(app)

    def test_missing_session_is_unauthorized(self):
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_cross_origin_changes_are_rejected(self):
        for path in ["register", "login", "logout"]:
            response = self.client.post(f"/api/auth/{path}", json={"email": "demo", "password": "1"},
                                        headers={"Origin": "https://other.example"})
            self.assertEqual(response.status_code, 403)

    def test_empty_password_is_rejected(self):
        response = self.client.post("/api/auth/register", json={"email": "demo", "password": ""})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
