"""Business-rule layer. Views parse HTTP input and choose responses; every change that
touches the database lives here, inside one transaction.atomic boundary per operation.

The can_* predicates are shared by the services (server-side enforcement) and by the
views/templates (what to show), so the UI and the server permission checks cannot drift.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Comment, ServiceRequest, WorkOrder

COMPLETED_STATUSES = {ServiceRequest.Status.RESOLVED, ServiceRequest.Status.CLOSED}


# --- Permission predicates (pure functions, no queries) -----------------------------------

def can_edit_request(*, actor, item):
    """Owner while the request is open, or any staff member."""
    return actor.is_staff or (actor.pk == item.requester_id and item.status == ServiceRequest.Status.OPEN)


def can_assign_request(*, actor):
    return actor.is_staff


def can_resolve_request(*, actor, work_order):
    """The assigned technician, or any staff member."""
    return actor.is_staff or (work_order is not None and work_order.technician_id == actor.pk)


# --- Create / update / comment (Step D1) ---------------------------------------------------

@transaction.atomic
def service_request_create(*, requester, category, title, description, location, priority):
    item = ServiceRequest(
        requester=requester, category=category, title=title,
        description=description, location=location, priority=priority,
    )
    item.full_clean()
    item.save()
    return item


@transaction.atomic
def service_request_update(*, item, actor, category, title, description, location, priority):
    locked = ServiceRequest.objects.select_for_update().get(id=item.id)
    if actor != locked.requester and not actor.is_staff:
        raise PermissionDenied("You cannot edit this request.")
    if locked.status != ServiceRequest.Status.OPEN and not actor.is_staff:
        raise ValidationError("Only an open request can be edited.")
    locked.category, locked.title = category, title
    locked.description, locked.location, locked.priority = description, location, priority
    locked.full_clean()
    locked.save(update_fields=[
        "category", "title", "description", "location", "priority", "updated_at"
    ])
    return locked


@transaction.atomic
def comment_create(*, item, author, body):
    comment = Comment(service_request=item, author=author, body=body)
    comment.full_clean()
    comment.save()
    return comment


# --- Assignment and resolution (Step D2) ---------------------------------------------------

@transaction.atomic
def service_request_assign(*, item, technician, actor):
    if not can_assign_request(actor=actor):
        raise PermissionDenied("Staff access is required.")
    if not (technician.is_staff and technician.is_active):
        raise ValidationError("The technician must be an active staff member.")
    locked = ServiceRequest.objects.select_for_update().get(id=item.id)
    if locked.status in COMPLETED_STATUSES:
        raise ValidationError("A completed request cannot be assigned.")
    # Both writes below succeed or fail together: WorkOrder row + request status.
    work_order, _ = WorkOrder.objects.update_or_create(
        service_request=locked, defaults={"technician": technician}
    )
    locked.status = ServiceRequest.Status.ASSIGNED
    locked.full_clean()
    locked.save(update_fields=["status", "updated_at"])
    return work_order


@transaction.atomic
def service_request_resolve(*, item, actor, work_notes):
    locked = ServiceRequest.objects.select_for_update().get(id=item.id)
    work_order = WorkOrder.objects.select_for_update().filter(service_request=locked).first()
    # Authorise first, so a caller who may not resolve learns nothing about assignment state.
    if not can_resolve_request(actor=actor, work_order=work_order):
        raise PermissionDenied("Only the assigned technician or staff may resolve.")
    if work_order is None:
        raise ValidationError("Assign a technician before resolving.")
    if locked.status in COMPLETED_STATUSES:
        raise ValidationError("This request is already completed.")
    notes = work_notes.strip()
    if not notes:
        raise ValidationError("Work notes are required to resolve a request.")
    now = timezone.now()
    work_order.work_notes = notes
    work_order.completed_at = now
    work_order.full_clean()
    work_order.save(update_fields=["work_notes", "completed_at"])
    locked.status = ServiceRequest.Status.RESOLVED
    locked.resolved_at = now
    locked.full_clean()
    locked.save(update_fields=["status", "resolved_at", "updated_at"])
    return locked
