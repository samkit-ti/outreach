FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Install hermes-agent from source (this has cron, gateway, skills hub built-in)
# Using a specific ref for reproducibility; update to latest release as needed
RUN pip install --no-cache-dir \
    "git+https://github.com/NousResearch/hermes-agent.git#egg=hermes-agent" \
    "python-dotenv>=1.2.0" \
    "requests>=2.31.0" \
    "pyyaml>=6.0.1"

# Set up Hermes home directory (profiles, cron jobs, sessions live here)
ENV HERMES_HOME=/app/data/.hermes
ENV HERMES_DIR=/app/data
ENV HOME=/app

# Create Hermes home structure
RUN mkdir -p \
    $HERMES_HOME/cron \
    $HERMES_HOME/skills \
    $HERMES_HOME/sessions \
    $HERMES_HOME/logs \
    /app/skills \
    /app/data

# Copy our custom skills
COPY skills/ /app/skills/
COPY config/ /app/config/

# Hermes gateway entrypoint
CMD ["hermes", "gateway"]
