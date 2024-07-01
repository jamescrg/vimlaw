import os


def prepare_path(path: str) -> None:
    """
    Create a file if it doesn't exist for the given path.
    """
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)

        with open(path, "w") as file:
            file.write("")
