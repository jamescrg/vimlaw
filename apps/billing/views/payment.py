from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import FormView, TemplateView

from apps.billing.forms.payment import PaymentForm
from apps.billing.models.invoice import Invoice
from apps.billing.models.payment import Payment
from apps.matters.models import Matter


class PaymentIndex(LoginRequiredMixin, TemplateView):
    template_name = "billing/payment-list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        payments = Payment.objects.all().select_related("matter")
        context["payments"] = payments

        return context


class AddPaymentView(LoginRequiredMixin, FormView):
    template_name = "billing/payments/form-payment.html"
    form_class = PaymentForm
    success_url = reverse_lazy("billing:billing")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        form = self.form_class()

        matter_ids = (
            Invoice.objects.filter(status="SENT")
            .select_related("matter")
            .values_list("matter", flat=True)
        )

        matters = Matter.objects.filter(id__in=matter_ids)
        form.fields["matter"].queryset = matters

        context["form"] = form

        return context

    def form_valid(self, form):
        payment = form.save(commit=False)
        payment.save()

        return super().form_valid(form)
