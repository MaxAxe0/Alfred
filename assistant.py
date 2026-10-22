from ollama import chat
from tools import list_files, read_file

messages = []

while True:
    user_input = input("You: ")

    if user_input.strip().lower() == "exit":
        break

    # Remember where this turn starts so a failed turn can be removed.
    turn_start = len(messages)
    messages.append({"role": "user", "content": user_input})

    # Allow several tool steps for one user request, with a fixed limit.
    for step in range(6):
        try:
            print("[Alfred] Thinking... waiting for Ollama.", flush=True)
            response = chat(
                model="qwen3:8b",
                messages=messages,
                tools=[list_files, read_file],
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
            else:
                result = "Error: unknown tool."

            if result.startswith("Error:"):
                print("[Tool]", result, flush=True)
            else:
                print("[Tool] Finished.", flush=True)

            messages.append({
                "role": "tool",
                "tool_name": call.function.name,
                "content": result,
            })

    else:
        print("[Alfred] Stopped after 6 tool rounds. Please narrow your request.")
