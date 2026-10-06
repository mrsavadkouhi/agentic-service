FROM python:3.12.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/agentic-service
COPY requirements.lock ./
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.lock \
    && useradd --uid 10001 --create-home agentic
COPY app ./app
COPY docs/department-tool-team-map.json ./docs/department-tool-team-map.json
COPY docs/servicedesk-catalog.json ./docs/servicedesk-catalog.json
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts/verify_runtime.py ./scripts/verify_runtime.py
COPY scripts/verify_tickets.py ./scripts/verify_tickets.py
USER agentic
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "app.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
