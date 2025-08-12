from datetime import datetime

from django import forms

from apps.invoicing.payments.models import Payment
from config.settings import CustomFormRendererCompact


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = [
            "matter",
            "date",
            "payment_method",
            "amount",
            "detail",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "matter": forms.Select(attrs={"class": ""}),
            "payment_method": forms.Select(),
            "amount": forms.TextInput(attrs={"class": ""}),
            "detail": forms.TextInput(attrs={"required": False, "class": "span2"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renderer = CustomFormRendererCompact()

        today = datetime.now().date()

        self.fields["date"].initial = today
        self.fields["payment_method"].initial = "CARD"
