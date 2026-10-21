# Northstar

A local AI assistant built as a hands-on learning project. Northstar uses Python and a model running through Ollama to chat, list sandbox files, and read text files.

The goal is to understand how an assistant works: conversation history, tool calling, permissions, and eventually communication between a dedicated AI host and a lightweight PC service.

## Current features

- Chat with a local `qwen3:8b` model.
- Keep conversation history for the current session.
- List files directly inside a designated `sandbox` folder.
- Read UTF-8 text files directly inside that folder.
- Reject read requests whose resolved paths are outside the sandbox or inside subfolders.

The model requests tools; Python decides which function to execute and returns the result to the model.

## Requirements

- Python 3.13 (the version used during development).
- [Ollama](https://ollama.com/download), installed and running.
- Enough memory and disk space for [Qwen3 8B](https://ollama.com/library/qwen3:8b). The model download is approximately 5.2 GB; runtime memory use is higher.

## Setup on Windows

Clone this repository, then open PowerShell in its folder:

```powershell
git clone https://github.com/MaxAxe0/Northstar.git
cd Northstar
```

Create a virtual environment and install the Python client:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ollama
```

Download the local model:

```powershell
ollama pull qwen3:8b
```

Create the sandbox and a sample file:

```powershell
New-Item -ItemType Directory -Path sandbox -Force
Set-Content -Path sandbox\example.txt -Value "Hello from Northstar." -Encoding utf8
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
```

Type `exit` to quit normally, or press Ctrl+C to interrupt the program. To unload the model from memory afterward:

```powershell
ollama stop qwen3:8b
```

## How it works

1. Your message is added to the conversation history.
2. Python sends the history and available tool descriptions to local Ollama.
3. If the model requests a supported tool, Python executes it.
4. Python sends the tool result back to the model for an answer.

Currently, each turn supports one batch of tool calls followed by an answer. Tasks that need several sequential tool decisions may require follow-up prompts.

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

This is an early prototype. The sandbox is an application-level path restriction, not operating-system isolation. File contents are untrusted input and could influence model responses. Large files are not yet limited, and some errors, such as losing the Ollama connection, can stop the program. Use small, non-sensitive test files while developing.

The assistant cannot currently create or modify files, control applications, send email, or upload to GitHub. Its conversational offers do not add capabilities beyond the implemented tools.

## Future direction

- Improve error handling and visibility into tool execution.
- Add narrowly scoped actions with explicit permissions.
- Separate model hosting from a lightweight PC service.
- Run the model and task management on a dedicated Mac.
- Add secure remote access and selected application integrations.
- Allow optional paid models only with approval over data sharing and spending.

These are project goals, not implemented features.

## License

Northstar's code is available under the [MIT License](LICENSE). Ollama, model weights, and other dependencies have their own licenses.
