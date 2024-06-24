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
    - [Running the Application](#running-the-application)
    - [Creating the first Superuser](#creating-the-first-superuser)
- [Troubleshooting](#troubleshooting)
    - [Troubleshoot Dependency Installation](#troubleshoot-dependency-installation)
    - [Troubleshoot Running Migrations](#troubleshoot-running-migrations)

## Getting Started

Make sure to have the following installed on your machine:

- Python 3.9, not 3.10 or higher
    - Some dependencies are not yet compatible with Python 3.10 or higher
- PostgreSQL

### Setting up PostgreSQL

After installing PostgreSQL on your machine, create a new database, user
and set up privileges and permissions for the user.

**NOTE:** Replace all instances inside `< >` with your own values.

``` postgresql
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

``` bash
python -m venv venv
```

---

After creating the virtual environment, activate it by running:

**Windows:**

``` bash
.\venv\Scripts\activate
```

**Linux/MacOS:**

``` bash
source venv/bin/activate
```

**NOTE:** We will be installing all dependencies, running migrations,
running all Django commands and tests and running the application
inside the virtual environment. For all the following steps, make sure
the virtual environment is activated.

### Installing Dependencies

All the project dependencies are listed in the `requirements.txt` file
located in the project root directory.

To install all dependencies, run the following command:

``` bash
pip install -r requirements.txt
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

``` bash
python manage.py migrate
```

If any problems occur during the migration process, please refer to the
[Troubleshooting - Running Migrations](#troubleshoot-running-migrations) section

### Running the Application

To run the application locally, run the following command:

**NOTE:** Make sure the virtual environment is activated.

``` bash
python manage.py runserver
```

After running the command, the application should be accessible at
[http://localhost:8000](http://localhost:8000).

### Creating the first Superuser

The object manager for the `CustomUser` model has a custom method
for creating a superuser allowing the creation of the superuser
through the Django built-in `createsuperuser` command.

To create the first superuser, run the following command:

**NOTE:** Make sure the virtual environment is activated.

``` bash
python manage.py createsuperuser
```

After running the command, follow the instructions in the terminal
to create the superuser.

## Troubleshooting

### Troubleshoot Dependency Installation

If any problems occur during the installation of dependencies, make sure
to check the following:

- Python version is 3.9 and not 3.10 or higher
- You are running the command inside the virtual environment created in [Step 2](#virtual-environment)
- The `requirements.txt` file is located in the project root directory
- The `requirements.txt` file is not corrupted or missing any dependencies
- The `pip` command is working correctly
- The `pip` version is up-to-date
- The `pip` command is not blocked by any firewall or antivirus software
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
