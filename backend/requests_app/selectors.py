"""Read/query layer. Every query that returns requests goes through here so that
row-level visibility (requesters see their own rows, staff see all) cannot be forgotten.
"""

from django.db.models import Count, Q

from .models import Comment, ServiceRequest, WorkOrder


def _visible_requests(*, user):
    """Base queryset limited to the rows this user may see."""
    queryset = ServiceRequest.objects.all()
    return queryset if user.is_staff else queryset.filter(requester=user)


def service_request_list(*, user):
    # Requesters must not learn about staff-only (internal) comments, not even the count.
    if user.is_staff:
        comment_count = Count("comments")
    else:
        comment_count = Count("comments", filter=Q(comments__is_internal=False))
    return (
        _visible_requests(user=user)
        .select_related("requester", "category")
        .annotate(comment_count=comment_count)
        .order_by("-created_at")
    )


def service_request_filter(*, user, status="", query=""):
    queryset = service_request_list(user=user)
    if status:
        queryset = queryset.filter(status=status)
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(location__icontains=query)
        )
    return queryset


def service_request_get(*, user, request_id):
    return service_request_list(user=user).get(id=request_id)


def service_request_status_counts(*, user):
    """Open / Assigned / Resolved totals over the requests this user can see (Part M, Task 4).

    One aggregate query on the visible rows. It deliberately uses the un-annotated
    visibility queryset so the counts are never inflated by the comments join.
    """
    Status = ServiceRequest.Status
    return _visible_requests(user=user).aggregate(
        open=Count("id", filter=Q(status=Status.OPEN)),
        assigned=Count("id", filter=Q(status=Status.ASSIGNED)),
        resolved=Count("id", filter=Q(status=Status.RESOLVED)),
    )


def comment_list(*, user, item):
    """Comments on a request the caller can already see; internal notes are staff-only."""
    queryset = Comment.objects.filter(service_request=item).select_related("author")
    if not user.is_staff:
        queryset = queryset.filter(is_internal=False)
    return queryset.order_by("created_at")


def work_order_get(*, item):
    return WorkOrder.objects.select_related("technician").filter(service_request=item).first()
