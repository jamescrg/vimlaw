"""Create the starter intake form templates.

The bundled forms are transcribed from the Craig Legal website's live
questionnaires — the inquiry form, the client intake, onboarding, and the
eleven dispute supplements — so a fresh environment has something realistic to
send without anyone rebuilding it by hand.

Safe to re-run. By default an existing form is left alone, because staff edits
in the builder outrank the seed; `--replace` overwrites the questions of the
ones it already knows about.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.intakes.client_forms.models import FormTemplate, seed_templates
from apps.intakes.client_forms.schema import LAYOUT_TYPES, SchemaError, normalize_schema


class Command(BaseCommand):
    help = "Create the starter intake form templates (Craig Legal questionnaires)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--list",
            action="store_true",
            help="Show the available forms and exit, changing nothing.",
        )
        parser.add_argument(
            "--only",
            action="append",
            metavar="KEY",
            help="Seed just this form (repeatable). Use --list for the keys.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help=(
                "Overwrite the questions of forms that already exist. Bumps "
                "the version; submissions already sent keep their own snapshot."
            ),
        )
        parser.add_argument(
            "--draft",
            action="store_true",
            help="Create the forms inactive, so they can be reviewed before use.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without writing anything.",
        )

    def handle(self, *args, **options):
        available = {form["key"]: form for form in seed_templates()}

        if options["list"]:
            for key, form in available.items():
                questions = self._question_count(form["schema"])
                self.stdout.write(
                    f"{key:24} {form['name']:40} {questions:3d} questions"
                )
            return

        keys = options["only"] or list(available)
        unknown = [key for key in keys if key not in available]
        if unknown:
            raise CommandError(f"Unknown form(s): {', '.join(unknown)}. Try --list.")

        created, updated, skipped = [], [], []
        dry_run = options["dry_run"]

        # One transaction: a half-seeded environment is worse than an unseeded
        # one, and this is cheap enough to do atomically.
        with transaction.atomic():
            for key in keys:
                form = available[key]
                try:
                    schema = normalize_schema(form["schema"])
                except SchemaError as exc:
                    raise CommandError(f"{key}: bundled schema is invalid — {exc}")

                existing = FormTemplate.objects.filter(name=form["name"]).first()

                if existing is None:
                    if not dry_run:
                        FormTemplate.objects.create(
                            name=form["name"],
                            description=form["description"],
                            intro_text=form["intro_text"],
                            is_active=not options["draft"],
                            schema=schema,
                        )
                    created.append(form["name"])
                elif options["replace"]:
                    if not dry_run:
                        existing.description = form["description"]
                        existing.intro_text = form["intro_text"]
                        existing.schema = schema
                        existing.version += 1
                        existing.save()
                    updated.append(form["name"])
                else:
                    skipped.append(form["name"])

            if dry_run:
                transaction.set_rollback(True)

        self._report(created, updated, skipped, dry_run=dry_run)

    def _question_count(self, schema):
        return sum(1 for field in schema if field.get("type") not in LAYOUT_TYPES)

    def _report(self, created, updated, skipped, *, dry_run):
        prefix = "Would create" if dry_run else "Created"
        for name in created:
            self.stdout.write(self.style.SUCCESS(f"{prefix}: {name}"))
        for name in updated:
            self.stdout.write(
                self.style.WARNING(
                    f"{'Would replace' if dry_run else 'Replaced'}: {name}"
                )
            )
        for name in skipped:
            self.stdout.write(f"Already present, left alone: {name}")

        summary = (
            f"{len(created)} created, {len(updated)} replaced, {len(skipped)} skipped"
        )
        self.stdout.write(self.style.SUCCESS(summary))
        if skipped and not dry_run:
            self.stdout.write("Re-run with --replace to overwrite the ones left alone.")
