# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Project Overview

Law-Admin is a Django-based law practice management application. It manages
matters, contacts, deadlines, time entries, expenses, trust accounting,
and intakes with support for multiple users/timekeepers.

## Development Commands

### Environment Setup

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

### Running the Application

```bash
python manage.py runserver
```

### Testing

```bash
# Run all tests
pytest

# Run tests with parallel execution
pytest -n auto

# Run specific app tests
pytest apps/matters/tests/
```

### Code Quality

```bash
# Format code with Black
black .

# Run linting with flake8
flake8

# Sort imports with isort
isort . --profile black --combine-as --trailing-comma

# Run pre-commit hooks manually
pre-commit run --all-files

# Format Django templates
djlint --profile django --reformat templates/
```

## Architecture

### Core Django Apps Structure

- **accounts/**: Custom user management and authentication
- **matters/**: Core matter management with sub-modules:
  - activity/: Time and expense tracking
  - contacts/: Matter-specific contact management
  - events/: Calendar events and deadlines
  - ledger/: Financial ledger functionality
  - proceedings/: Court proceedings tracking
  - rates/: Billing rate management
  - settlement/: Settlement tracking
  - timeline/: Case timeline management
- **activity/**: Global time and expense management (expenses/, time/)
- **agenda/**: Task and event management (events/, tasks/)
- **contacts/**: Global contact management with Google integration
- **invoicing/**: Billing system (invoices/, payments/, credits/, collection/)
- **intakes/**: Client intake management
- **trust/**: Trust accounting functionality
- **reports/**: Reporting system (activity/, clients/, revenue/)
- **documents/**: Document management and PDF deep linking
- **folders/**: Contact organization
- **search/**: Global search functionality
- **settings/**: Application settings (company/, profile/, users/, integrations/)

### Key Configuration

- **config/**: Django configuration directory
  - settings.py: Main Django settings with environment variable support
  - urls.py: Root URL configuration
- **utils/**: Shared utilities
- **templates/**: Django templates organized by app
- **static/**: CSS, JavaScript, and images

### Database

- PostgreSQL with custom user model (CustomUser)
- Migration files in each app's migrations/ directory

### External Integrations

- Google Calendar API (calendar_tokens.json)
- Google Contacts API (contact_tokens.json)
- PDF generation with WeasyPrint

### Testing Strategy

- pytest with django plugin
- Test files in each app's tests/ directory
- Conftest.py files for test configuration
- Parallel test execution support with pytest-xdist

### Code Standards

Please run pre-commit hooks and fix any linting errors on all significant changes:
- Black code formatting
- isort for import sorting
- flake8 for linting
- djLint for Django template formatting
- Pre-commit hooks enforce code quality
- Migrations excluded from linting (see .pre-commit-config.yaml)

- Do not use inline styles in HTML
- Do not use style tags. Place all styles in a stylesheet.
- Css values should be in rems and snap to a 0.25rem grid
- Tests run slowly on this server, when testing, please run targeted unit tests to cover recent changes
- If a fix fails, clean it up before applying a new fix, unless the solutions are likely to be cumulative.
- When committing changes, please do not add the Claude branding.


### Design Standards

Please always at the start of each session, review the site-wide design conventions and try to make all template and css changes reflect the overall design of the project.


## Template: Django & HTMX Project (IMPORTANT)

Technology Stack: This project uses HTMX (via CDN). We do not use a separate JavaScript framework (React, Vue, etc.) for UI logic.

HATEOAS Principle: All front-end interactivity (AJAX calls, form submissions, dynamic updates) MUST be implemented using HTMX attributes (hx-get, hx-post, hx-target, hx-swap, etc.) placed directly on HTML elements.

Response Content: Django Views handling HTMX requests MUST return only a partial HTML template fragment (a snippet, not a full page) to be swapped into the DOM. Do NOT return JSON unless it's for a highly specific, justified edge case (e.g., uploading a file).
