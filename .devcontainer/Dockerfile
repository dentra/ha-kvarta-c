FROM mcr.microsoft.com/devcontainers/python:3.14

# ffmpeg нужен HA из default_config
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
