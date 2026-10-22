"""Shared Alfred settings. Restart the assistant after changing these values."""

MODEL_NAME = "qwen3.5:9b"
THINK = False
CONTEXT_TOKENS = 8192
MAX_TOOL_ROUNDS = 6

# Reads count bytes; writes count Python string characters.
MAX_READ_BYTES = 10_000
MAX_WRITE_CHARS = 10_000
