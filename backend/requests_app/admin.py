from django.contrib import admin

from .models import Category, Comment, ServiceRequest, WorkOrder

admin.site.register(Category)
admin.site.register(ServiceRequest)
admin.site.register(WorkOrder)
admin.site.register(Comment)
