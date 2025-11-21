FROM ghcr.io/ministryofjustice/hmpps-python:python3.13-alpine AS base

# initialise uv
COPY pyproject.toml .
RUN uv sync

COPY ./veracode_discovery.py .

RUN chown -R 2000:2000 /app
USER 2000

CMD [ "uv", "run", "python", "-u", "veracode_discovery.py" ]
