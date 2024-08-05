import logging
from datetime import date

logger = logging.getLogger(__name__)


class Filter:
    values = {
        "show_time": True,
        "show_expenses": True,
        "date_from": None,
        "date_to": None,
        "firm": "Campbell & Brannon",
        "matter": None,
        "user": "All",
        "keyword": "",
        "comp": None,
        "entered": None,
        "invoiced": None,
        "order": "date, descending",
    }

    quick_filters = {
        "today": {
            "date_from": None,
            "date_to": None,
            "firm": "Campbell & Brannon",
            "matter": None,
            "order": "date, descending",
            "keyword": "",
            "comp": None,
            "entered": None,
            "invoiced": None,
        },
        "unbilled": {
            "date_from": None,
            "date_to": None,
            "firm": "Campbell & Brannon",
            "matter": None,
            "order": "date, descending",
            "keyword": "",
            "comp": None,
            "entered": "No",
            "invoiced": "No",
        },
    }

    def __init__(self, request):
        # set today's date on relevant filters
        # this prevents the current date from lagging back to when the gunicorn
        # server first started and the Filter class was first initialized
        self.values["date_from"] = date.today().strftime("%Y-%m-%d")
        self.quick_filters["today"]["date_from"] = date.today().strftime("%Y-%m-%d")

        # load save session data
        activity_filter = request.session.get("activity_filter")
        if activity_filter:
            for key, value in activity_filter.items():
                self.values[key] = value

        # otherwise, initialize session
        else:
            request.session["activity_filter"] = {}

    def update(self, request):

        # make the user submitted post data mutable
        filter_values = request.POST.copy()

        # cast the show_x values to integers that will evaluate to True/False
        filter_values["show_time"] = int(filter_values["show_time"])
        filter_values["show_expenses"] = int(filter_values["show_expenses"])

        # save in session
        for key in self.values.keys():
            request.session["activity_filter"][key] = filter_values[key]
        request.session.modified = True

    def set_quick_filter(self, request, quick_filter):
        request.session["activity_filter"] = self.quick_filters[quick_filter]
        request.session.modified = True

    def matter(self, request, id):
        new_values = {
            "date_from": None,
            "date_to": None,
            "firm": None,
            "matter": id,
            "keyword": "",
            "comp": None,
            "entered": None,
            "invoiced": None,
            "order": "date, descending",
        }
        for key, val in new_values.items():
            request.session["activity_filter"][key] = val
        request.session.modified = True

    def toggle_entries(self, request, entry_type):
        if entry_type == "time":
            val = "show_time"
        else:
            val = "show_expenses"
        if self.values[val]:
            self.values[val] = False
        else:
            self.values[val] = True
        request.session["activity_filter"][val] = self.values[val]
        request.session.modified = True
