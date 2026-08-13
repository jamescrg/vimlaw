"""Connect Claude Desktop: per-user setup page for the notes MCP server.

Generalizes the companion .oxt precedent (the artifact we hand out carries
the user's token, so setup needs no manual configuration): the page renders
the exact claude_desktop_config.json block with the user's real token
substituted, plus a download of the MCP script it points at.

The token is the same CompanionToken the LibreOffice companion uses, so
rotating or revoking it here also re-keys that extension.
"""

import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.drafts.models import CompanionToken

SCRIPT_PATH = Path(settings.BASE_DIR) / "tools" / "kosmos_notes_mcp.py"


def _config_block(request, token):
    return json.dumps(
        {
            "mcpServers": {
                "kosmos": {
                    "command": "uv",
                    "args": ["run", "--script", "/path/to/kosmos_notes_mcp.py"],
                    "env": {
                        "KOSMOS_URL": f"{request.scheme}://{request.get_host()}",
                        "KOSMOS_TOKEN": token.key,
                    },
                }
            }
        },
        indent=2,
    )


@login_required
def claude_index(request):
    token = CompanionToken.objects.filter(user=request.user).first()
    context = {
        "subapp": "claude",
        "token": token,
        "config_block": _config_block(request, token) if token else "",
    }
    return render(request, "settings/claude/index.html", context)


@login_required
@require_POST
def claude_rotate(request):
    """Generate (or re-key) the user's token. Serves both buttons: the
    delete is a no-op when no token exists yet."""
    CompanionToken.objects.filter(user=request.user).delete()
    CompanionToken.for_user(request.user)
    return redirect("settings:claude-index")


@login_required
@require_POST
def claude_revoke(request):
    CompanionToken.objects.filter(user=request.user).delete()
    return redirect("settings:claude-index")


@login_required
def claude_script(request):
    """The MCP server script, served for download so users never need the
    repo. Not personalized (the token travels in the config block)."""
    return FileResponse(
        open(SCRIPT_PATH, "rb"),
        as_attachment=True,
        filename="kosmos_notes_mcp.py",
        content_type="text/x-python",
    )
