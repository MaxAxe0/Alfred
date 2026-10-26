# Alfred

> **Work in progress.** Alfred is an early prototype under active development. Many features described below as the vision are not built yet; see [Current features](#current-features) for what works today.

Alfred is a personal AI assistant that runs on your own hardware. It is local-first and private by default, with no per-use AI charges. The long-term goal is an assistant you can reach from anywhere (by text message, a desktop app, a voice call, or a live video session showing your screen) that carries out real tasks on your computer: opening apps, finding files, emailing them to you, or pushing work to GitHub. It will always ask before doing anything consequential.

Alfred is also meant to be modular and open source. The plan is an extension system so anyone can add tools and shape Alfred around their own tasks and preferences, with the core, not the extensions, enforcing permissions and approvals. Eventually Alfred will run full time on a dedicated machine, with a lightweight service on the PC carrying out approved actions.

It is also a hands-on learning project: each capability is built in small, tested steps, with safety enforced in code rather than trusted to the AI model.

**Today**, Alfred uses Python and a model running through Ollama to chat, read and create text files in a sandbox folder, and send plain-text email, with every file creation and email approved by you in the terminal. An isolated web-research setup is being built separately.

## Current features

- Chat with a local `qwen3.5:9b` model.
- Propose and send one plain-text Gmail message per turn after terminal approval (requires local Gmail setup).
- Keep conversation history for the current session.
- List files directly inside a designated `sandbox` folder.
- Read UTF-8 text files directly inside that folder, up to 10,000 bytes per file.
- Create new sandbox `.txt` files after an exact preview and terminal approval; existing files are never overwritten. Creation is limited to 10,000 characters per file.
- Reject file names that are not plain names (no folders, slashes, or colons) before touching the filesystem, and any resolved path outside the sandbox.

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
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
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

## Docker option

Start Docker Desktop with Linux containers and keep Ollama running natively. Prepare the local runtime paths:

```powershell
New-Item -ItemType Directory -Path sandbox -Force
New-Item -ItemType Directory -Path .local/gmail -Force
if (-not (Test-Path .local/profile.json)) {
    Copy-Item profile.example.json .local/profile.json
}
docker compose build
docker compose run --rm alfred
```

The Dockerfile packages public source and dependencies. `.dockerignore` excludes everything except allowlisted build files. Compose mounts `sandbox/` read/write, `.local/profile.json` read-only, and `.local/gmail/` read/write for token updates. Private files stay on the host and are not copied into the image. No host ports or Docker socket are exposed.

The app runs as a non-root user with a read-only root filesystem, temporary `/tmp`, one CPU, and 512 MB memory. These limits exclude native Ollama, which uses the host GPU and its existing model storage. `OLLAMA_HOST` points to `host.docker.internal:11434`; use `/status` to check it. This targets Docker Desktop on Windows/macOS.

Use the interactive command above rather than detached mode so approvals can read terminal input. `exit` stops Alfred; `--rm` removes the container while mounted data persists. Rebuild after editing code, `config.py`, or `system_prompt.txt`; private-profile changes need only a new run. Perform Gmail browser sign-in on the host, not inside the container.

Run image tests without network or private mounts:

```powershell
docker run --rm --network none alfred-app:local python -m unittest discover -s tests -v
```

Alfred's own container still has normal outbound networking for Ollama and Gmail. The isolated web-research setup is separate and not yet connected to Alfred; see [Web research (in progress)](#web-research-in-progress).

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

Type `exit` or press Ctrl+C at `You:` to quit cleanly. During a model request or tool execution, Ctrl+C cancels the current turn and returns to `You:`. Completed writes are not undone. At an approval prompt, Ctrl+C rejects that write; the assistant can then report the cancellation. During `/status`, Ctrl+C cancels just the status check. Ending terminal input also exits cleanly at `You:`. To unload the model from memory afterward:

```powershell
ollama stop qwen3.5:9b
```

## Chat commands

Commands are handled by Python and are not added to conversation history. `/status` queries Ollama for its installed models with a five-second request timeout; it does not generate an answer or load a model. Other commands do not contact Ollama.

| Command | Behavior |
| --- | --- |
| `/help` | Show the command list |
| `/status` | Show current settings, Ollama connectivity, and whether the selected model is installed |
| `/clear` | Clear conversation history while keeping Alfred's system identity; files are unaffected |
| `/think` | Show whether thinking is enabled |
| `/think on` | Enable thinking for subsequent model requests |
| `/think off` | Disable thinking for subsequent model requests |
| `exit` | End the program |

Thinking changes apply only to the running session and do not edit `config.py`. Restarting uses the `THINK` default again. `/clear` keeps the current thinking setting. Commands work at the `You:` prompt; at a file approval prompt, only `yes` approves and other input cancels.

## Identity and private preferences

`system_prompt.txt` contains Alfred's public identity and operating instructions. Keep it short and generic; it is sent as the system message on each model request.

Create `.local/profile.json` using `profile.example.json` as a template. This private file is ignored by Git:

```json
{
  "preferred_name": "",
  "timezone": "America/New_York",
  "default_email": ""
}
```

Enter your preferred name and your own default recipient address locally, then restart Alfred. Keep Gmail credentials and tokens in their separate `.local/gmail/` location; do not add them to the profile. Only these three profile fields are supported, and profiles are capped at 4,096 bytes. Timezone is currently descriptive context, not a scheduling feature or timezone conversion setting.

Python sends the preferred name, timezone, and a flag indicating whether a default recipient is set to the model. It does not add the default address to the standing context. For an explicit “email me” request, the model can request recipient `me`; Python resolves it to the private address and shows the actual destination for approval. Explicitly supplied addresses continue to work. If no default is set, Alfred asks for an address or reports the missing setting.

`/clear` preserves the startup identity and preferences while clearing chat history. Profile edits take effect after restart. This is a small startup profile, not automatic long-term memory; conversations are still held in memory only. The email address can still enter conversation context if you type it into chat yourself.

## Model settings

Edit `config.py` to change shared settings, then restart Alfred. `assistant.py` and `tools.py` both read this module. Current defaults:

| Setting | Default | Purpose |
| --- | --- | --- |
| `MODEL_NAME` | `"qwen3.5:9b"` | Local model; download it through Ollama before switching |
| `THINK` | `True` | Enables the separate thinking phase; may help complex tasks and can add latency |
| `CONTEXT_TOKENS` | `8192` | Request context budget for conversation, tool data, and generation |
| `MAX_TOOL_ROUNDS` | `6` | Maximum sequential tool rounds per user request |
| `REQUEST_TIMEOUT_SECONDS` | `120.0` | Network inactivity timeout for model requests; not a total task deadline |
| `MAX_READ_BYTES` | `10_000` | Maximum bytes read from one file |
| `MAX_WRITE_CHARS` | `10_000` | Maximum characters in a proposed new file |
| `MAX_EMAIL_BODY_CHARS` | `10_000` | Maximum characters in a proposed email body |

Use positive integers for the numeric limits. Bytes and characters are different units: a Unicode character may use multiple UTF-8 bytes. Large settings can increase resource use, and these per-file limits do not enforce an overall conversation budget.

The terminal's “Thinking...” message is a waiting indicator; it does not mean the model's separate thinking mode is enabled. The program currently displays the answer after generation finishes, rather than streaming it.

To check GPU placement while the model is loaded, run `ollama ps`. `100% GPU` means the model is entirely loaded on the GPU, not that GPU utilization stays at 100%. The first request after loading may take longer than subsequent requests.

Each successful model request prints its elapsed time as `[Timing] Ollama request: ... seconds`. This measures the full client request, including any model loading and waiting, rather than generation alone. Tool execution and time spent approving writes are excluded. A turn with several tool rounds prints a separate timing for each request.

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
| `tools.py` | Sandbox file listing, reading, and approved creation |
| `gmail_auth.py` | One-time, send-only Gmail sign-in run on the host; never sends mail |
| `gmail_tools.py` | Email validation, exact preview, terminal approval, and sending |
| `config.py` | Shared model settings and limits |
| `system_prompt.txt` | Public identity and operating instructions |
| `user_profile.py` | Validates private preferences and resolves the email alias |
| `profile.example.json` | Blank public template for the ignored private profile |
| `tests/` | Automated checks with temporary folders and mocked Ollama and Gmail |
| `requirements.txt` | Pinned Python package versions |
| `Dockerfile`, `compose.yaml`, `.dockerignore` | Alfred's container image, runtime settings, and build allowlist |
| `sandbox/` | Local test files; excluded from Git |
| `web_research/` | Isolated web-research setup (in progress); see below |
| `.gitignore` | Keeps environments, caches, sandbox data, credentials, private notes, and logs out of Git |
| `.gitattributes` | Keeps shell scripts in Linux line-ending format for containers |
| `LICENSE` | MIT license |

## Privacy and limitations

Keep credentials, account-specific preferences, and private runtime data under the Git-ignored `.local/` folder, never in public source or `config.py`. Tests use synthetic data. Credential files are ordinary local files, not encrypted by Alfred. Ignore rules do not remove previously tracked files or prevent force-adding them; review staged changes before pushing. If a credential is published, revoke it first, then address the Git history.

Before pushing, check what will be published and confirm private files are ignored:

```powershell
git status --short
git diff --cached --stat
git check-ignore .local/gmail/credentials.json .local/gmail/token.json
```

The configured model runs locally, without per-token API charges. File contents returned by tools become part of the conversation sent to local Ollama. History stays in Python memory and is lost when the program exits.

To disable Ollama's cloud features on Windows:

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_NO_CLOUD", "1", "User")
```

Quit and reopen Ollama after setting it. See [Ollama's configuration documentation](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features).

This is an early prototype. The sandbox is an application-level path restriction, not operating-system isolation. File contents are untrusted input and could influence model responses. Reads are limited to 10,000 bytes per file, but combined tool results and conversation history can still exceed the context budget. Errors beyond the handled failures can still stop the program. Use small, non-sensitive test files while developing.

The assistant can create new sandbox text files with approval. It cannot overwrite or edit existing files, control applications, attach files to emails, or upload to GitHub. Its conversational offers do not add capabilities beyond the implemented tools.

## Model request failures

If Ollama is unreachable, times out, or returns an error (such as a missing model), Alfred reports the problem and returns to `You:`. The incomplete turn is removed from history while earlier turns and Alfred's identity are preserved. Completed file writes remain on disk. Failed turns are not automatically retried.

Model requests use `REQUEST_TIMEOUT_SECONDS` from `config.py`. This is an HTTP connection/read/write/pool inactivity timeout, not a hard deadline for a complete turn. The separate `/status` check retains its five-second timeout. Restart after changing the setting.

## Run checks

From the project folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

These checks use temporary folders rather than your sandbox and do not contact Ollama or Gmail. They cover missing sandbox folders, file listing, invalid, network-style, and outside paths, read-size boundaries, approvals that must be typed exactly, no overwriting, email header and look-alike address rejection, private-profile validation, and recovery from simulated model-request failures and keyboard interruption. The web-research tests are run separately; see [Web research (in progress)](#web-research-in-progress).

## Gmail setup and sending

To configure your own Gmail account:

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/) and enable the Gmail API.
2. Configure Google Auth Platform branding. For personal Gmail, choose External audience, keep Testing enabled, and add the sending account as a test user.
3. Add only the scope `https://www.googleapis.com/auth/gmail.send` under Data Access.
4. Create a Desktop app OAuth client and download its JSON to `.local/gmail/credentials.json`. If offered an AI-agent designation, select it for Alfred.
5. Run the host-side command `.\.venv\Scripts\python.exe gmail_auth.py`, sign in as the sending account, and review consent. The token is saved to `.local/gmail/token.json`.

The authorization script does not send mail and is not exposed as a model tool. Keep credentials and tokens local, outside the sandbox. If the token is malformed or the requested scope changes, delete only `.local/gmail/token.json` and run the authorization again; keep the downloaded client file. To switch accounts, revoke the old authorization in your Google account, delete the token, and sign in again. Google may require renewed consent; External apps in Testing with Gmail scopes have seven-day refresh-token expiry. See [Google's setup guide](https://developers.google.com/workspace/gmail/api/quickstart/python) and [token-expiry documentation](https://developers.google.com/identity/protocols/oauth2#expiration).

Standalone plain-text sending is available with mandatory terminal approval:

```powershell
.\.venv\Scripts\python.exe gmail_tools.py
```

Enter one recipient, subject, and a one-line body. Review the exact preview; only `yes` sends. The sender is the Gmail account authorized during setup. It supports no attachments, Cc, or Bcc. `MAX_EMAIL_BODY_CHARS` in `config.py` limits the body (default 10,000). Gmail acceptance is not proof of inbox delivery. If the outcome is uncertain, inspect the sender's Sent folder before retrying. The assistant also offers `send_email_with_approval` as a model tool. Restart Alfred and ask, for example: `Send an email to recipient@example.com with subject Alfred test and body Hello from Alfred.` Replace that example address with your intended recipient. The model proposes the fields; Python validates and previews them and requires terminal approval. At most one email proposal is allowed per user turn, preventing model-driven retries within that turn. If a send is uncertain, check Sent before requesting another attempt. Credentials stay in the Git-ignored `.local/gmail/` folder.

## Web research (in progress)

The goal is for Alfred to search the web, read sources, and cite them, without the research code being able to reach the home network. The `web_research/` folder contains the groundwork. **It is not connected to Alfred yet.**

- **Sealed network:** the research container runs on a Docker network with no route out. Docker's ordinary networks can reach the local network, so this is enforced at the network level.
- **One guarded exit:** a [Smokescreen](https://github.com/stripe/smokescreen) proxy, built from source, is the only way out. It looks up each destination itself and refuses private, loopback, and cloud-metadata addresses, including public names that point at them. It uses public DNS and is rate-limited.
- **Safe fetcher (`web_research/fetcher.py`):** checks every URL and every redirect before contacting it (schemes, ports 80/443, local names, URL parsing tricks), refuses https-to-http downgrades, accepts only text pages, and enforces time and size limits, including against compression bombs.

Unit tests use fake websites and make no network requests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s web_research/tests -t web_research -v
```

Live checks run the fetcher in Docker through the real proxy. Set your router and PC addresses first (they are only used by the probes and stay out of Git):

```powershell
$env:ROUTER_IP = "192.168.1.1"; $env:PC_IP = "192.168.1.x"
docker compose -f web_research/compose.yaml run --rm fetcher
docker compose -f web_research/compose.yaml down
```

Next steps: turning pages into readable text, self-hosted search, a `/search` command, and citations.

## Future direction

- Improve error handling and visibility into tool execution.
- Add narrowly scoped actions with explicit permissions.
- Separate model hosting from a lightweight PC service.
- Run the model and task management on a dedicated Mac.
- Add secure remote access and selected application integrations.
- Allow optional paid models only with approval over data sharing and spending.

These are project goals, not implemented features.

## Disclaimer

This project was developed with the assistance of ChatGPT and Claude for research, planning, and implementation.

## License

Alfred's code is available under the [MIT License](LICENSE). Ollama, model weights, and other dependencies have their own licenses.
