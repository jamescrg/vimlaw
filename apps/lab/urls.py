from django.urls import path

from apps.lab.views import index, results, email_test

urlpatterns = [
    path("lab/", index, name="lab"),
    path("lab/results", results, name="lab-results"),
    path("lab/email", email_test, name="email-test"),
]
