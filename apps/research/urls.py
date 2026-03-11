from django.urls import path

from . import views

app_name = "research"

urlpatterns = [
    path("research/", views.research_index, name="index"),
    path("research/search/", views.research_search, name="search"),
    path("research/results/<int:query_id>/", views.research_results, name="results"),
    path("research/result/<int:result_id>/", views.result_status, name="result-status"),
    path("research/status/<int:query_id>/", views.query_status, name="query-status"),
    path("research/<int:query_id>/", views.research_detail, name="detail"),
    path("research/<int:query_id>/delete/", views.research_delete, name="delete"),
]
