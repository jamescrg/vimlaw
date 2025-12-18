import django_filters
from django.db.models import Q

from config.helpers import MultipleOrderingFilter

from .models import Note

IMPORTANCE_CHOICES = tuple((i, f"Importance {i}") for i in range(1, 11))


class NotesFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method="filter_keyword", label="Keyword")
    category = django_filters.ChoiceFilter(
        field_name="category",
        choices=Note.CATEGORY_CHOICES,
        label="Category",
        empty_label="All Categories",
    )
    topic = django_filters.CharFilter(field_name="topic", lookup_expr="exact")
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
            ("title", "title"),
            ("topic", "topic"),
            ("importance", "importance"),
            ("viewed_at", "viewed_at"),
        ],
        field_labels={
            "updated_at": "Last Updated",
            "created_at": "Created",
            "title": "Title",
            "topic": "Topic",
            "importance": "Importance",
            "viewed_at": "Viewed",
        },
        label="Order By",
    )

    class Meta:
        model = Note
        fields = ["keyword", "category", "importance", "order_by"]

    def filter_keyword(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(title__icontains=value) | Q(content__icontains=value)
            )
        return queryset
