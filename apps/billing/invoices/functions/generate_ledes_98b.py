import os
from itertools import chain
from tempfile import NamedTemporaryFile
from typing import Dict, Union

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.billing.invoices.models import Invoice

HEADER_FIELDS = [
    "INVOICE_DATE",
    "INVOICE_NUMBER",
    "CLIENT_ID",
    "LAW_FIRM_MATTER_ID",
    "INVOICE_TOTAL",
    "BILLING_START_DATE",
    "BILLING_END_DATE",
    "INVOICE_DESCRIPTION",
    "LINE_ITEM_NUMBER",
    "EXP/FEE/INV_ADJ_TYPE",
    "LINE_ITEM_NUMBER_OF_UNITS",
    "LINE_ITEM_ADJUSTMENT_AMOUNT",
    "LINE_ITEM_TOTAL",
    "LINE_ITEM_DATE",
    "LINE_ITEM_TASK_CODE",
    "LINE_ITEM_EXPENSE_CODE",
    "LINE_ITEM_ACTIVITY_CODE",
    "TIMEKEEPER_ID",
    "LINE_ITEM_DESCRIPTION",
    "LAW_FIRM_ID",
    "LINE_ITEM_UNIT_COST",
    "TIMEKEEPER_NAME",
    "TIMEKEEPER_CLASSIFICATION",
    "CLIENT_MATTER_ID",
]

HEADER = f"LEDES1998B[]\n{'|'.join(HEADER_FIELDS)}[]\n"


def _get_combined_entries(invoice: Invoice) -> list:
    """
    Returns a list of combined time and expense entries, with a shared index and sorted by date
    """
    # Merge time and expense entries into a single iterable
    merged_data = chain(
        # Create tuples of (entry, type) for each entry in the invoice
        ((entry, "time") for entry in invoice.timeentry_set.all()),
        ((expense, "expense") for expense in invoice.expenseentry_set.all()),
    )

    # Sort the merged data by date in descending order (most recent first)
    # x[0] refers to the entry object (time or expense entry)
    return sorted(merged_data, key=lambda x: x[0].date, reverse=True)


def _get_billing_dates(invoice: Invoice) -> tuple:
    """
    Given an invoice, return a billing start and end date
     - Start date is the earliest date of all entries
     - End date is the latest date of all entries
    """
    combined_entries = _get_combined_entries(invoice)

    earliest_date = min(entry.date for entry, _ in combined_entries)
    latest_date = max(entry.date for entry, _ in combined_entries)

    return earliest_date, latest_date


def _format_line(
    invoice: Invoice,
    entry: Union[TimeEntry, ExpenseEntry],
    entry_type: str,
    index: int,
) -> str:
    """
    Format a single line in the LEDES invoice file -- given an entry and its type
    """
    created_at_date = invoice.created_at.strftime("%Y%m%d")

    timekeeper_name = f"{entry.user.last_name}, {entry.user.first_name}"
    timekeeper_initials = f"{entry.user.first_name[0]}{entry.user.last_name[0]}"

    earliest_date, latest_date = _get_billing_dates(invoice)

    common_fields = {
        "INVOICE_DATE": created_at_date,
        "INVOICE_NUMBER": str(invoice.id),
        "CLIENT_ID": str(invoice.matter.client_id),
        "LAW_FIRM_MATTER_ID": str(invoice.matter_id),
        "INVOICE_TOTAL": str(invoice.value["final_total"]),
        "BILLING_START_DATE": earliest_date.strftime("%Y%m%d"),
        "BILLING_END_DATE": latest_date.strftime("%Y%m%d"),
        "INVOICE_DESCRIPTION": invoice.matter.name,
        "LINE_ITEM_NUMBER": str(index),
    }

    if entry_type == "time":
        entry_specific_fields = {
            "EXP/FEE/INV_ADJ_TYPE": "F",
            "LINE_ITEM_NUMBER_OF_UNITS": str(entry.hours),
            "LINE_ITEM_ADJUSTMENT_AMOUNT": f"-{entry.fee}" if entry.comp == 1 else "0",
            "LINE_ITEM_TOTAL": str(entry.fee),
            "LINE_ITEM_DATE": entry.date.strftime("%Y%m%d"),
            "LINE_ITEM_TASK_CODE": "",
            "LINE_ITEM_EXPENSE_CODE": "",
            "LINE_ITEM_ACTIVITY_CODE": "A111",
            "LINE_ITEM_DESCRIPTION": entry.actions,
            "LINE_ITEM_UNIT_COST": str(entry.rate),
        }
    elif entry_type == "expense":
        entry_specific_fields = {
            "EXP/FEE/INV_ADJ_TYPE": "E",
            "LINE_ITEM_NUMBER_OF_UNITS": "1.0",
            "LINE_ITEM_ADJUSTMENT_AMOUNT": (
                f"-{entry.amount}" if entry.comp == 1 else "0"
            ),
            "LINE_ITEM_TOTAL": str(entry.amount),
            "LINE_ITEM_DATE": entry.date.strftime("%Y%m%d"),
            "LINE_ITEM_TASK_CODE": "",
            "LINE_ITEM_EXPENSE_CODE": "",
            "LINE_ITEM_ACTIVITY_CODE": "",
            "LINE_ITEM_DESCRIPTION": entry.description,
            "LINE_ITEM_UNIT_COST": str(entry.amount),
        }
    else:
        raise ValueError(f"Unknown entry type: {entry_type}")

    common_end_fields = {
        "TIMEKEEPER_ID": timekeeper_initials,
        "LAW_FIRM_ID": os.getenv("LAW_FIRM_ID"),
        "TIMEKEEPER_NAME": timekeeper_name,
        "TIMEKEEPER_CLASSIFICATION": "PT",
        "CLIENT_MATTER_ID": entry.matter.client_reference_id or "",
    }

    all_fields: Dict[str, str] = {
        **common_fields,
        **entry_specific_fields,
        **common_end_fields,
    }

    return "|".join(all_fields[field] for field in HEADER_FIELDS) + "[]"


def generate_ledes_98b(invoice: Invoice) -> NamedTemporaryFile:
    """
    Generate a LEDES 1998B invoice file for a given invoice
    """
    combined_entries = _get_combined_entries(invoice)

    with NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as file:
        # Write the LEDES header -- this is a constant string
        file.write(HEADER)

        for index, (entry, entry_type) in enumerate(combined_entries, start=1):
            ledes_line = _format_line(invoice, entry, entry_type, index)

            file.write(f"{ledes_line}\n")

    return file
