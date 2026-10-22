# Alfred

A local AI assistant built as a hands-on learning project. Alfred uses Python and a model running through Ollama to chat, list sandbox files, and read text files.

The goal is to understand how an assistant works: conversation history, tool calling, permissions, and eventually communication between a dedicated AI host and a lightweight PC service.

## Current features

- Chat with a local `qwen3.5:9b` model.
- Keep conversation history for the current session.
- List files directly inside a designated `sandbox` folder.
- Read UTF-8 text files directly inside that folder, up to 10,000 bytes per file.
- Create new sandbox `.txt` files after an exact preview and terminal approval; existing files are never overwritten. Creation is limited to 10,000 characters per file.
- Reject read requests whose resolved paths are outside the sandbox or inside subfolders.

The model requests tools; Python decides which function to execute and returns the result to the model.

## Requirements

- Python 3.13 (the version used during development).
- [Ollama](https://ollama.com/download), installed and running.
- Enough memory and disk space for [Qwen3.5 9B](https://ollama.com/library/qwen3.5:9b). Allow space for the model download and additional runtime memory; requirements depend on the model variant and context length.

## Setup on Windows

Clone this repository, then open PowerShell in its folder:

```powershell
git clone https://github.com/MaxAxe0/Alfred.git
cd Alfred
```

Create a virtual environment and install the Python client:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ollama
```

Download the local model:

```powershell
ollama pull qwen3.5:9b
```

Create the sandbox and a sample file:

```powershell
New-Item -ItemType Directory -Path sandbox -Force
Set-Content -Path sandbox\example.txt -Value "Hello from Alfred." -Encoding utf8
```

The sandbox is ignored by Git, so each installation needs its own folder and sample files.

## Run

Keep Ollama running, then start the assistant:

```powershell
.\.venv\Scripts\python.exe assistant.py
```

Try these prompts:

```text
What files are in my sandbox folder?
Read example.txt from my sandbox.
Create greeting.txt containing Hello from Alfred.
```

For file creation, review the destination and escaped content preview. Only typing `yes` at the Python confirmation prompt approves the write; other answers cancel it. Chat messages or file contents cannot supply this approval.

Type `exit` to quit normally, or press Ctrl+C to interrupt the program. To unload the model from memory afterward:

```powershell
ollama stop qwen3.5:9b
```

## Model settings

Alfred currently configures each Ollama request in `assistant.py` with:

| Setting | Value | Purpose |
| --- | --- | --- |
| `model` | `qwen3.5:9b` | Selects the downloaded local Qwen3.5 9B model |
| `think` | `False` | Disables the separate thinking phase to reduce waiting; complex tasks may benefit from enabling it |
| `options["num_ctx"]` | `8192` | Sets an 8,192-token context budget for conversation, tool data, and generation |

The terminal's “Thinking...” message is a waiting indicator; it does not mean the model's separate thinking mode is enabled. The program currently displays the answer after generation finishes, rather than streaming it.

To check GPU placement while the model is loaded, run `ollama ps`. `100% GPU` means the model is entirely loaded on the GPU, not that GPU utilization stays at 100%. The first request after loading may take longer than subsequent requests.

## How it works

1. Your message is added to the conversation history.
2. Python sends the history and available tool descriptions to local Ollama.
3. If the model requests a supported tool, Python executes it.
4. Python sends the tool result back to the model for an answer.

Each turn supports up to six sequential tool rounds. Tool activity and a waiting message are displayed in the terminal. If Ollama cannot be reached, the assistant removes the incomplete turn from history and returns to the input prompt.

## Project files

| File | Purpose |
| --- | --- |
| `assistant.py` | Interactive conversation and tool dispatch |
| `tools.py` | Sandbox file listing and reading functions |
| `sandbox/` | Local test files; excluded from Git |
| `.gitignore` | Excludes environments, caches, sandbox data, and `.env` |

## Privacy and limitations

The configured model runs locally, without per-token API charges. File contents returned by tools become part of the conversation sent to local Ollama. History stays in Python memory and is lost when the program exits.

To disable Ollama's cloud features on Windows:

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_NO_CLOUD", "1", "User")
```

Quit and reopen Ollama after setting it. See [Ollama's configuration documentation](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features).

This is an early prototype. The sandbox is an application-level path restriction, not operating-system isolation. File contents are untrusted input and could influence model responses. Reads are limited to 10,000 bytes per file, but combined tool results and conversation history can still exceed the context budget. Errors beyond the handled failures can still stop the program. Use small, non-sensitive test files while developing.

The assistant can create new sandbox text files with approval. It cannot overwrite or edit existing files, control applications, send email, or upload to GitHub. Its conversational offers do not add capabilities beyond the implemented tools.

## Future direction

- Improve error handling and visibility into tool execution.
- Add narrowly scoped actions with explicit permissions.
- Separate model hosting from a lightweight PC service.
- Run the model and task management on a dedicated Mac.
- Add secure remote access and selected application integrations.
- Allow optional paid models only with approval over data sharing and spending.

These are project goals, not implemented features.

## License

Alfred's code is available under the [MIT License](LICENSE). Ollama, model weights, and other dependencies have their own licenses.
