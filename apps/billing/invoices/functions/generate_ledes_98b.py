from tempfile import NamedTemporaryFile

from apps.billing.invoices.models import Invoice

LEDES_1998B_HEADER = """LEDES1998B[]
INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_MATTER_ID|INVOICE_TOTAL|BILLING_START_DATE|BILLING_END_DATE|INVOICE_DESCRIPTION|LINE_ITEM_NUMBER|EXP/FEE/INV_ADJ_TYPE|LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_ADJUSTMENT_AMOUNT|LINE_ITEM_TOTAL|LINE_ITEM_DATE|LINE_ITEM_TASK_CODE|LINE_ITEM_EXPENSE_CODE|LINE_ITEM_ACTIVITY_CODE|TIMEKEEPER_ID|LINE_ITEM_DESCRIPTION|LAW_FIRM_ID|LINE_ITEM_UNIT_COST|TIMEKEEPER_NAME|TIMEKEEPER_CLASSIFICATION|CLIENT_MATTER_ID[]
"""


def generate_ledes_98b(invoice: Invoice) -> NamedTemporaryFile:
    """
    Generate a LEDES file for the given invoice instance
    """
    created_at_date = invoice.created_at.strftime("%Y%m%d")
    client_reference_id = invoice.matter.client_reference_id or ""
    invoice_total = invoice.value["final_total"]

    # NOTE: Check billing dates
    billing_start_date = "20240101"
    billing_end_date = "20240131"

    # NOTE: Check task code, is L120 for time entries and E124 for expenses?
    # NOTE: Check activity code, is A111 for all entries?
    entry_code = "L120"
    entry_activity_code = "A111"

    # NOTE: Is this always the same?
    law_firm_id = 9395549

    with NamedTemporaryFile(suffix=".txt", delete=False) as ledes_file:
        # Write the LEDES header -- this is a constant string
        ledes_file.write(LEDES_1998B_HEADER.encode())

        # Enumerate through all time entries, but start at 1 instead of 0
        for index, entry in enumerate(invoice.timeentry_set.all(), start=1):
            item_date = entry.date.strftime("%Y%m%d")
            timekeeper_name = f"{entry.user.last_name}, {entry.user.first_name}"

            ledes_file.write(
                f"{created_at_date}|{invoice.id}|{client_reference_id}|{invoice.matter.name} - {invoice.matter.id}|"
                f"{invoice_total}|{billing_start_date}|{billing_end_date}|{invoice.comment}|{index}|F|{entry.hours}|"
                f"0|{entry.fee}|{item_date}|{entry_code}||{entry_activity_code}|JC|{entry.actions}|{law_firm_id}|"
                f"{entry.rate}|{timekeeper_name}|PT|[]\n".encode()
            )

        # TODO: Enumerate through all expenses

        ledes_file.seek(0)

    return ledes_file
