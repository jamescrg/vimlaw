from django.urls import path

from apps.search.views import index, results

app_name = "search"

# fmt: off
urlpatterns = [
    path("search/", index, name="search"),
    path("search/results", results, name="results"),
]
# fmt: on
