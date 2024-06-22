from django import forms

from .models import Task


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = (
            "matter",
            "description",
            "status",
            "date_due",
            "user",
            "priority",
        )
        STATUSES = (
            ("Pending", "Pending"),
            ("Complete", "Complete"),
        )
        labels = {
            "description": "Task",
        }
        widgets = {
            "description": forms.TextInput(attrs={"autofocus": "autofocus"}),
            "status": forms.Select(choices=STATUSES),
            "date_due": forms.DateInput(attrs={"type": "date"}),
        }
