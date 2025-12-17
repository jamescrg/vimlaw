import pytest
from pytest_django.asserts import assertTemplateUsed

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
        assert "Craig Legal, LLC" in content

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
        session["last_viewed_matter"] = matter.id
        session.save()
        client_with_matter.matter = matter
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "is a paralegal supporting an attorney" in content
