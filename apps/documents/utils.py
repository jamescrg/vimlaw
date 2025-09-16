import re


def sanitize_filename(filename):
    """
    Sanitize a string to be safe for Linux filesystem use.
    """
    if not filename:
        return "unknown"

    # Remove null bytes and control characters
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename)

    # Remove forward slashes
    filename = filename.replace("/", "_")

    # Trim whitespace and dots from the end
    filename = filename.strip(" .")

    # Replace spaces with underscores
    filename = filename.replace(" ", "_")

    # Ensure it's not empty after sanitization
    if not filename:
        return "unknown"

    # Limit length to 255 bytes
    if len(filename.encode("utf-8")) > 255:
        filename = filename.encode("utf-8")[:250].decode("utf-8", errors="ignore")

    return filename
