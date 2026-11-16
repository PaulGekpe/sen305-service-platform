from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import AssignmentForm, CommentForm, ResolutionForm, ServiceRequestForm
from .models import ServiceRequest
from .selectors import (
    comment_list,
    service_request_filter,
    service_request_get,
    service_request_status_counts,
    work_order_get,
)
from .services import (
    COMPLETED_STATUSES,
    can_assign_request,
    can_edit_request,
    can_resolve_request,
    comment_create,
    service_request_assign,
    service_request_create,
    service_request_resolve,
    service_request_update,
)

PAGE_SIZE = 10


# --- helpers --------------------------------------------------------------------------------

def _get_visible_or_404(user, request_id):
    """Load through the selector so another requester's id is indistinguishable from a missing one."""
    try:
        return service_request_get(user=user, request_id=request_id)
    except ServiceRequest.DoesNotExist as exc:
        raise Http404("Service request not found.") from exc


def _filter_querystring(*, status, query):
    """Reusable query string that keeps q and status while the page number changes (Task 3)."""
    params = {}
    if query:
        params["q"] = query
    if status:
        params["status"] = status
    return urlencode(params)


def _flash_validation_error(request, exc):
    for message in exc.messages:
        messages.error(request, message)


def _flash_form_errors(request, form):
    for field_name, errors in form.errors.items():
        label = form.fields[field_name].label or field_name.replace("_", " ").capitalize()
        for error in errors:
            messages.error(request, f"{label}: {error}")


# --- read views (Step E1) ---------------------------------------------------------------------

@login_required
def request_list(request):
    status = request.GET.get("status", "").strip()
    if status not in ServiceRequest.Status.values:
        status = ""
    query = request.GET.get("q", "").strip()
    queryset = service_request_filter(user=request.user, status=status, query=query)
    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "requests_app/request_list.html", {
        "page_obj": page_obj,
        "status_choices": ServiceRequest.Status.choices,
        "selected_status": status,
        "query": query,
        "filter_qs": _filter_querystring(status=status, query=query),
        "summary": service_request_status_counts(user=request.user),
    })


@login_required
def request_detail(request, request_id):
    item = _get_visible_or_404(request.user, request_id)
    work_order = work_order_get(item=item)
    open_for_work = item.status not in COMPLETED_STATUSES
    can_assign = can_assign_request(actor=request.user) and open_for_work
    # Show the resolve form only to someone the server would accept, and only when there is
    # a work order to complete.
    can_resolve = (
        work_order is not None
        and open_for_work
        and can_resolve_request(actor=request.user, work_order=work_order)
    )
    return render(request, "requests_app/request_detail.html", {
        "item": item,
        "work_order": work_order,
        "comments": comment_list(user=request.user, item=item),
        "comment_form": CommentForm(),
        "can_edit": can_edit_request(actor=request.user, item=item),
        "can_assign": can_assign,
        "can_resolve": can_resolve,
        "assignment_form": AssignmentForm() if can_assign else None,
        "resolution_form": ResolutionForm() if can_resolve else None,
    })


# --- create, update, comment (Step E2) ---------------------------------------------------------

@login_required
def request_create(request):
    form = ServiceRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item = service_request_create(requester=request.user, **form.cleaned_data)
        messages.success(request, "Service request created.")
        return redirect("requests:detail", request_id=item.id)
    return render(request, "requests_app/request_form.html", {"form": form, "mode": "Create"})


@login_required
def request_update(request, request_id):
    item = _get_visible_or_404(request.user, request_id)
    form = ServiceRequestForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        try:
            item = service_request_update(item=item, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Service request updated.")
            return redirect("requests:detail", request_id=item.id)
    return render(request, "requests_app/request_form.html", {
        "form": form, "mode": "Update", "item": item
    })


@require_POST
@login_required
def comment_add(request, request_id):
    item = _get_visible_or_404(request.user, request_id)
    form = CommentForm(request.POST)
    if form.is_valid():
        comment_create(item=item, author=request.user, **form.cleaned_data)
        messages.success(request, "Comment added.")
    else:
        messages.error(request, "Enter at least 3 characters.")
    return redirect("requests:detail", request_id=item.id)


# --- assignment and resolution (Part M, Tasks 1 and 2) -----------------------------------------

@require_POST
@login_required
def request_assign(request, request_id):
    # Check the role before touching the database: every non-staff caller gets the same 403.
    if not can_assign_request(actor=request.user):
        raise PermissionDenied("Staff access is required.")
    item = _get_visible_or_404(request.user, request_id)
    form = AssignmentForm(request.POST)
    if form.is_valid():
        try:
            service_request_assign(
                item=item, technician=form.cleaned_data["technician"], actor=request.user
            )
        except ValidationError as exc:
            _flash_validation_error(request, exc)
        else:
            messages.success(request, "Technician assigned.")
    else:
        _flash_form_errors(request, form)
    return redirect("requests:detail", request_id=item.id)


@require_POST
@login_required
def request_resolve(request, request_id):
    item = _get_visible_or_404(request.user, request_id)
    # Same rule as the service (and as the template): reject early so an unauthorised caller
    # always gets 403, whatever they post. The service re-checks inside its transaction.
    if not can_resolve_request(actor=request.user, work_order=work_order_get(item=item)):
        raise PermissionDenied("Only the assigned technician or staff may resolve.")
    # The view never creates or edits WorkOrder rows; it hands the validated input to the service.
    form = ResolutionForm(request.POST)
    if form.is_valid():
        try:
            service_request_resolve(item=item, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            _flash_validation_error(request, exc)
        else:
            messages.success(request, "Request resolved.")
    else:
        _flash_form_errors(request, form)
    return redirect("requests:detail", request_id=item.id)
