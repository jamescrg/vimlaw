import django_filters
from django.db.models import Q

from apps.case.models import Label, Note
from config.helpers import MultipleOrderingFilter

IMPORTANCE_CHOICES = tuple((i, f"Importance {i}") for i in range(1, 11))


class NotesFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="Keyword")
    label = django_filters.ModelChoiceFilter(
        method="filter_label",
        queryset=Label.objects.none(),
        empty_label="All Labels",
        label="Label",
    )
    category = django_filters.ChoiceFilter(
        field_name="category",
        choices=Note.CATEGORY_CHOICES,
        label="Category",
        empty_label="All Categories",
    )
    importance = django_filters.ChoiceFilter(
        field_name="importance",
        choices=IMPORTANCE_CHOICES,
        lookup_expr="lte",
        label="Importance",
        empty_label="All",
    )
    order_by = MultipleOrderingFilter(
        fields=[
            ("updated_at", "updated_at"),
            ("created_at", "created_at"),
            ("date", "date"),
            ("title", "title"),
            ("importance", "importance"),
            ("viewed_at", "viewed_at"),
        ],
        field_labels={
            "updated_at": "Last Updated",
            "created_at": "Created",
            "date": "Date",
            "title": "Title",
            "importance": "Importance",
            "viewed_at": "Viewed",
        },
        label="Order By",
    )

    class Meta:
        model = Note
        fields = ["keyword", "label", "category", "importance", "order_by"]

    def __init__(self, *args, matter=None, **kwargs):
        super().__init__(*args, **kwargs)
        if matter:
            self.filters["label"].queryset = Label.objects.filter(
                Q(matter=matter) | Q(matter__isnull=True)
            ).order_by("name")

    def filter_keyword(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(title__icontains=value) | Q(content__icontains=value)
            )
        return queryset

    def filter_label(self, queryset, name, value):
        if value:
            return queryset.filter(labels=value)
        return queryset
