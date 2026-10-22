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

while True:
    user_input = input("You: ")

    if user_input.strip().lower() == "exit":
        break

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
                think=config.THINK,
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
