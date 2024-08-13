import django_filters

from apps.billing.models_payment import PAYMENT_METHOD_CHOICES, Payment
from apps.matters.models import Matter


class PaymentFilter(django_filters.FilterSet):
    payment_method = django_filters.ChoiceFilter(
        choices=PAYMENT_METHOD_CHOICES, empty_label="All"
    )
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(payment__isnull=False).distinct(),
        empty_label="All",
    )
    date = django_filters.DateFromToRangeFilter(
        widget=django_filters.widgets.RangeWidget(attrs={"type": "date"})
    )

    class Meta:
        model = Payment
        fields = ["payment_method", "matter", "date"]
