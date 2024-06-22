class Filter:
    values = {
        "status": "Open",
        "date_from": None,
        "date_to": None,
        "area": None,
        "order": None,
        "limit": None,
        "source": None,
    }

    quick_filters = {
        "open": {
            "status": "Open",
            "date_from": None,
            "date_to": None,
            "area": None,
            "order": "date",
            "limit": None,
            "source": None,
        },
        "recent": {
            "status": None,
            "date_from": None,
            "date_to": None,
            "area": None,
            "order": "date",
            "limit": 20,
            "source": None,
        },
        "pending": {
            "status": "Pending",
            "date_from": None,
            "date_to": None,
            "area": None,
            "order": "date",
            "limit": None,
            "source": None,
        },
    }

    def __init__(self, request):
        intakes_filter = request.session.get("intakes_filter")
        if intakes_filter:
            for key, value in intakes_filter.items():
                self.values[key] = value
        else:
            request.session["intakes_filter"] = {}

    def update(self, request):
        request.session["intakes_filter"]["status"] = request.POST["status"]
        request.session["intakes_filter"]["date_from"] = request.POST["date_from"]
        request.session["intakes_filter"]["date_to"] = request.POST["date_to"]
        request.session["intakes_filter"]["area"] = request.POST["area"]
        request.session["intakes_filter"]["order"] = request.POST["order"]
        request.session["intakes_filter"]["source"] = request.POST["source"]
        request.session["intakes_filter"]["limit"] = None
        request.session.modified = True

    def set_quick_filter(self, request, quick_filter):
        request.session["intakes_filter"] = self.quick_filters[quick_filter]

    def order(self, request, order):
        request.session["intakes_filter"]["order"] = order
        request.session.modified = True
