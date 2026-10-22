"""Shared Alfred settings. Restart the assistant after changing these values."""

MODEL_NAME = "qwen3.5:9b"
THINK = True
CONTEXT_TOKENS = 8192
MAX_TOOL_ROUNDS = 6
# Network inactivity timeout, not a total task deadline.
REQUEST_TIMEOUT_SECONDS = 120.0

# Reads count bytes; writes count Python string characters.
MAX_READ_BYTES = 10_000
MAX_WRITE_CHARS = 10_000
