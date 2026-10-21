from ollama import chat
from tools import list_files, read_file

messages = []

while True:
    user_input = input("You: ")

    if user_input.strip().lower() == "exit":
        break

    messages.append({"role": "user", "content": user_input})

    response = chat(
        model="qwen3:8b",
        messages=messages,
        tools=[list_files, read_file],
    )

    # Keep the full message, including any tool requests.
    messages.append(response.message)

    if response.message.tool_calls:
        for call in response.message.tool_calls:
            if call.function.name == "list_files":
                result = str(list_files())
            elif call.function.name == "read_file":
                # Validate the filename supplied by the model before using it.
                filename = call.function.arguments.get("filename")
                if isinstance(filename, str):
                    result = read_file(filename)
                else:
                    result = "Error: filename must be a string."
            else:
                result = "Error: unknown tool."

            messages.append({
                "role": "tool",
                "tool_name": call.function.name,
                "content": result,
            })

        # Ask the model to answer using the tool results.
        response = chat(
            model="qwen3:8b",
            messages=messages,
        )

        messages.append(response.message)

    print("Assistant:", response.message.content)
