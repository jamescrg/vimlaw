from datetime import datetime, timedelta

from django import forms

from apps.invoicing.models import Invoice


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            "matter",
            "date_from",
            "date_to",
            "date_issued",
            "message",
            "comment",
            "show_comp",
            "discount",
        ]
        widgets = {
            "matter": forms.Select(attrs={"required": True}),
            "date_from": forms.DateInput(attrs={"type": "date"}),
            "date_to": forms.DateInput(attrs={"type": "date"}),
            "date_issued": forms.DateInput(attrs={"type": "date"}),
            "message": forms.Textarea(attrs={"rows": 3}),
            "comment": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        today = datetime.now().date()

        first_day_of_current_month = today.replace(day=1)

        last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)
        first_day_of_previous_month = last_day_of_previous_month.replace(day=1)

        self.fields["date_issued"].initial = today
        self.fields["show_comp"].initial = True

        self.fields["date_from"].initial = first_day_of_previous_month
        self.fields["date_to"].initial = last_day_of_previous_month
