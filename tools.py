from pathlib import Path


def list_files() -> list[str]:
    """List all files in the sandbox folder without reading it's contents."""
    folder = Path(__file__).parent / "sandbox"
    return [item.name for item in folder.iterdir() if item.is_file()]

def read_file(filename: str) -> str:
    """Read a UTF-8 text file directly inside the sandbox folder."""
    folder = (Path(__file__).parent / "sandbox").resolve()
    file_path = (folder / filename).resolve()

    if file_path.parent != folder:
        return "Error: only files directly inside the sandbox are allowed."

    try:
        return file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "Error: file not found."
    except IsADirectoryError:
        return "Error: the requested path is a folder."
    except UnicodeDecodeError:
        return "Error: the file is not valid UTF-8 text."
    except OSError:
        return "Error: the file could not be read."
    
if __name__ == "__main__":
    print(list_files())