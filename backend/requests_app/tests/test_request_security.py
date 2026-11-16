"""Unauthorised paths, CSRF, POST-only mutations, PRG and field whitelisting."""

from django.test import Client
from django.urls import reverse

from requests_app.models import Comment, ServiceRequest, WorkOrder
from requests_app.services import service_request_assign

from .base import WorkflowTestCase


class AnonymousAccessTests(WorkflowTestCase):
    def test_every_request_url_redirects_anonymous_users_to_login(self):
        urls = [
            ("get", reverse("requests:list")),
            ("get", reverse("requests:create")),
            ("get", reverse("requests:detail", args=[self.item.id])),
            ("get", reverse("requests:update", args=[self.item.id])),
            ("post", reverse("requests:comment-add", args=[self.item.id])),
            ("post", reverse("requests:assign", args=[self.item.id])),
            ("post", reverse("requests:resolve", args=[self.item.id])),
        ]
        for method, url in urls:
            with self.subTest(url=url):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("login")))
                self.assertIn("next=", response.url)

    def test_login_page_signs_a_user_in_and_lands_on_the_list(self):
        response = self.client.post(
            reverse("login"), {"username": "owner", "password": self.PASSWORD}
        )
        self.assertRedirects(response, reverse("requests:list"))

    def test_logout_requires_post_and_returns_home(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("core:home"))


class ObjectLevelAuthorizationTests(WorkflowTestCase):
    """requester2 must learn nothing about requester1's rows: always 404, never 403."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.other)

    def test_other_requester_cannot_open_the_edit_page(self):
        response = self.client.get(reverse("requests:update", args=[self.item.id]))
        self.assertEqual(response.status_code, 404)

    def test_other_requester_cannot_update(self):
        response = self.client.post(reverse("requests:update", args=[self.item.id]), {
            "category": self.category.id, "title": "Hijacked by someone else",
            "description": "x", "location": "x", "priority": "LOW",
        })
        self.assertEqual(response.status_code, 404)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, "Projector does not display")

    def test_other_requester_cannot_comment(self):
        response = self.client.post(
            reverse("requests:comment-add", args=[self.item.id]), {"body": "Sneaky comment"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Comment.objects.count(), 0)

    def test_other_requester_cannot_resolve(self):
        response = self.client.post(
            reverse("requests:resolve", args=[self.item.id]), {"work_notes": "Not mine"}
        )
        self.assertEqual(response.status_code, 404)

    def test_other_requester_is_refused_assignment_with_403(self):
        response = self.client.post(
            reverse("requests:assign", args=[self.item.id]), {"technician": self.tech.id}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_list_never_contains_another_requesters_rows(self):
        response = self.client.get(reverse("requests:list"))
        self.assertNotContains(response, self.item.title)

    def test_the_404_page_does_not_name_the_owner_or_title(self):
        response = self.client.get(reverse("requests:detail", args=[self.item.id]))
        self.assertNotContains(response, "owner", status_code=404)
        self.assertNotContains(response, self.item.title, status_code=404)


class EditRuleTests(WorkflowTestCase):
    def payload(self, **extra):
        data = {
            "category": self.category.id, "title": "Projector bulb has failed",
            "description": "No image at all.", "location": "Room B14", "priority": "HIGH",
        }
        data.update(extra)
        return data

    def test_owner_can_edit_an_open_request(self):
        self.client.force_login(self.owner)
        url = reverse("requests:update", args=[self.item.id])
        response = self.client.post(url, self.payload())
        self.assertRedirects(response, reverse("requests:detail", args=[self.item.id]))
        self.item.refresh_from_db()
        self.assertEqual((self.item.title, self.item.location), ("Projector bulb has failed", "Room B14"))

    def test_owner_cannot_edit_once_the_request_is_assigned(self):
        service_request_assign(item=self.item, technician=self.tech, actor=self.staff)
        self.client.force_login(self.owner)
        response = self.client.post(reverse("requests:update", args=[self.item.id]), self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Only an open request can be edited.")
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, "Projector does not display")

    def test_staff_can_edit_an_assigned_request(self):
        service_request_assign(item=self.item, technician=self.tech, actor=self.staff)
        self.client.force_login(self.staff)
        response = self.client.post(reverse("requests:update", args=[self.item.id]), self.payload())
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, "Projector bulb has failed")
        self.assertEqual(self.item.status, ServiceRequest.Status.ASSIGNED)

    def test_edit_link_visibility_matches_the_server_rule(self):
        edit = reverse("requests:update", args=[self.item.id])
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("requests:detail", args=[self.item.id])), edit)
        service_request_assign(item=self.item, technician=self.tech, actor=self.staff)
        self.assertNotContains(self.client.get(reverse("requests:detail", args=[self.item.id])), edit)
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("requests:detail", args=[self.item.id])), edit)

    def test_server_owned_fields_cannot_be_posted(self):
        self.client.force_login(self.owner)
        before = ServiceRequest.objects.count()
        self.client.post(reverse("requests:create"), self.payload(
            title="Smuggled fields attempt", requester=self.other.id,
            status="RESOLVED", resolved_at="2030-01-01 00:00:00",
        ))
        created = ServiceRequest.objects.get(title="Smuggled fields attempt")
        self.assertEqual(ServiceRequest.objects.count(), before + 1)
        self.assertEqual(created.requester, self.owner)
        self.assertEqual(created.status, ServiceRequest.Status.OPEN)
        self.assertIsNone(created.resolved_at)

    def test_inactive_category_is_not_accepted(self):
        self.category.is_active = False
        self.category.save()
        self.client.force_login(self.owner)
        before = ServiceRequest.objects.count()
        response = self.client.post(reverse("requests:create"), self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ServiceRequest.objects.count(), before)


class CommentTests(WorkflowTestCase):
    def test_comment_author_comes_from_the_logged_in_user(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("requests:comment-add", args=[self.item.id]),
            {"body": "Still not working.", "author": self.other.id, "is_internal": "on"},
        )
        self.assertRedirects(response, reverse("requests:detail", args=[self.item.id]))
        comment = Comment.objects.get()
        self.assertEqual(comment.author, self.owner)
        self.assertFalse(comment.is_internal)

    def test_short_comment_is_rejected_with_a_message(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("requests:comment-add", args=[self.item.id]), {"body": "ok"}, follow=True
        )
        self.assertContains(response, "Enter at least 3 characters.")
        self.assertEqual(Comment.objects.count(), 0)

    def test_comment_endpoint_is_post_only(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("requests:comment-add", args=[self.item.id]))
        self.assertEqual(response.status_code, 405)

    def test_internal_comments_are_hidden_from_requesters_but_not_staff(self):
        Comment.objects.create(service_request=self.item, author=self.staff, body="Visible note")
        Comment.objects.create(
            service_request=self.item, author=self.staff, body="Staff only note", is_internal=True
        )
        self.client.force_login(self.owner)
        detail = self.client.get(reverse("requests:detail", args=[self.item.id]))
        self.assertContains(detail, "Visible note")
        self.assertNotContains(detail, "Staff only note")
        row = self.client.get(reverse("requests:list")).context["page_obj"][0]
        self.assertEqual(row.comment_count, 1)
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("requests:detail", args=[self.item.id])), "Staff only note")
        self.assertEqual(self.client.get(reverse("requests:list")).context["page_obj"][0].comment_count, 2)


class CsrfAndRedirectTests(WorkflowTestCase):
    def test_post_without_a_csrf_token_is_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        before = ServiceRequest.objects.count()
        response = client.post(reverse("requests:create"), {
            "category": self.category.id, "title": "No token supplied here",
            "description": "x", "location": "x", "priority": "LOW",
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ServiceRequest.objects.count(), before)

    def test_every_mutating_form_renders_a_csrf_token(self):
        service_request_assign(item=self.item, technician=self.tech, actor=self.staff)
        self.client.force_login(self.staff)
        detail = self.client.get(reverse("requests:detail", args=[self.item.id]))
        form_count = detail.content.decode().count("<form method=\"post\"")
        token_count = detail.content.decode().count("csrfmiddlewaretoken")
        self.assertGreaterEqual(form_count, 4)  # sign out, assign, resolve, comment
        self.assertGreaterEqual(token_count, form_count)

    def test_successful_create_redirects_so_a_refresh_does_not_duplicate(self):
        self.client.force_login(self.owner)
        data = {
            "category": self.category.id, "title": "Refresh test request",
            "description": "x", "location": "x", "priority": "LOW",
        }
        response = self.client.post(reverse("requests:create"), data)
        self.assertEqual(response.status_code, 302)
        created = ServiceRequest.objects.get(title="Refresh test request")
        # The browser now re-requests the redirect target with GET; reloading it creates nothing.
        for _ in range(2):
            self.client.get(response.url)
        self.assertEqual(ServiceRequest.objects.filter(title="Refresh test request").count(), 1)
        self.assertEqual(response.url, reverse("requests:detail", args=[created.id]))
