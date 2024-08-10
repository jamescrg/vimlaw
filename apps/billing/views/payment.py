from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import FormView, TemplateView, View

from apps.billing.filters.payment import PaymentFilter
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


@login_required
def delete_payment(request, pk):
    payment = Payment.objects.get(pk=pk)
    payment.delete()

    payments = Payment.objects.all().select_related("matter")

    return render(request, "billing/payments/payment-list.html", {"payments": payments})


class EditPaymentView(LoginRequiredMixin, FormView):
    template_name = "billing/payments/edit-payment.html"
    form_class = PaymentForm

    def get_success_url(self):
        return reverse_lazy("billing:billing")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()

        payment = Payment.objects.get(pk=self.kwargs["pk"])
        kwargs["instance"] = payment

        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        form = self.form_class()

        matter_ids = Invoice.objects.filter(status="SENT").values_list(
            "matter", flat=True
        )

        payment = Payment.objects.get(pk=self.kwargs["pk"])

        # Make sure the pre-edit matter is included, even if it doesn't have an invoice
        matters = Matter.objects.filter(id__in=matter_ids) | Matter.objects.filter(
            id=payment.matter.id
        )

        form.fields["matter"].queryset = matters

        form.fields["matter"].initial = payment.matter
        form.fields["date"].initial = payment.date
        form.fields["amount"].initial = payment.amount
        form.fields["payment_method"].initial = payment.payment_method
        form.fields["detail"].initial = payment.detail

        context["form"] = form
        context["payment"] = payment

        return context

    def form_valid(self, form):
        form.save()

        return super().form_valid(form)


class PaymentFilterView(LoginRequiredMixin, View):
    template_name = "billing/payments/payment-filter.html"

    def get_filter(self, request):
        filter_data = request.session.get("payment_filter", request.POST)

        return PaymentFilter(
            filter_data, queryset=Payment.objects.all().select_related("matter")
        )

    def get(self, request):
        filter = self.get_filter(request)

        return render(request, self.template_name, {"filter": filter})

    def post(self, request):
        request.session["payment_filter"] = request.POST

        return redirect("billing:billing")
