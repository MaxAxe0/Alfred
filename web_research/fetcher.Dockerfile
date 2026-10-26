# R3d: the research fetcher, for live tests on the isolated network.
# Packages are installed at build time on the host; the running container has
# no route out except through the proxy.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt && python -m pip check

# Code stays owned by root, so the fetcher's own user cannot change it.
COPY net_policy.py fetcher.py live_check.py ./

RUN groupadd --gid 10002 research && useradd --uid 10002 --gid research --no-create-home research
USER research
CMD ["python", "live_check.py"]
