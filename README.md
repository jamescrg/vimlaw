# Law-Admin

A web-based law practice management application. Manage matters, contacts, deadlines, time entries, expenses, trust
accounting, and intakes. Supports multiple users / time-keepers. Emphasis on a clean, simple UI and the efficient
execution of core functionality.

## Table of Contents

- [Getting Started](#getting-started)
  - [Setting up PostgreSQL](#setting-up-postgresql)
  - [Virtual Environment](#virtual-environment)
  - [Installing Dependencies](#installing-dependencies)
  - [Environment Variables](#environment-variables)
  - [Running Migrations](#running-migrations)
  - [Building the Search Index](#building-the-search-index)
  - [Running the Application](#running-the-application)
  - [Running Background Tasks](#running-background-tasks)
  - [Creating the first Superuser](#creating-the-first-superuser)
- [Troubleshooting](#troubleshooting)
  - [Troubleshoot Dependency Installation](#troubleshoot-dependency-installation)
  - [Troubleshoot Running Migrations](#troubleshoot-running-migrations)
- [Steps After Squashing Migrations](#steps-after-squashing-migrations)
  - [Step 1: Ensure squashing was done correctly](#step-1-ensure-squashing-was-done-correctly)
  - [Step 2: Removing the old migration history](#step-2-removing-the-old-migration-history)
  - [Step 3: Faking Django content type migrations](#step-3-faking-django-content-type-migrations)
  - [Step 4: Faking the squashed migrations](#step-4-faking-the-squashed-migrations)
- [Google Calendar/Contact Integration](#google-calendarcontact-integration)
  - [Step 1: Create a Google Cloud Project](#step-1-create-a-google-cloud-project)
  - [Step 2: Add the credentials file to the project](#step-2-add-the-credentials-file-to-the-project)
  - [Step 3: Set up the environment variables](#step-3-set-up-the-environment-variables)

## Getting Started

Make sure to have the following installed on your machine:

- Python 3.10 or higher
- PostgreSQL
- [uv](https://docs.astral.sh/uv/)

### Additional Machine Requirements

The application needs additional software to be installed on the machine
where the application will be running:

```bash
sudo apt-get install -y libpangocairo-1.0-0 tesseract-ocr ghostscript poppler-utils
```

- **Pango** (`libpangocairo-1.0-0`) - Required by WeasyPrint for PDF generation
- **Tesseract** (`tesseract-ocr`) - OCR engine for text extraction from scanned PDFs
- **Ghostscript** (`ghostscript`) - Required by ocrmypdf for PDF processing
- **Poppler** (`poppler-utils`) - Required by pdf2image for PDF to image conversion

### Setting up PostgreSQL

After installing PostgreSQL on your machine, create a new database, user
and set up privileges and permissions for the user.

**NOTE:** Replace all instances inside `< >` with your own values.

```postgresql
CREATE DATABASE <database_name>;
CREATE USER <database_user> WITH ENCRYPTED PASSWORD '<user_password>';
GRANT ALL PRIVILEGES ON DATABASE <database_name> TO <database_user>;
ALTER DATABASE <database_name> OWNER TO <database_user>;
```

The upper commands will create a new database, user with an encrypted password
and grant all privileges to the user while also making the user the owner of the database.

**IMPORTANT:** Remember all the values you used as variables as they will
be needed in the next steps.

### Virtual Environment

If running the application outside a container, it is recommended to create
a virtual environment to manage all project dependencies.

To create a virtual environment, navigate to the project root directory
and run the following command:

```bash
uv venv
```

This creates a `.venv` directory with the virtual environment.

______________________________________________________________________

After creating the virtual environment, activate it by running:

**Windows:**

```bash
.\.venv\Scripts\activate
```

**Linux/MacOS:**

```bash
source .venv/bin/activate
```

**NOTE:** We will be installing all dependencies, running migrations,
running all Django commands and tests and running the application
inside the virtual environment. For all the following steps, make sure
the virtual environment is activated.

### Installing Dependencies

All the project dependencies are defined in `pyproject.toml` located in the
project root directory.

To install all dependencies (including dev dependencies), run:

```bash
uv sync
```

If any problems occur during the installation of dependencies, please refer to the
[Troubleshooting - Troubleshoot Dependency Installation](#troubleshoot-dependency-installation) section.

### Environment Variables

The project uses a number of environment variables to store either
sensitive information or instance-specific configuration.

An example of the `.env` file is provided in the configuration directory
located at `config/.env.example`.

To set up the project environment correctly, create a new `.env` file
in the same directory as the example file and copy the contents of the
example file into the new `.env` file.

**The `.env.example` file has all the necessary environment variables,
their types, examples and descriptions.**

### Running Migrations

Migrations in this project are versioned and stored in the `migrations` directory
located in each Django app. To run all migrations and create the
necessary database schema, run the following command:

**NOTE:** Make sure the virtual environment is activated.

```bash
python manage.py migrate
```

If any problems occur during the migration process, please refer to the
[Troubleshooting - Running Migrations](#troubleshoot-running-migrations) section

### Building the Search Index

The application uses django-watson for full-text search across documents, highlights, and facts.
After running migrations for the first time (or after restoring a database), build the search index:

```bash
python manage.py buildwatson
```

**Note:** You only need to run this once. Watson automatically keeps the index updated as you
create, edit, or delete records. You'll need to rebuild if you:

- Restore a database from backup
- Add new models to the search configuration
- Change which fields are indexed for existing models

### Running the Application

To run the application locally, run the following command:

**NOTE:** Make sure the virtual environment is activated.

```bash
python manage.py runserver
```

After running the command, the application should be accessible at
[http://localhost:8000](http://localhost:8000).

### Running Background Tasks

The application uses Django-Q for background task processing (OCR, etc.).
To process background tasks, run the following command in a separate terminal:

**NOTE:** Make sure the virtual environment is activated.

```bash
python manage.py qcluster
```

#### Production Setup (systemd)

For production deployments, create a systemd service to run the task worker.

Create `/etc/systemd/system/qcluster.service`:

```ini
[Unit]
Description=Django-Q Cluster
After=network.target

[Service]
User=<your_user>
Group=<your_group>
WorkingDirectory=/path/to/law
ExecStart=/path/to/law/.venv/bin/python manage.py qcluster
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable qcluster
sudo systemctl start qcluster
```

### Creating the first Superuser

The object manager for the `CustomUser` model has a custom method
for creating a superuser allowing the creation of the superuser
through the Django built-in `createsuperuser` command.

To create the first superuser, run the following command:

**NOTE:** Make sure the virtual environment is activated.

```bash
python manage.py createsuperuser
```

After running the command, follow the instructions in the terminal
to create the superuser.

## Troubleshooting

### Troubleshoot Dependency Installation

If any problems occur during the installation of dependencies, make sure
to check the following:

- Python version is 3.10 or higher
- You are running the command inside the virtual environment created in [Virtual Environment](#virtual-environment)
- The `pyproject.toml` file is located in the project root directory
- The `uv` command is installed and working correctly (`uv --version`)
- The `uv` command is not blocked by any firewall or antivirus software
- The internet connection is stable and working correctly

### Troubleshoot Running Migrations

If any problems occur during the migration process, make sure to check the following:

- The database is set up correctly and the user has all the necessary privileges
- The database connection is set up correctly in the `.env` file
- Each django app has a `migrations` directory with the `__init__.py` file and the migration files
- The database connection is working correctly
- The database is running and accessible
- The database is not blocked by any firewall or antivirus software
- The database is not corrupted or missing any necessary extensions
- The database is not missing any necessary configuration

### Steps After Squashing Migrations

Squashing migration files is a process that takes all the migration
files from all the apps and squashes them into a single migration file: `0001_initial.py`.

This is usually done when there are too many migration files or
there is an issue with the migration files that cannot be resolved
in any other way.

However, after squashing the migration files, some additional
actions are needed to ensure the database is in a consistent and
synchronized state with the new migration files and to ensure
the migration file sequence is correct (some migration files
have dependencies on other migration files).

**WARNING:** Do not proceed with the following steps without
backing up the database and the migration files.

______________________________________________________________________

#### Step 1: Ensure squashing was done correctly

Make sure the squashing process was done correctly and there are no
known issues with the migrations. This should be tested locally
by running the migrations and loading a dump of the production
database to ensure the migrations work correctly.

Additionally, it is recommended to test out creating new migrations
to ensure the squashing process did not break the migration sequence.

#### Step 2: Removing the old migration history

Django keeps track of the migration history in the `django_migrations`
table in the database. After squashing the migration files, the old
migration history should be removed, since those files no longer
exist and are not needed.

At this point, it is safe to delete all rows from the `django_migrations`
table.

**NOTE:** Do not delete the _TABLE_, only the records inside the table.

#### Step 3: Faking Django content type migrations

Django has a built-in content type framework that is used to store
information about all the models and their content types. This is
used for the `ContentType` model and is used in the admin panel
and other parts of Django.

The reason for faking the content type migrations lies in the
fact that in Django 1.8, the `ContentType` model was altered,
having the `name` field removed from it. Because of this,
there are 2 migration files that are automatically created
when running the `makemigrations` command. These 2 files need
to be faked before faking any other migrations.

To fake the content type migrations, run the following command:

```bash
python manage.py migrate --fake contenttypes
```

You can check if the content type migrations were faked correctly
by running the following command:

```bash
python manage.py showmigrations
```

#### Step 4: Faking the squashed migrations

All that is left is to fake the squashed migrations from all
the other apps. This should be a simple process, since all
the migration files have a proper sequence and are squashed.

To fake all the squashed migrations, run the following command:

```bash
python manage.py migrate --fake
```

After running the command, check if all the migrations were
faked correctly by running the following command:

```bash
python manage.py showmigrations
```

______________________________________________________________________

If all the migrations are marked as applied, the process
was successful and the database is in a consistent state.

You should have no further issues with the migrations and new
changes to the models can be made, as before, by running the
`makemigrations` and `migrate` commands.

### Google Calendar/Contact Integration

To integrate Google Calendar and Contacts into the application,
you will need to finish a few additional steps.

#### Step 1: Create a Google Cloud Project

Create a new project in the Google Cloud Console and enable the
Google Calendar and Google Contacts APIs.

After finishing a project, you will be able to download
the credentials file in JSON format.

#### Step 2: Add the credentials file to the project

There is an empty directory in the project root directory called `/google`.

Add the credentials file to the `/google` directory and
rename it to `google_tokens.json`.

#### Step 3: Set up the environment variables

In the `.env` file, there is an additional environment variable
that needs to be set up for the Calendar integration.

The variable is `CALENDAR_ID` and it should be set to the
string value of the Google Calendar ID found in the Calendar
settings.

______________________________________________________________________

After finishing these steps, the Google Calendar and Contacts
integration should be set up and working correctly.
