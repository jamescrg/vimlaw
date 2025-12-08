import pytest
from pytest_django.asserts import assertTemplateUsed

pytestmark = pytest.mark.django_db


class TestAICreatePrompt:
    def test_create_prompt_requires_login(self, client):
        client.logout()
        response = client.get("/case/ai/create-prompt/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_create_prompt_requires_matter(self, client):
        response = client.get("/case/ai/create-prompt/")
        # Redirects to AI index when no matter selected
        assert response.status_code == 302

    def test_create_prompt_authenticated(self, client_with_matter, user):
        response = client_with_matter.get("/case/ai/create-prompt/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/ai/prompt.html")

    def test_create_prompt_contains_user_info(self, client_with_matter, user):
        response = client_with_matter.get("/case/ai/create-prompt/")
        content = response.content.decode()
        assert user.email in content
        assert "Craig Legal, LLC" in content

    def test_create_prompt_contains_date(self, client_with_matter):
        response = client_with_matter.get("/case/ai/create-prompt/")
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
        session.save()
        response = client_with_matter.get("/case/ai/create-prompt/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "is an attorney" in content

    def test_create_prompt_paralegal_role(self, client_with_matter, user, matter):
        user.is_attorney = False
        user.first_name = "Jane"
        user.last_name = "Doe"
        user.save()
        # Re-login and re-set matter selection
        client_with_matter.login(username="testuser", password="testpass123")
        client_with_matter.get("/dash/")
        session = client_with_matter.session
        session["documents_selected_matter"] = matter.id
        session.save()
        response = client_with_matter.get("/case/ai/create-prompt/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "is a paralegal supporting an attorney" in content
