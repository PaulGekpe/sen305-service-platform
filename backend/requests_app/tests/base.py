"""Shared fixtures for the Lab 4 test modules."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from requests_app.models import Category, ServiceRequest


class WorkflowTestCase(TestCase):
    PASSWORD = "pass12345"

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("owner", password=self.PASSWORD)
        self.other = User.objects.create_user("other", password=self.PASSWORD)
        self.staff = User.objects.create_user("staff1", password=self.PASSWORD, is_staff=True)
        self.tech = User.objects.create_user("tech1", password=self.PASSWORD, is_staff=True)
        self.category = Category.objects.create(name="Facilities")
        self.item = self.make_request(self.owner, "Projector does not display")

    def make_request(self, requester, title, **extra):
        data = dict(
            requester=requester, category=self.category, title=title,
            description="The device reports a fault.", location="Room B12", priority="MEDIUM",
        )
        data.update(extra)
        return ServiceRequest.objects.create(**data)
