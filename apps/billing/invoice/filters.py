import django_filters

from apps.billing.invoice.models import INVOICE_STATUS, Invoice
from apps.matters.models import Matter


class InvoiceFilter(django_filters.FilterSet):
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(invoice__isnull=False).distinct(),
        empty_label="All",
    )
    status = django_filters.ChoiceFilter(choices=INVOICE_STATUS, empty_label="All")
    date_issued = django_filters.DateFromToRangeFilter(
        widget=django_filters.widgets.RangeWidget(attrs={"type": "date"})
    )

    class Meta:
        model = Invoice
        fields = ["matter", "status", "date_issued"]
