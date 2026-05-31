FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    bash \
    rsync \
    && rm -rf /var/lib/apt/lists/*

# Install hermes-agent from source (this has cron, gateway, skills hub built-in)
# Using a specific ref for reproducibility; update to latest release as needed
RUN pip install --no-cache-dir \
    "git+https://github.com/NousResearch/hermes-agent.git#egg=hermes-agent" \
    "python-dotenv>=1.2.0" \
    "requests>=2.31.0" \
    "pyyaml>=6.0.1"

# Set up Hermes home directory
# IMPORTANT: HERMES_HOME is mounted as EmptyDir so SQLite survives restarts.
# Azure Files (mounted at /app/backup) is used for cross-replica config DR.
ENV HERMES_HOME=/app/.hermes
ENV HERMES_DIR=/app
ENV HOME=/app
ENV BACKUP_INTERVAL=300
ENV BACKUP_DIR=/app/backup

# Copy our custom skills
COPY skills/ /app/skills/
COPY config/ /app/config/
COPY scripts/init-hermes.sh /app/scripts/init-hermes.sh
COPY scripts/init-crm-db.py /app/scripts/init-crm-db.py
RUN chmod +x /app/scripts/init-hermes.sh

# Create Hermes home structure (EmptyDir mount point)
RUN mkdir -p \
    $HERMES_HOME/cron \
    $HERMES_HOME/skills \
    $HERMES_HOME/active-skills \
    $HERMES_HOME/logs \
    /app/backup

# Entrypoint: init script restores persistent data, then runs hermes gateway
CMD ["/app/scripts/init-hermes.sh"]
