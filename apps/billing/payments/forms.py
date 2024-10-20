from datetime import datetime

from django import forms

from apps.billing.payments.models import Payment


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = [
            "matter",
            "date",
            "payment_method",
            "detail",
            "amount",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "detail": forms.TextInput(attrs={"required": False}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        today = datetime.now().date()

        self.fields["date"].initial = today
        self.fields["payment_method"].initial = "CARD"
