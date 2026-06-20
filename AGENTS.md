# AGENTS.md - Law Admin Development Guide

This document provides guidance for AI coding agents working in this Django law
practice management codebase.

## Project Overview

A Django 4.2 web application for law practice management. Manages matters, contacts,
deadlines, time entries, expenses, trust accounting, and intakes.

- **Python**: 3.10+ (3.13 in Nix dev environment)
- **Database**: PostgreSQL
- **Package Manager**: uv
- **Framework**: Django 4.2 with HTMX for frontend interactivity

## Build, Test, and Lint Commands

### Environment Setup

```bash
# Create and activate virtual environment
uv venv
source .venv/bin/activate

# Install dependencies (including dev dependencies)
uv sync

# Set up environment variables
cp config/.env.example config/.env
# Edit config/.env with your local settings

# Run migrations
python manage.py migrate

# Build search index (run once after migrations)
python manage.py buildwatson
```

### Running the Application

```bash
# Start development server
python manage.py runserver

# Start background task worker (separate terminal)
python manage.py qcluster

# Using process-compose (Nix environment)
pc-up      # Start all services (PostgreSQL, Django)
pc-down    # Stop all services
```

### Testing Commands

```bash
# Run all tests
pytest -n auto












# Run tests in parallel (faster)
pytest -n auto

# Run a single test file
pytest apps/notes/tests/test_views.py

# Run a single test class
pytest apps/notes/tests/test_views.py::TestNotesIndex

# Run a single test method
pytest apps/notes/tests/test_views.py::TestNotesIndex::test_notes_index_loads

# Run tests matching a pattern
pytest -k "note"

# Run tests and stop on first failure
pytest -x

# Run tests with coverage
pytest --cov=. --cov-report=term-missing
```

### Linting and Formatting Commands

```bash
# Run all pre-commit checks (includes black, isort, flake8, pycln, djlint)
pre-commit run --all-files

# Individual formatters/linters
black .                    # Format Python code
isort .                    # Sort imports
flake8                     # Lint Python code
pycln --all .              # Remove unused imports
djlint --profile django templates/  # Lint Django templates
djlint --reformat --profile django templates/  # Format Django templates

# Type checking (if configured)
pyright
```

### Database Commands

```bash
# Create migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Reset database (Nix environment only)
db-reset

# Connect to database via psql (Nix environment)
db-psql
```

## Code Style Guidelines

### Python Code Style

- **Formatter**: Black (configured via pre-commit)
- **Line Length**: 120 characters (configured in .flake8)
- **Imports**: isort with black profile, combine-as, trailing-comma
- **Linting**: flake8 with E203 ignored (black conflict)
- **Unused Imports**: pycln removes them automatically

### Import Organization

Imports should be organized in this order (enforced by isort):

1. Standard library imports
2. Django imports
3. Third-party imports
4. Local application imports (apps._, utils._, config.\*)

Example:

```python
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import HttpResponse, JsonResponse

from simple_history.models import HistoricalRecords

from apps.contacts.models import Contact
from utils.models import AuditMixin
```

### Django Template Style

- **Formatter**: djlint with Django profile
- **Indentation**: 2 spaces
- **Rule H023 ignored**: Do not use this rule

### Naming Conventions

- **Functions/Variables**: snake_case (e.g., `get_notes_data`, `filter_session_key`)
- **Classes**: PascalCase (e.g., `CustomUser`, `NoteForm`, `TestNotesIndex`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `ROLE_OPTIONS`, `SIDEBAR_SORT_OPTIONS`)
- **Models**: PascalCase singular nouns (e.g., `Matter`, `Contact`, `Note`)
- **Tests**: `test_<action>_<condition>_<expected>` pattern

### Type Hints

Type hints are optional but encouraged for function signatures when they add clarity.
This codebase does not strictly enforce type hints.

### Error Handling

- Use Django's built-in validation in forms and models
- Return appropriate HTTP status codes:
  - `200` for successful GET/POST with content
  - `204` for successful POST with no content (HTMX pattern)
  - `302` for redirects
  - `400` for bad requests (with JsonResponse error message)
  - `404` for not found (use `get_object_or_404`)
- Use `JsonResponse` for API endpoints returning JSON

## Django Patterns and Conventions

### Models

- Use `AuditMixin` for models that need created_at/updated_at tracking
- Use `HistoricalRecords` from django-simple-history for audit trail
- Define `__str__` method for readable representations
- Use `Meta` class for db*table naming (prefix with `app*`)
- Add indexes for frequently queried fields

Example:

```python
from django.db import models
from simple_history.models import HistoricalRecords

from utils.models import AuditMixin


class Note(AuditMixin, models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField(blank=True, default="")
    history = HistoricalRecords()

    class Meta:
        db_table = "app_note"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title
```

### Views

- Use `@login_required` decorator for authenticated views
- Use `@require_POST` for POST-only endpoints
- Use `get_object_or_404` for object lookups
- Return `HttpResponse(status=204)` for HTMX success without content
- Use `HX-Trigger` header to notify HTMX of data changes

Example:

```python
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST


@login_required
def note_delete(request, note_id):
    note = get_object_or_404(Note, pk=note_id)
    note.delete()
    return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})
```

### Forms

- Use `ModelForm` for model-backed forms
- Set `use_required_attribute=False` when appropriate
- Use custom form renderers for consistent styling

### URL Patterns

- Use namespaced URLs (e.g., `reverse("notes:note-view", args=[note.id])`)
- Keep URL patterns in app-specific `urls.py` files

## Testing Conventions

### Test Organization

- Tests go in `tests/` subdirectory within each app
- Use `conftest.py` for pytest fixtures
- Group related tests in classes (e.g., `class TestNotesIndex`)

### Test File Pattern

```python
import pytest
from django.urls import reverse

from apps.notes.models import Note

pytestmark = pytest.mark.django_db


class TestNotesIndex:
    def test_notes_index_requires_login(self, client, matter):
        client.logout()
        url = reverse("notes:index")
        response = client.get(url)
        assert response.status_code == 302

    def test_notes_index_loads(self, client_with_matter):
        matter = client_with_matter.matter
        url = reverse("notes:index")
        response = client_with_matter.get(url)
        assert response.status_code == 200
```

### Fixtures

Define common fixtures in `conftest.py`:

```python
@pytest.fixture
def user():
    user = CustomUser.objects.create(username="testuser")
    user.set_password("testpass123")
    user.save()
    return user


@pytest.fixture
def client(user):
    client = Client()
    client.login(username="testuser", password="testpass123")
    return client


@pytest.fixture
def client_with_matter(client, matter):
    session = client.session
    session["selected_matter"] = matter.id
    session.save()
    client.matter = matter
    return client
```

### Test Assertions

- Use `assert response.status_code == <expected>`
- Use `assertTemplateUsed(response, "template.html")` for template checks
- Use `assert "content" in response.content` for content checks
- Use `refresh_from_db()` to verify database changes

## Pre-commit Hooks

The project uses pre-commit to enforce code quality. Configuration in `.pre-commit-config.yaml`:

- **trailing-whitespace**: Removes trailing whitespace
- **end-of-file-fixer**: Ensures files end with newline
- **check-yaml**: Validates YAML files
- **black**: Formats Python code
- **isort**: Sorts imports
- **pycln**: Removes unused imports
- **flake8**: Lints Python code
- **djlint**: Lints and formats Django templates

Always run `pre-commit run --all-files` before committing.

## Key Files and Directories

```text
kosmos/
├── apps/                    # Django applications
│   ├── accounts/           # User authentication
│   ├── case/               # Case documents and management
│   ├── contacts/           # Contact management
│   ├── matters/            # Legal matters
│   ├── notes/              # Notes and analysis
│   ├── invoicing/          # Billing and invoices
│   └── ...
├── config/                 # Project configuration
│   ├── settings.py        # Django settings
│   └── .env               # Environment variables
├── templates/              # Django templates
├── static/                 # Static files
├── utils/                  # Shared utilities
│   ├── models.py          # AuditMixin and shared model utilities
│   └── middleware.py      # Custom middleware
├── manage.py              # Django management script
├── pyproject.toml         # Python project configuration
└── .pre-commit-config.yaml # Pre-commit hooks
```

## Environment Variables

Required environment variables (see `config/.env.example`):

- `SECRET_KEY`: Django secret key
- `DEBUG`: Debug mode (True/False)
- `ENV`: Environment (development/production)
- `ALLOWED_HOSTS`: Comma-separated list of allowed hosts
- `DATABASE_URL` or individual DB settings (`DB_NAME`, `DB_USER`, `DB_PASSWORD`,
  `DB_HOST`, `DB_PORT`)

## Common Tasks

### Adding a New Model

1. Create model in `apps/<app>/models.py`
2. Run `python manage.py makemigrations <app>`
3. Run `python manage.py migrate`
4. Add to admin if needed in `apps/<app>/admin.py`

### Adding a New View

1. Create view function in `apps/<app>/views.py`
2. Add URL pattern in `apps/<app>/urls.py`
3. Create template in `templates/<app>/`
4. Write tests in `apps/<app>/tests/test_views.py`

### Running Background Tasks

Background tasks use Django-Q2. Define tasks in `tasks.py` files within apps.

```bash
# Start the task worker
python manage.py qcluster
```

## Notes for AI Agents

- This is a law practice management application for legal professionals
- Users are attorneys and legal staff, not end consumers
- The application handles confidential attorney-client information
- When writing tests, follow the existing patterns in `apps/*/tests/`
- Always use the project's existing utilities and patterns rather than introducing
  new libraries
- HTMX is used extensively for dynamic UI updates without full page reloads
