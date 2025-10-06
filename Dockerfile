FROM ghcr.io/astral-sh/uv:python3.13-alpine
WORKDIR /app

RUN addgroup -g 2000 appgroup && \
    adduser -u 2000 -G appgroup -h /home/appuser -D appuser

# initialise uv
COPY pyproject.toml .
RUN uv sync

COPY ./veracode_discovery.py .

USER 2000

CMD [ "uv", "run", "python", "-u", "veracode_discovery.py" ]
