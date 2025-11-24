FROM ghcr.io/ministryofjustice/hmpps-python:python3.13-alpine AS base

# initialise uv
COPY pyproject.toml .
RUN uv sync

COPY ./veracode_discovery.py .

CMD [ "uv", "run", "python", "-u", "veracode_discovery.py" ]
