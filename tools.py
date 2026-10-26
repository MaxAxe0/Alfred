from pathlib import Path

import config


def filename_error(filename: str) -> str | None:
    """Return an error unless filename is a plain name, checked before any filesystem call.

    Slashes are refused first: on Windows, resolving a name like //server/share/x
    contacts that computer (and may send a login attempt) before any path check runs.
    """
    if ":" in filename:
        return "Error: filename cannot contain a colon."
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        return "Error: use a plain file name, directly inside the sandbox."
    return None


def list_files() -> list[str] | str:
    """List sandbox filenames, or return an error if the folder is unavailable."""
    folder = Path(__file__).parent / "sandbox"
    try:
        return [item.name for item in folder.iterdir() if item.is_file()]
    except FileNotFoundError:
        return "Error: the sandbox folder does not exist."
    except NotADirectoryError:
        return "Error: the sandbox path is not a folder."
    except OSError:
        return "Error: the sandbox folder could not be listed."

def read_file(filename: str) -> str:
    """Read a sandbox UTF-8 text file within the configured byte limit."""
    error = filename_error(filename)
    if error:
        return error

    try:
        folder = (Path(__file__).parent / "sandbox").resolve()
        file_path = (folder / filename).resolve()

        if file_path.parent != folder:
            return "Error: only files directly inside the sandbox are allowed."

        # Read one extra byte to detect oversize files without loading them fully.
        with file_path.open("rb") as file:
            data = file.read(config.MAX_READ_BYTES + 1)

        if len(data) > config.MAX_READ_BYTES:
            return f"Error: file exceeds the {config.MAX_READ_BYTES:,}-byte read limit."

        return data.decode("utf-8")
    except FileNotFoundError:
        return "Error: file not found."
    except IsADirectoryError:
        return "Error: the requested path is a folder."
    except UnicodeDecodeError:
        return "Error: the file is not valid UTF-8 text."
    except (OSError, ValueError):
        return "Error: the file could not be read."
    
def create_file(filename: str, content: str) -> str:
    """Create a new UTF-8 .txt file directly inside the sandbox."""
    error = filename_error(filename)
    if error:
        return error

    if len(content) > config.MAX_WRITE_CHARS:
        return f"Error: content exceeds the {config.MAX_WRITE_CHARS:,}-character limit."

    try:
        folder = (Path(__file__).parent / "sandbox").resolve()
        file_path = (folder / filename).resolve()

        if file_path.parent != folder:
            return "Error: only files directly inside the sandbox are allowed."

        if file_path.suffix.lower() != ".txt":
            return "Error: only .txt files are supported."

        with file_path.open("x", encoding="utf-8") as file:
            file.write(content)

        return f"Created {file_path.name}."
    except FileExistsError:
        return "Error: a file already exists at that location."
    except FileNotFoundError:
        return "Error: the sandbox folder does not exist."
    except (OSError, ValueError):
        return "Error: the file could not be created."


def create_file_with_approval(filename: str, content: str) -> str:
    """Ask the user to approve creating a new sandbox .txt file; never overwrite."""
    if not isinstance(filename, str) or not isinstance(content, str):
        return "Error: filename and content must be strings."

    # Validate the proposal before asking for approval.
    error = filename_error(filename)
    if error:
        return error
    if len(content) > config.MAX_WRITE_CHARS:
        return f"Error: content exceeds the {config.MAX_WRITE_CHARS:,}-character limit."

    try:
        folder = (Path(__file__).parent / "sandbox").resolve()
        destination = (folder / filename).resolve()
        if destination.parent != folder or destination.suffix.lower() != ".txt":
            return "Error: only .txt files directly inside the sandbox are allowed."
        if destination.exists():
            return "Error: a file already exists at that location."
    except (OSError, ValueError):
        return "Error: invalid destination."

    print("[Approval] Proposed file:", repr(str(destination)))
    # repr shows exact text with control characters escaped for the terminal.
    print("[Approval] Content (escaped):", repr(content))
    try:
        answer = input("Create this file? Type yes to approve: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return "Cancelled: file creation was not approved."

    if answer.strip().lower() != "yes":
        return "Cancelled: file creation was not approved."

    # The writer rechecks restrictions and uses exclusive creation.
    return create_file(filename, content)


if __name__ == "__main__":
    print(list_files())