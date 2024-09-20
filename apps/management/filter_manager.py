from typing import Any, Dict

from django.http import HttpRequest


class FilterManager:
    def __init__(self, request: HttpRequest, filter_class: Any, session_key: str):
        self.request = request
        self.filter_class = filter_class
        self.session_key = session_key

        self.quick_filters = {
            "events-pending": {
                "status": "Pending",
                "matter": None,
                "date_min": "",
                "date_max": "",
                "party": None,
                "order_by": "date",
            },
        }

    def get_filter_data(self) -> Dict[str, Any]:
        """
        Get the filter data from the session, or default to an empty dictionary
        """
        return self.request.session.get(self.session_key, {})

    def set_filter_data(self, data: Dict[str, Any]) -> None:
        """
        Set the filter data for the given session key in the session
        """
        self.request.session[self.session_key] = data
        self.request.session.modified = True

    def apply_quick_filter(self, quick_filter: str):
        """
        Apply a predefined quick filter to the filter data
        """
        if quick_filter in self.quick_filters:
            self.set_filter_data(self.quick_filters[quick_filter])

    def get_filter(self, queryset):
        """
        Get the filter instance for the given queryset
        """
        filter_data = self.get_filter_data()

        return self.filter_class(filter_data, queryset=queryset)

    def process_filter(self) -> bool:
        """
        Return a boolean indicating whether the filter data was processed or not
        """
        if self.request.method == "POST":
            self.set_filter_data(self.request.POST)

            return True

        return False
