from django import forms
from django.contrib.auth import get_user_model

from .models import Category, Comment, ServiceRequest


class ServiceRequestForm(forms.ModelForm):
    """Create/edit form. Exposes only safe user-editable fields.

    requester, status and resolved_at are deliberately excluded: they are set by
    the server (request.user and the workflow services), never by posted data.
    """

    class Meta:
        model = ServiceRequest
        fields = ["category", "title", "description", "location", "priority"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(is_active=True)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if len(title) < 8:
            raise forms.ValidationError("Use at least 8 characters.")
        return title


class CommentForm(forms.ModelForm):
    """Comment form. author and is_internal are excluded on purpose."""

    class Meta:
        model = Comment
        fields = ["body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 3})}

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if len(body) < 3:
            raise forms.ValidationError("Enter a meaningful comment.")
        return body


class AssignmentForm(forms.Form):
    """Staff-only: choose the technician for a request (Part M, Task 1)."""

    technician = forms.ModelChoiceField(queryset=get_user_model().objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user_model = get_user_model()
        field = self.fields["technician"]
        # Only active staff accounts can be technicians.
        field.queryset = user_model.objects.filter(is_staff=True, is_active=True).order_by("username")
        field.label_from_instance = lambda user: user.get_full_name() or user.get_username()
        field.empty_label = "Select a technician"
        field.widget.attrs.setdefault("class", "form-control")


class ResolutionForm(forms.Form):
    """Technician or staff: record the work done and resolve (Part M, Task 2)."""

    work_notes = forms.CharField(
        label="Work notes",
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        help_text="Describe what was done to fix the problem.",
    )

    def clean_work_notes(self):
        notes = self.cleaned_data["work_notes"].strip()
        if not notes:
            raise forms.ValidationError("Work notes are required to resolve a request.")
        return notes
