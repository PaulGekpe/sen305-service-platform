"""Part M, Task 5: assignment, resolution, atomicity, filtered pagination and summary counts."""

from unittest import mock

from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.urls import reverse

from requests_app.models import ServiceRequest, WorkOrder
from requests_app.selectors import service_request_list, service_request_status_counts
from requests_app.services import service_request_assign, service_request_resolve

from .base import WorkflowTestCase


def message_texts(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class AssignmentTests(WorkflowTestCase):
    def assign_url(self):
        return reverse("requests:assign", args=[self.item.id])

    def test_non_staff_assignment_returns_403_and_creates_no_work_order(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.assign_url(), {"technician": self.tech.id})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(WorkOrder.objects.count(), 0)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.OPEN)

    def test_staff_assignment_creates_one_work_order_and_sets_assigned(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.assign_url(), {"technician": self.tech.id})
        self.assertRedirects(response, reverse("requests:detail", args=[self.item.id]))
        self.assertEqual(WorkOrder.objects.filter(service_request=self.item).count(), 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.ASSIGNED)
        self.assertEqual(self.item.work_order.technician, self.tech)

    def test_reassignment_updates_the_same_work_order(self):
        self.client.force_login(self.staff)
        self.client.post(self.assign_url(), {"technician": self.tech.id})
        self.client.post(self.assign_url(), {"technician": self.staff.id})
        self.assertEqual(WorkOrder.objects.filter(service_request=self.item).count(), 1)
        self.assertEqual(self.item.work_order.technician, self.staff)

    def test_assignment_form_rejects_a_non_staff_technician(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.assign_url(), {"technician": self.other.id}, follow=True)
        self.assertEqual(WorkOrder.objects.count(), 0)
        self.assertTrue(any("Select a valid choice" in m for m in message_texts(response)))

    def test_service_rejects_a_non_staff_technician_even_without_the_form(self):
        with self.assertRaises(ValidationError):
            service_request_assign(item=self.item, technician=self.other, actor=self.staff)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_completed_request_cannot_be_assigned(self):
        ServiceRequest.objects.filter(id=self.item.id).update(status=ServiceRequest.Status.RESOLVED)
        self.client.force_login(self.staff)
        response = self.client.post(self.assign_url(), {"technician": self.tech.id}, follow=True)
        self.assertEqual(WorkOrder.objects.count(), 0)
        self.assertIn("A completed request cannot be assigned.", message_texts(response))

    def test_assignment_is_atomic(self):
        """If the status write fails, the WorkOrder row created a moment earlier is rolled back."""
        with mock.patch.object(ServiceRequest, "save", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                service_request_assign(item=self.item, technician=self.tech, actor=self.staff)
        self.assertEqual(WorkOrder.objects.filter(service_request=self.item).count(), 0)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.OPEN)


class ResolutionTests(WorkflowTestCase):
    def resolve_url(self):
        return reverse("requests:resolve", args=[self.item.id])

    def assign(self):
        service_request_assign(item=self.item, technician=self.tech, actor=self.staff)

    def test_resolution_without_assignment_leaves_request_unchanged(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.resolve_url(), {"work_notes": "Replaced the cable."}, follow=True)
        self.assertIn("Assign a technician before resolving.", message_texts(response))
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.OPEN)
        self.assertIsNone(self.item.resolved_at)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_assigned_technician_resolution_changes_both_models(self):
        self.assign()
        self.client.force_login(self.tech)
        response = self.client.post(self.resolve_url(), {"work_notes": "  Replaced the HDMI cable.  "})
        self.assertRedirects(response, reverse("requests:detail", args=[self.item.id]))
        self.item.refresh_from_db()
        order = self.item.work_order
        self.assertEqual(self.item.status, ServiceRequest.Status.RESOLVED)
        self.assertIsNotNone(self.item.resolved_at)
        self.assertEqual(order.work_notes, "Replaced the HDMI cable.")
        self.assertIsNotNone(order.completed_at)
        self.assertEqual(order.completed_at, self.item.resolved_at)

    def test_resolution_requires_work_notes(self):
        self.assign()
        self.client.force_login(self.tech)
        response = self.client.post(self.resolve_url(), {"work_notes": "   "}, follow=True)
        self.assertTrue(any("Work notes" in m for m in message_texts(response)))
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.ASSIGNED)
        self.assertIsNone(self.item.work_order.completed_at)

    def test_requester_who_is_not_staff_cannot_resolve(self):
        self.assign()
        self.client.force_login(self.owner)
        response = self.client.post(self.resolve_url(), {"work_notes": "I fixed it myself."})
        self.assertEqual(response.status_code, 403)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.ASSIGNED)

    def test_unauthorised_caller_gets_403_even_with_invalid_input(self):
        self.assign()
        self.client.force_login(self.owner)
        response = self.client.post(self.resolve_url(), {"work_notes": ""})
        self.assertEqual(response.status_code, 403)

    def test_a_resolved_request_cannot_be_resolved_twice(self):
        self.assign()
        service_request_resolve(item=self.item, actor=self.tech, work_notes="First fix.")
        self.item.refresh_from_db()
        first_resolved_at = self.item.resolved_at
        with self.assertRaises(ValidationError):
            service_request_resolve(item=self.item, actor=self.tech, work_notes="Second fix.")
        self.item.refresh_from_db()
        self.assertEqual(self.item.resolved_at, first_resolved_at)
        self.assertEqual(self.item.work_order.work_notes, "First fix.")

    def test_resolution_is_atomic(self):
        """If the request update fails, the WorkOrder completion written first is rolled back."""
        self.assign()
        with mock.patch.object(ServiceRequest, "save", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                service_request_resolve(item=self.item, actor=self.tech, work_notes="Replaced cable.")
        order = WorkOrder.objects.get(service_request=self.item)
        self.assertIsNone(order.completed_at)
        self.assertEqual(order.work_notes, "")
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.ASSIGNED)
        self.assertIsNone(self.item.resolved_at)


class DetailPageVisibilityTests(WorkflowTestCase):
    """UI visibility and server permission must agree (Part M check table)."""

    def detail(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("requests:detail", args=[self.item.id]))

    def test_assignment_form_is_shown_only_to_staff(self):
        self.assertContains(self.detail(self.staff), reverse("requests:assign", args=[self.item.id]))
        self.assertNotContains(self.detail(self.owner), reverse("requests:assign", args=[self.item.id]))

    def test_resolve_form_needs_a_work_order_and_the_right_person(self):
        resolve = reverse("requests:resolve", args=[self.item.id])
        self.assertNotContains(self.detail(self.staff), resolve)  # nothing assigned yet
        service_request_assign(item=self.item, technician=self.tech, actor=self.staff)
        self.assertContains(self.detail(self.tech), resolve)
        self.assertContains(self.detail(self.staff), resolve)
        self.assertNotContains(self.detail(self.owner), resolve)

    def test_resolved_request_shows_work_notes_and_hides_the_forms(self):
        service_request_assign(item=self.item, technician=self.tech, actor=self.staff)
        service_request_resolve(item=self.item, actor=self.tech, work_notes="Replaced the HDMI cable.")
        response = self.detail(self.staff)
        self.assertContains(response, "Replaced the HDMI cable.")
        self.assertNotContains(response, reverse("requests:resolve", args=[self.item.id]))
        self.assertNotContains(response, reverse("requests:assign", args=[self.item.id]))


class FilteredPaginationTests(WorkflowTestCase):
    def setUp(self):
        super().setUp()
        for i in range(25):
            self.make_request(self.owner, f"Printer jam number {i:02d}")
        for i in range(3):
            self.make_request(self.owner, f"Projector fault number {i:02d}")
        ServiceRequest.objects.filter(title__startswith="Printer jam number 0").update(
            status=ServiceRequest.Status.ASSIGNED
        )

    def test_page_two_keeps_search_text_and_status(self):
        self.client.force_login(self.owner)
        # 15 printer requests are still OPEN (numbers 10-24) -> two pages of 10 and 5.
        response = self.client.get(reverse("requests:list"), {"q": "printer", "status": "OPEN", "page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertEqual(response.context["page_obj"].paginator.count, 15)
        self.assertEqual(response.context["filter_qs"], "q=printer&status=OPEN")
        # Both filters are still selected in the form...
        self.assertContains(response, 'value="printer"')
        self.assertContains(response, 'value="OPEN" selected')
        # ...and the Previous link carries both filters while changing only the page.
        self.assertContains(response, 'href="?q=printer&amp;status=OPEN&amp;page=1"')
        self.assertNotContains(response, "Projector fault")

    def test_middle_page_has_previous_and_next_links_with_filters(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("requests:list"), {"q": "number", "page": 2})
        self.assertContains(response, 'href="?q=number&amp;page=1"')
        self.assertContains(response, 'href="?q=number&amp;page=3"')

    def test_without_filters_links_only_carry_the_page(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("requests:list"))
        self.assertContains(response, 'href="?page=2"')

    def test_search_text_is_url_encoded(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("requests:list"), {"q": "printer jam&x=1"})
        self.assertEqual(response.context["filter_qs"], "q=printer+jam%26x%3D1")

    def test_unknown_status_is_ignored(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("requests:list"), {"status": "NOPE"})
        self.assertEqual(response.context["selected_status"], "")
        self.assertEqual(response.context["page_obj"].paginator.count, 29)  # 25 + 3 + the fixture request


class SummaryCountTests(WorkflowTestCase):
    def setUp(self):
        super().setUp()
        Status = ServiceRequest.Status
        # owner: 1 OPEN (self.item) + 1 ASSIGNED + 2 RESOLVED; other: 3 OPEN + 1 ASSIGNED
        self.make_request(self.owner, "Owner assigned request", status=Status.ASSIGNED)
        for i in range(2):
            self.make_request(self.owner, f"Owner resolved request {i}", status=Status.RESOLVED)
        for i in range(3):
            self.make_request(self.other, f"Other open request {i}")
        self.make_request(self.other, "Other assigned request", status=Status.ASSIGNED)

    def test_counts_for_a_requester_cover_only_visible_requests(self):
        self.assertEqual(
            service_request_status_counts(user=self.owner), {"open": 1, "assigned": 1, "resolved": 2}
        )

    def test_counts_for_staff_cover_everything(self):
        self.assertEqual(
            service_request_status_counts(user=self.staff), {"open": 4, "assigned": 2, "resolved": 2}
        )

    def test_counts_are_not_inflated_by_comments(self):
        from requests_app.models import Comment

        for i in range(3):
            Comment.objects.create(service_request=self.item, author=self.owner, body=f"Note {i}")
        self.assertEqual(service_request_status_counts(user=self.owner)["open"], 1)

    def test_list_page_shows_the_counts(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("requests:list"))
        self.assertEqual(response.context["summary"], {"open": 1, "assigned": 1, "resolved": 2})
        self.assertContains(response, "summary-number")


class SelectorVisibilityTests(WorkflowTestCase):
    def test_row_level_visibility(self):
        self.assertTrue(service_request_list(user=self.owner).filter(id=self.item.id).exists())
        self.assertFalse(service_request_list(user=self.other).filter(id=self.item.id).exists())
        self.assertTrue(service_request_list(user=self.staff).filter(id=self.item.id).exists())

    def test_list_uses_a_constant_number_of_queries(self):
        for i in range(8):
            self.make_request(self.owner, f"Extra request number {i}")
        with self.assertNumQueries(2):  # one for the page rows (joined + annotated), one for the count
            from django.core.paginator import Paginator

            page = Paginator(service_request_list(user=self.owner), 10).get_page(1)
            for row in page:
                str(row.requester.username), str(row.category), row.comment_count
