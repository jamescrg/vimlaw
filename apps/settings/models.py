from django.db import models

from utils.models import AuditMixin

# Models offered for AI quick task entry - the cheap tier of each provider
# the app integrates. The picked model only matters when quick_task_ai is on;
# a missing API key just fails the call and the fuzzy matcher takes over.
QUICK_TASK_AI_MODELS = (
    ("gemini-flash", "Gemini Flash"),
    ("claude-sonnet", "Claude Sonnet"),
)


class Firm(AuditMixin):
    name = models.CharField(max_length=255)
    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    billing_email = models.EmailField(blank=True)
    invoice_bcc = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Comma-separated addresses BCC'd on every invoice email.",
    )
    # Cc + Reply-To on template emails sent to intakes. Must be a human
    # inbox, not the Mailgun intake pipeline address - the pipeline would
    # log our own outbound copies as duplicate notes.
    intake_email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to="company/", blank=True, null=True)
    jurisdiction = models.CharField(max_length=100, blank=True)
    # Quick task entry: the fuzzy "Matter - description" prefix matcher is
    # the default; AI interpretation of the whole line is an opt-in add-on.
    quick_task_ai = models.BooleanField(default=False)
    quick_task_ai_model = models.CharField(
        max_length=20, choices=QUICK_TASK_AI_MODELS, default="gemini-flash"
    )

    class Meta:
        verbose_name_plural = "firms"

    def __str__(self):
        return self.name
