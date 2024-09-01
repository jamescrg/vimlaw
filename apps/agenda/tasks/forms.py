from django import forms

from apps.agenda.tasks.models import Task


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = (
            "description",
            "matter",
            "date_due",
            "status",
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
            "description": forms.TextInput(
                attrs={"autofocus": "autofocus", "required": "required"}
            ),
            "matter": forms.Select(attrs={"required": "required"}),
            "status": forms.Select(choices=STATUSES),
            "date_due": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["date_due"].initial = None
