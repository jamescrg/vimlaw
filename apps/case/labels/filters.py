import django_filters

from apps.case.models import Label
from apps.matters.models import Matter


class LabelsFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains", label="Name")
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(labels__isnull=False)
        .distinct()
        .order_by("name"),
        empty_label="All",
    )
    order_by = django_filters.OrderingFilter(
        fields=[
            ("name", "name"),
            ("matter__name", "matter"),
        ]
    )

    class Meta:
        model = Label
        fields = ["name", "matter", "order_by"]
