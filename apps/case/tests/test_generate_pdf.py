from unittest.mock import MagicMock, patch

import pytest
from django.http import Http404

from apps.case.facts.generate_pdf import generate_facts_pdf

pytestmark = pytest.mark.django_db


class TestGenerateFactsPdf:
    def test_nonexistent_matter_raises_404(self):
        """Generating PDF for non-existent matter should raise Http404."""
        mock_request = MagicMock()
        with pytest.raises(Http404):
            generate_facts_pdf(99999, mock_request)

    @patch("apps.case.facts.generate_pdf.HTML")
    @patch("apps.case.facts.generate_pdf.render_to_string")
    def test_generates_pdf(self, mock_render, mock_html, matter, fact, client):
        """PDF should be generated for valid matter."""
        mock_render.return_value = "<html>Test PDF</html>"
        mock_html_instance = MagicMock()
        mock_html.return_value = mock_html_instance

        # Create a mock request
        mock_request = MagicMock()
        mock_request.build_absolute_uri.return_value = "http://testserver/"

        result = generate_facts_pdf(matter.id, mock_request)

        mock_render.assert_called_once()
        mock_html.assert_called_once()
        mock_html_instance.write_pdf.assert_called_once()
        assert result is not None

    @patch("apps.case.facts.generate_pdf.HTML")
    @patch("apps.case.facts.generate_pdf.render_to_string")
    def test_includes_matter_in_context(self, mock_render, mock_html, matter, client):
        """Context should include matter."""
        mock_render.return_value = "<html></html>"
        mock_html.return_value = MagicMock()

        mock_request = MagicMock()
        mock_request.build_absolute_uri.return_value = "http://testserver/"

        generate_facts_pdf(matter.id, mock_request)

        call_args = mock_render.call_args
        context = call_args[0][1]
        assert context["matter"] == matter

    @patch("apps.case.facts.generate_pdf.HTML")
    @patch("apps.case.facts.generate_pdf.render_to_string")
    def test_includes_facts_in_context(
        self, mock_render, mock_html, matter, fact, client
    ):
        """Context should include facts for the matter."""
        mock_render.return_value = "<html></html>"
        mock_html.return_value = MagicMock()

        mock_request = MagicMock()
        mock_request.build_absolute_uri.return_value = "http://testserver/"

        generate_facts_pdf(matter.id, mock_request)

        call_args = mock_render.call_args
        context = call_args[0][1]
        assert fact in context["facts"]

    @patch("apps.case.facts.generate_pdf.HTML")
    @patch("apps.case.facts.generate_pdf.render_to_string")
    def test_includes_proceeding_in_context(
        self, mock_render, mock_html, matter, proceeding, client
    ):
        """Context should include proceeding for the matter."""
        mock_render.return_value = "<html></html>"
        mock_html.return_value = MagicMock()

        mock_request = MagicMock()
        mock_request.build_absolute_uri.return_value = "http://testserver/"

        generate_facts_pdf(matter.id, mock_request)

        call_args = mock_render.call_args
        context = call_args[0][1]
        assert context["proceeding"] == proceeding

    @patch("apps.case.facts.generate_pdf.HTML")
    @patch("apps.case.facts.generate_pdf.render_to_string")
    def test_uses_correct_template(self, mock_render, mock_html, matter, client):
        """Should render the correct template."""
        mock_render.return_value = "<html></html>"
        mock_html.return_value = MagicMock()

        mock_request = MagicMock()
        mock_request.build_absolute_uri.return_value = "http://testserver/"

        generate_facts_pdf(matter.id, mock_request)

        call_args = mock_render.call_args
        template_name = call_args[0][0]
        assert template_name == "case/facts/pdf.html"
