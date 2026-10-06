from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient


class ScaffoldTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_endpoint_reports_database_ok(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"], "ok")
        self.assertEqual(response.json()["database_engine"], "postgresql")
        self.assertEqual(response.json()["currency"], "RWF")

    def test_tests_run_on_postgresql(self):
        self.assertEqual(connection.vendor, "postgresql")

    def test_custom_user_model_is_active(self):
        self.assertEqual(get_user_model()._meta.label, "accounts.User")
