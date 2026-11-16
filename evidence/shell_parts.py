"""Django-shell snippets from the Lab 4 practical note, kept verbatim so they can be run
non-interactively by run_evidence.py (python manage.py shell < snippet)."""

A3_ACCOUNTS = '''\
from django.contrib.auth import get_user_model
User = get_user_model()
owner = User.objects.create_user("requester1", password="LabPass123!")
other = User.objects.create_user("requester2", password="LabPass123!")
staff = User.objects.create_user("technician1", password="LabPass123!", is_staff=True)
'''

B2_VALIDATION = '''\
from requests_app.forms import ServiceRequestForm
bad = ServiceRequestForm(data={
    "category": "", "title": "PC", "description": "",
    "location": "", "priority": "HIGH",
})
print(bad.is_valid())
print(bad.errors.as_json())
'''

C2_VISIBILITY = '''\
from django.contrib.auth import get_user_model
from requests_app.models import Category, ServiceRequest
from requests_app.selectors import service_request_list
User = get_user_model()
owner = User.objects.get(username="requester1")
other = User.objects.get(username="requester2")
staff = User.objects.get(username="technician1")
category, _ = Category.objects.get_or_create(name="ICT Support")
item = ServiceRequest.objects.create(
    requester=owner, category=category,
    title="Laboratory computer cannot start",
    description="The workstation shows no power indicator.",
    location="Software Laboratory", priority="HIGH",
)
print(service_request_list(user=owner).filter(id=item.id).exists())
print(service_request_list(user=other).filter(id=item.id).exists())
print(service_request_list(user=staff).filter(id=item.id).exists())
'''

J_DB_VERIFICATION = '''\
from requests_app.models import Comment, ServiceRequest
print(ServiceRequest.objects.values("id", "requester__username", "title", "status"))
print(Comment.objects.values("service_request_id", "author__username", "body"))
'''

K_ROLLBACK = '''\
from django.contrib.auth import get_user_model
from django.db import transaction
from requests_app.models import ServiceRequest, WorkOrder
User = get_user_model()
item = ServiceRequest.objects.filter(status="OPEN").first()
technician = User.objects.get(username="technician1")
before_status = item.status
before_count = WorkOrder.objects.filter(service_request=item).count()
try:
    with transaction.atomic():
        WorkOrder.objects.create(service_request=item, technician=technician)
        item.status = "ASSIGNED"
        item.save(update_fields=["status", "updated_at"])
        raise RuntimeError("Deliberate failure for rollback test")
except RuntimeError as exc:
    print(exc)
item.refresh_from_db()
after_count = WorkOrder.objects.filter(service_request=item).count()
print("status:", before_status, "->", item.status)
print("work orders:", before_count, "->", after_count)
'''

# Extra data for the Part M screenshots (Task 3 needs at least 12 matching records).
SEED_PRINTER_REQUESTS = '''\
from django.contrib.auth import get_user_model
from requests_app.models import Category, ServiceRequest
User = get_user_model()
owner = User.objects.get(username="requester1")
cat = Category.objects.get(name="ICT Support")
for i in range(1, 15):
    ServiceRequest.objects.create(
        requester=owner, category=cat, title=f"Printer jam in office {i:02d}",
        description="Paper keeps jamming at the rear tray.", location=f"Office {i:02d}",
        priority="MEDIUM",
    )
print("seeded printer requests:", ServiceRequest.objects.filter(title__startswith="Printer jam").count())
'''

TASK_DB_VERIFICATION = '''\
from requests_app.models import ServiceRequest, WorkOrder
for item in ServiceRequest.objects.filter(status="RESOLVED"):
    wo = item.work_order
    print("request:", item.title)
    print("  status      :", item.status)
    print("  resolved_at :", item.resolved_at)
    print("  technician  :", wo.technician.username)
    print("  work_notes  :", wo.work_notes)
    print("  completed_at:", wo.completed_at)
    print("  resolved_at == completed_at:", item.resolved_at == wo.completed_at)
'''
