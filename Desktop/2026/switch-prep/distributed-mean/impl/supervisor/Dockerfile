# Build context is impl/ (the parent directory) so the reaper can import the
# worker package's run_pairing — one pairing implementation, two triggers.
FROM python:3.12-slim
WORKDIR /app
COPY worker/pyproject.toml worker/pyproject.toml
COPY worker/worker worker/worker
RUN pip install --no-cache-dir ./worker docker
COPY supervisor supervisor
RUN touch supervisor/__init__.py
STOPSIGNAL SIGTERM
# WARNING (HLD §9): the compose file mounts /var/run/docker.sock into this
# container — root-equivalent on the host, demo-only. On AWS the reconciler is
# an IAM-scoped ecs:UpdateService call and no socket exists.
CMD ["python", "-m", "supervisor.main"]
