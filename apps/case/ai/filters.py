import django_filters
from django.db.models import Q

from .models import Conversation


class ConversationFilter(django_filters.FilterSet):
    q = django_filters.CharFilter(method="filter_keyword", label="Keyword")
    participant = django_filters.NumberFilter(
        method="filter_participant", label="Participant"
    )
    order_by = django_filters.OrderingFilter(
        fields=[
            ("title", "title"),
            ("created_at", "created_at"),
            ("last_activity", "last_activity"),
        ],
        label="Order By",
    )

    def filter_keyword(self, queryset, name, value):
        """Match the title or any message body."""
        return queryset.filter(
            Q(title__icontains=value) | Q(messages__content__icontains=value)
        ).distinct()

    def filter_participant(self, queryset, name, value):
        """Conversations the given user has sent a message in."""
        return queryset.filter(messages__user_id=value).distinct()

    class Meta:
        model = Conversation
        fields = ["q", "participant", "order_by"]
