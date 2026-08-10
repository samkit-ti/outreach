FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY worker ./worker
RUN pip install --no-cache-dir .
# SIGTERM → graceful drain (finish task in hand, deregister, exit)
STOPSIGNAL SIGTERM
CMD ["dm-worker"]
