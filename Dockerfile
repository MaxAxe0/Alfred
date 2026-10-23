FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

# An ordinary user, rather than root, runs Alfred.
RUN groupadd --gid 10001 alfred \
    && useradd --uid 10001 --gid alfred --create-home alfred \
    && mkdir -p /app/sandbox /app/.local/gmail \
    && chown -R alfred:alfred /app

COPY --chown=alfred:alfred assistant.py config.py tools.py gmail_auth.py gmail_tools.py user_profile.py system_prompt.txt ./
COPY --chown=alfred:alfred tests/test_*.py ./tests/

USER alfred
CMD ["python", "assistant.py"]
