import config
from ollama import chat
from tools import list_files, read_file, create_file_with_approval

messages = [
    {
        "role": "system",
        "content": (
            "Your name is Alfred. You are the user's local AI assistant. "
            "When asked your name, introduce yourself as Alfred. "
            "Describe your capabilities accurately and only claim actions "
            "that your tools have actually completed."
        ),
    }
]

# Commands change this session only; config.py supplies the startup default.
think_enabled = config.THINK

while True:
    user_input = input("You: ")

    command = user_input.strip().lower()

    if command == "exit":
        break
    if not command:
        continue

    # Handle local commands before adding anything to model history.
    if command == "/help":
        print("/help          Show available commands")
        print("/clear         Clear chat history, keeping Alfred's identity")
        print("/think         Show the current thinking setting")
        print("/think on      Enable thinking for subsequent requests")
        print("/think off     Disable thinking for subsequent requests")
        print("exit           Quit Alfred")
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
    turn_start = len(messages)
    messages.append({"role": "user", "content": user_input})

    # Allow several tool steps for one user request, with a fixed limit.
    for step in range(config.MAX_TOOL_ROUNDS):
        try:
            print("[Alfred] Thinking...", flush=True)
            response = chat(
                model=config.MODEL_NAME,
                messages=messages,
                tools=[list_files, read_file, create_file_with_approval],
                think=think_enabled,
                options={"num_ctx": config.CONTEXT_TOKENS},
            )
        except ConnectionError:
            del messages[turn_start:]
            print("[Alfred] Cannot connect to Ollama. Open Ollama and try again.")
            print("[Alfred] This turn was removed from history. Any tools already run were not undone.")
            break

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
            else:
                result = "Error: unknown tool."

            if result.startswith(("Error:", "Cancelled:")):
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
