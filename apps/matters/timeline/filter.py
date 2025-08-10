import django_filters
from django.db.models import Q

from .models import Fact


class TimelineFilter(django_filters.FilterSet):
    date_start = django_filters.DateFilter(
        field_name="date", lookup_expr="gte", label="Start Date"
    )
    date_end = django_filters.DateFilter(
        field_name="date", lookup_expr="lte", label="End Date"
    )
    keyword = django_filters.CharFilter(method="filter_keyword", label="Keyword")

    class Meta:
        model = Fact
        fields = ["date_start", "date_end", "keyword"]

    def filter_keyword(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(description__icontains=value) | Q(citations__icontains=value)
            )
        return queryset
