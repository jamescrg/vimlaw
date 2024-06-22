class Filter:
    values = {
        "status": "Open",
        "date_from": None,
        "date_to": None,
        "firm": "Campbell & Brannon",
        "order": "name",
        "area": None,
    }

    quick_filters = {
        "open": {
            "status": "Open",
            "date_from": None,
            "date_to": None,
            "firm": "Campbell & Brannon",
            "order": "name",
            "area": None,
        },
        "cb": {
            "status": "Open",
            "date_from": None,
            "date_to": None,
            "firm": "Campbell & Brannon",
            "order": "name",
            "area": "CB",
        },
        "old-republic": {
            "status": "Open",
            "date_from": None,
            "date_to": None,
            "firm": "Campbell & Brannon",
            "order": "name",
            "area": "Old Republic",
        },
        "general": {
            "status": "Open",
            "date_from": None,
            "date_to": None,
            "firm": "Campbell & Brannon",
            "order": "name",
            "area": "General",
        },
    }

    def __init__(self, request):
        matters_filter = request.session.get("matters_filter")
        if matters_filter:
            for key, value in matters_filter.items():
                self.values[key] = value
        else:
            request.session["matters_filter"] = {}

    def update(self, request):
        request.session["matters_filter"]["status"] = request.POST["status"]
        request.session["matters_filter"]["firm"] = request.POST["firm"]
        request.session["matters_filter"]["order"] = request.POST["order"]
        request.session["matters_filter"]["area"] = request.POST["area"]
        request.session["matters_filter"]["date_from"] = request.POST["date_from"]
        request.session["matters_filter"]["date_to"] = request.POST["date_to"]
        request.session.modified = True

    def set_quick_filter(self, request, quick_filter):
        request.session["matters_filter"] = self.quick_filters[quick_filter]

    def order(self, request, order):
        request.session["matters_filter"]["order"] = order
        request.session.modified = True
