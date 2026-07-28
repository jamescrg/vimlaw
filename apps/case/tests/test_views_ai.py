import pytest
from pytest_django.asserts import assertTemplateUsed

from apps.case.ai.models import Conversation
from apps.case.ai.selector import MODEL_CONTEXT_LIMITS, MODEL_HARD_LIMITS
from apps.case.ai.tasks import CLAUDE_MODELS, GEMINI_MODELS
from apps.case.ai.views import RETIRED_LLMS, VALID_LLMS
from apps.settings.models import Firm

pytestmark = pytest.mark.django_db


class TestAICreatePrompt:
    def test_create_prompt_requires_login(self, client, matter):
        client.logout()
        response = client.get(f"/case/{matter.id}/ai/create-prompt/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_create_prompt_requires_matter(self, client, matter):
        # With valid matter_id in URL
        response = client.get(f"/case/{matter.id}/ai/create-prompt/")
        assert response.status_code == 200

    def test_create_prompt_authenticated(self, client_with_matter, user):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/ai/create-prompt/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/ai/prompt.html")

    def test_create_prompt_contains_user_info(self, client_with_matter, user):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/ai/create-prompt/")
        content = response.content.decode()
        assert user.email in content
        company = Firm.objects.first()
        assert company.name in content

    def test_create_prompt_contains_date(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/ai/create-prompt/")
        content = response.content.decode()
        assert "## Request Date" in content

    def test_create_prompt_attorney_role(self, client_with_matter, user, matter):
        user.is_attorney = True
        user.first_name = "John"
        user.last_name = "Doe"
        user.save()
        # Re-login and re-set matter selection
        client_with_matter.login(username="testuser", password="testpass123")
        client_with_matter.get("/dash/")
        session = client_with_matter.session
        session["documents_selected_matter"] = matter.id
        session["last_viewed_matter"] = matter.id
        session.save()
        client_with_matter.matter = matter
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "Title: Attorney" in content
        # Roster anchors every firm name to an authoritative title
        assert "## Firm Team" in content

    def test_create_prompt_staff_fallback(self, client_with_matter, user, matter):
        """No explicit title + not an attorney falls back to Staff."""
        user.is_attorney = False
        user.first_name = "Jane"
        user.last_name = "Doe"
        user.save()
        # Re-login and re-set matter selection
        client_with_matter.login(username="testuser", password="testpass123")
        client_with_matter.get("/dash/")
        session = client_with_matter.session
        session["documents_selected_matter"] = matter.id
        session["last_viewed_matter"] = matter.id
        session.save()
        client_with_matter.matter = matter
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "Title: Staff" in content

    def test_create_prompt_explicit_title(self, client_with_matter, user, matter):
        """An explicit title beats the attorney-flag fallback."""
        user.is_attorney = False
        user.title = "Office Manager"
        user.first_name = "Jane"
        user.last_name = "Doe"
        user.save()
        # Re-login and re-set matter selection
        client_with_matter.login(username="testuser", password="testpass123")
        client_with_matter.get("/dash/")
        session = client_with_matter.session
        session["documents_selected_matter"] = matter.id
        session["last_viewed_matter"] = matter.id
        session.save()
        client_with_matter.matter = matter
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "Title: Office Manager" in content
        assert "Jane Doe — Office Manager" in content

    def test_create_prompt_uses_company_jurisdiction(self, client_with_matter, matter):
        company = Firm.objects.first()
        company.jurisdiction = "Georgia"
        company.save()
        matter.jurisdiction = ""
        matter.save()
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        content = response.content.decode()
        assert "jurisdiction of Georgia" in content
        assert "[JURISDICTION]" not in content

    def test_create_prompt_matter_jurisdiction_overrides_company(
        self, client_with_matter, matter
    ):
        company = Firm.objects.first()
        company.jurisdiction = "Georgia"
        company.save()
        matter.jurisdiction = "Florida"
        matter.save()
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        content = response.content.decode()
        assert "jurisdiction of Florida" in content
        assert "jurisdiction of Georgia" not in content

    def test_create_prompt_falls_back_to_us_common_law(
        self, client_with_matter, matter
    ):
        company = Firm.objects.first()
        company.jurisdiction = ""
        company.save()
        matter.jurisdiction = ""
        matter.save()
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        content = response.content.decode()
        assert "United States common law" in content
        assert "[JURISDICTION]" not in content


class TestLLMChoiceWiring:
    """Every model in the picker has to be wired through four tables: the
    request validator, the provider dispatch, and both selector budgets.
    Missing one is silent — the picker offers a model that then falls back
    to Sonnet, or blows past its context window."""

    def test_every_picker_choice_is_fully_wired(self):
        for key, _label in Conversation.LLM_CHOICES:
            assert key in VALID_LLMS, f"{key} would be rejected by the views"
            assert key in MODEL_CONTEXT_LIMITS, f"{key} has no selector budget"
            assert key in MODEL_HARD_LIMITS, f"{key} has no hard ceiling"
            assert key in CLAUDE_MODELS or key in GEMINI_MODELS, (
                f"{key} maps to no provider model ID"
            )

    def test_opus_4_6_dispatches_to_opus_4_6(self):
        assert CLAUDE_MODELS["claude-opus-4-6"] == "claude-opus-4-6"
        assert MODEL_HARD_LIMITS["claude-opus-4-6"] == 1_000_000

    def test_retired_choices_still_dispatch(self):
        """Conversations started on a retired model keep sending."""
        for key in RETIRED_LLMS:
            assert key in VALID_LLMS
            assert key in CLAUDE_MODELS or key in GEMINI_MODELS
