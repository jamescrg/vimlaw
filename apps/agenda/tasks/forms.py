from datetime import datetime

from django import forms

from apps.agenda.tasks.models import Task


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = (
            "matter",
            "description",
            "status",
            "date_due",
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current_date = datetime.now().date()
        self.fields["date_due"].initial = current_date
