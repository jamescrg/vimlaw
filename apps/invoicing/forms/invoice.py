from datetime import datetime, timedelta

from django import forms

from apps.invoicing.models import Invoice


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            "matter",
            "date_limit",
            "date_issued",
            "message",
            "comment",
            "show_comp",
            "discount",
        ]
        widgets = {
            "matter": forms.Select(attrs={"required": True}),
            "date_issued": forms.DateInput(attrs={"type": "date"}),
            "date_limit": forms.DateInput(attrs={"type": "date"}),
            "message": forms.Textarea(attrs={"rows": 3}),
            "comment": forms.Textarea(attrs={"rows": 3}),
            "discount": forms.TextInput(attrs={"class": "discount"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        today = datetime.now().date()

        first_day_of_current_month = today.replace(day=1)

        last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)

        self.fields["date_issued"].initial = today
        self.fields["date_issued"].label = "Issue Date"
        self.fields["show_comp"].initial = True

        self.fields["date_limit"].initial = last_day_of_previous_month
        self.fields["date_limit"].label = "Limit Date "
