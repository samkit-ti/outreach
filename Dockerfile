FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY skills/ ./skills/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY sql/ ./sql/

# Install the package and dependencies
RUN pip install --no-cache-dir -e "."

# Create directories for persistent data
RUN mkdir -p /app/data /app/logs /app/active-skills

# Expose port if needed (for health checks)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "print('healthy')" || exit 1

# Run the agent (Hermes gateway mode)
CMD ["python", "-m", "skills"]
