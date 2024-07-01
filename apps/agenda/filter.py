from datetime import date


class Filter:
    values = {
        "date_from": None,
        "date_to": None,
        "matter": None,
        "user": None,
        "status": "Pending",
        "order_field": "matter",
        "order_direction": "ascending",
    }

    quick_filters = {
        "current_user": {
            "date_from": None,
            "date_to": None,
            "matter": None,
            "user": None,
            "status": "Pending",
            "order_field": "matter",
            "order_direction": "ascending",
        },
        "all": {
            "date_from": None,
            "date_to": None,
            "matter": None,
            "user": None,
            "status": "Pending",
            "order_field": "matter",
            "order_direction": "ascending",
        },
        "paralegal": {
            "date_from": None,
            "date_to": None,
            "matter": None,
            "user": 4,
            "status": "Pending",
            "order_field": "matter",
            "order_direction": "ascending",
        },
    }

    def __init__(self, request):
        # set today's date on relevant filters
        # this prevents the current date from lagging back to when the gunicorn
        # server first started and the Filter class was first initialized
        # self.quick_filters["today"]["date_to"] = date.today(
        # ).strftime("%Y-%m-%d")

        # set the current user for the "mine" quickfilter
        self.quick_filters["current_user"]["user"] = request.user.id

        # load save session data
        agenda_filter = request.session.get("agenda_filter")
        if agenda_filter:
            for key, value in agenda_filter.items():
                self.values[key] = value

        # otherwise, initialize session
        else:
            request.session["agenda_filter"] = {}

    def update(self, request):
        for key in self.values.keys():
            request.session["agenda_filter"][key] = request.POST[key]
        request.session.modified = True

    def set_quick_filter(self, request, quick_filter):
        request.session["agenda_filter"] = self.quick_filters[quick_filter]
        request.session.modified = True

    def sort(self, request, new_field):
        saved_field = self.values["order_field"]
        saved_direction = self.values["order_direction"]

        if saved_field == new_field:
            if saved_direction == "ascending":
                new_direction = "descending"
            else:
                new_direction = "ascending"
        else:
            new_direction = "ascending"

        request.session["agenda_filter"]["order_field"] = new_field
        request.session["agenda_filter"]["order_direction"] = new_direction
        request.session.modified = True
