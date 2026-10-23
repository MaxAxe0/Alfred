from time import perf_counter
import config
from ollama import Client, ResponseError
from httpx import RequestError, TimeoutException
from tools import list_files, read_file, create_file_with_approval
from gmail_tools import send_email_with_approval

messages = [
    {
        "role": "system",
        "content": (
            "Your name is Alfred. You are the user's local AI assistant. "
            "When asked your name, introduce yourself as Alfred. "
            "Describe your capabilities accurately and only claim actions "
            "that your tools have actually completed. "
            "You can propose a plain-text email using send_email_with_approval. "
            "Ask for a recipient address if it is unknown; never invent one. "
            "Python requests approval before sending. Report cancellation or "
            "uncertainty accurately; never claim Gmail acceptance proves delivery."
        ),
    }
]

# Commands change this session only; config.py supplies the startup default.
think_enabled = config.THINK
status_client = Client(timeout=5.0)
chat_client = Client(timeout=config.REQUEST_TIMEOUT_SECONDS)

while True:
    try:
        user_input = input("You: ")
    except (KeyboardInterrupt, EOFError):
        print("\n[Alfred] Goodbye.")
        break

    command = user_input.strip().lower()

    if command == "exit":
        break
    if not command:
        continue

    # Handle local commands before adding anything to model history.
    if command == "/help":
        print("/help          Show available commands")
        print("/status        Show settings and check the Ollama connection")
        print("/clear         Clear chat history, keeping Alfred's identity")
        print("/think         Show the current thinking setting")
        print("/think on      Enable thinking for subsequent requests")
        print("/think off     Disable thinking for subsequent requests")
        print("exit           Quit Alfred")
        continue
    if command == "/status":
        print("[Status] Model:", config.MODEL_NAME)
        print("[Status] Thinking:", "on" if think_enabled else "off")
        print(f"[Status] Context budget: {config.CONTEXT_TOKENS:,} tokens")
        print("[Status] Tool-round limit:", config.MAX_TOOL_ROUNDS)
        print(f"[Status] Request inactivity timeout: {config.REQUEST_TIMEOUT_SECONDS:g} seconds")
        print(f"[Status] Read limit: {config.MAX_READ_BYTES:,} bytes per file")
        print(f"[Status] Write limit: {config.MAX_WRITE_CHARS:,} characters per file")
        print("[Status] Checking Ollama...", flush=True)
        try:
            installed = status_client.list()
            print("[Status] Ollama: reachable")
            selected = config.MODEL_NAME
            if ":" not in selected.rsplit("/", 1)[-1]:
                selected += ":latest"
            available = any(model.model == selected for model in installed.models)
            print("[Status] Selected model:", "installed" if available else "not installed")
            if not available:
                print(f"[Status] Download with: ollama pull {config.MODEL_NAME}")
        except KeyboardInterrupt:
            print("\n[Status] Check cancelled.")
        except TimeoutException:
            print("[Status] Ollama: check timed out (5-second request timeout)")
        except ConnectionError:
            print("[Status] Ollama: unreachable. Open Ollama and try again.")
        except ResponseError as error:
            print(f"[Status] Ollama returned an error: {error}")
        except RequestError:
            print("[Status] Ollama: connection check failed.")
        continue
    if command == "/clear":
        del messages[1:]
        print("[Alfred] Conversation cleared. Files and thinking setting are unchanged.")
        continue
    if command.startswith("/"):
        parts = command.split()
        if parts == ["/think"]:
            print("[Alfred] Thinking is", "on." if think_enabled else "off.")
        elif len(parts) == 2 and parts[0] == "/think" and parts[1] in ("on", "off"):
            think_enabled = parts[1] == "on"
            print("[Alfred] Thinking is now", "on." if think_enabled else "off.")
        else:
            print("[Alfred] Unknown command or arguments. Type /help for commands.")
        continue

    # Remember where this turn starts so a failed turn can be removed.
    email_proposed = False  # One email proposal per user turn; no model-driven resend.
    turn_start = len(messages)
    messages.append({"role": "user", "content": user_input})

    # Allow several tool steps for one user request, with a fixed limit.
    try:
        for step in range(config.MAX_TOOL_ROUNDS):
            try:
                print("[Alfred] Thinking...", flush=True)
                request_start = perf_counter()
                response = chat_client.chat(
                    model=config.MODEL_NAME,
                    messages=messages,
                    tools=[list_files, read_file, create_file_with_approval, send_email_with_approval],
                    think=think_enabled,
                    options={"num_ctx": config.CONTEXT_TOKENS},
                )
            except (ConnectionError, TimeoutException, ResponseError, RequestError) as error:
                # Handle expected request failures; programming errors still surface.
                if isinstance(error, TimeoutException):
                    print(f"[Alfred] Ollama request timed out (inactivity limit: {config.REQUEST_TIMEOUT_SECONDS:g} seconds).")
                elif isinstance(error, ConnectionError):
                    print("[Alfred] Cannot connect to Ollama. Open Ollama and try again.")
                elif isinstance(error, ResponseError):
                    print(f"[Alfred] Ollama error ({error.status_code}): {error.error}")
                    if error.status_code == 404:
                        print(f"[Alfred] Check MODEL_NAME and whether it is installed: ollama list")
                        print(f"[Alfred] Download the selected model with: ollama pull {config.MODEL_NAME}")
                else:
                    print("[Alfred] Communication with Ollama failed. Check the connection and try again.")

                del messages[turn_start:]
                print("[Alfred] This turn was removed from history. Any tools already run were not undone.")
                # Do not retry automatically: a tool may already have created a file.
                break

            elapsed = perf_counter() - request_start
            print(f"[Timing] Ollama request: {elapsed:.2f} seconds")

            # Keep the full message, including any tool requests.
            messages.append(response.message)

            if not response.message.tool_calls:
                print("Alfred:", response.message.content)
                break

            for call in response.message.tool_calls:
                if call.function.name == "list_files":
                    print("[Tool] Listing sandbox files...", flush=True)
                    result = str(list_files())
                elif call.function.name == "read_file":
                    # Validate the filename supplied by the model before using it.
                    filename = call.function.arguments.get("filename")
                    if isinstance(filename, str):
                        print(f"[Tool] Reading sandbox file: {filename!r}", flush=True)
                        result = read_file(filename)
                    else:
                        result = "Error: filename must be a string."
                elif call.function.name == "create_file_with_approval":
                    filename = call.function.arguments.get("filename")
                    content = call.function.arguments.get("content")
                    result = create_file_with_approval(filename, content)
                elif call.function.name == "send_email_with_approval":
                    if email_proposed:
                        result = "Error: only one email proposal is allowed per user turn. Ask the user before trying again; check Sent if the previous outcome was uncertain."
                    else:
                        email_proposed = True
                        recipient = call.function.arguments.get("recipient")
                        subject = call.function.arguments.get("subject")
                        body = call.function.arguments.get("body")
                        print("[Tool] Preparing an email for your approval...", flush=True)
                        result = send_email_with_approval(recipient, subject, body)
                else:
                    result = "Error: unknown tool."

                if result.startswith(("Error:", "Cancelled:", "Uncertain:")):
                    print("[Tool]", result, flush=True)
                else:
                    print("[Tool] Finished.", flush=True)

                messages.append({
                    "role": "tool",
                    "tool_name": call.function.name,
                    "content": result,
                })

        else:
            print(f"[Alfred] Stopped after {config.MAX_TOOL_ROUNDS} tool rounds. Please narrow your request.")
    except KeyboardInterrupt:
        del messages[turn_start:]
        print("\n[Alfred] Request cancelled. Returning to the prompt.")
        print("[Alfred] This turn was removed from history. Any tools already run were not undone.")
