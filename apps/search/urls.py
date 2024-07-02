from django.urls import path

from apps.search.views import index, results

urlpatterns = [
    path("search/", index, name="search"),
    path("search/results", results, name="search-results"),
]
