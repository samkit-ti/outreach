"""Entry point for the outreach agent container.

Runs a lightweight cron scheduler. Loads secrets from HERMES_HOME/.env
and substitutes environment variables in config.yaml.
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from croniter import croniter

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv

    env_paths = [
        Path(os.environ.get("HERMES_HOME", "/app/.hermes")) / ".env",
        Path(os.environ.get("HERMES_DIR", ".")) / ".env",
        Path(".env"),
    ]
    for p in env_paths:
        if p.exists():
            load_dotenv(p)
            logging.getLogger(__name__).debug(f"Loaded .env from {p}")
            break
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Map of known skill modules to their run functions for direct invocation
SKILL_MAP = {
    "follow_up_scheduler": "skills.follow_up_scheduler",
    "pattern_extractor": "skills.pattern_extractor",
    "market_research": "skills.market_research",
    "inbox_classifier": "skills.inbox_classifier",
    "lead_enricher": "skills.lead_enricher",
    "outreach_drafter": "skills.outreach_drafter",
    "evolution_engine": "skills.evolution_engine",
    "crm_toolkit": "skills.crm_toolkit",
}


def _substitute_env_vars(obj):
    """Recursively substitute ${VAR:-default} patterns in config values."""
    if isinstance(obj, str):
        pattern = re.compile(r"\$\{([^}]+)\}")

        def replacer(match):
            expr = match.group(1)
            if ":-" in expr:
                var, default = expr.split(":-", 1)
                return os.environ.get(var, default)
            return os.environ.get(expr, match.group(0))

        return pattern.sub(replacer, obj)
    if isinstance(obj, list):
        return [_substitute_env_vars(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _substitute_env_vars(v) for k, v in obj.items()}
    return obj


def load_config() -> dict:
    """Load agent configuration from YAML with env var substitution."""
    paths = [
        Path("/app/config/config.yaml"),
        Path(os.environ.get("HERMES_DIR", ".")).parent / "config" / "config.yaml",
        Path("config/config.yaml"),
    ]
    for p in paths:
        if p.exists():
            logger.info(f"Loading config from {p}")
            with open(p) as f:
                raw = yaml.safe_load(f)
            return _substitute_env_vars(raw)
    logger.warning("No config.yaml found; using defaults")
    return {}


def run_subprocess(cmd: str) -> None:
    """Run a shell command and log output."""
    logger.info(f"Running command: {cmd}")
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        cwd="/app",
    )
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            logger.info(f"[{cmd}] {line}")
    if result.returncode != 0:
        logger.error(f"Command failed (exit {result.returncode}): {result.stderr}")
    else:
        logger.info(f"Command succeeded: {cmd}")


def run_skill_direct(name: str) -> bool:
    """Try to run a skill's main run_* function directly via import."""
    module_name = SKILL_MAP.get(name)
    if not module_name:
        return False

    func_guesses = [
        f"run_daily_{name}",
        f"run_weekly_{name}",
        f"run_{name}",
        "main",
    ]

    try:
        module = __import__(module_name, fromlist=[""])
        for func_name in func_guesses:
            if hasattr(module, func_name):
                logger.info(f"Running {module_name}.{func_name}()")
                result = getattr(module, func_name)()
                logger.info(f"Result: {result}")
                return True
        return False
    except Exception:
        logger.debug(f"Direct import failed for {name}", exc_info=True)
        return False


def execute_job(job: dict) -> None:
    """Execute a single cron job."""
    name = job["name"]
    cmd = job.get("command", "")

    logger.info(f"Triggering job: {name}")

    if run_skill_direct(name):
        return

    if cmd:
        run_subprocess(cmd)
    else:
        logger.warning(f"Job {name} has no command and no direct skill mapping")


def main() -> int:
    """Run the outreach agent scheduler."""
    logger.info("=" * 50)
    logger.info("PS3Labs Outreach Agent Scheduler starting up")
    logger.info("=" * 50)

    config = load_config()
    jobs = config.get("cron", {}).get("jobs", [])

    if not jobs:
        logger.warning("No cron jobs configured — entering keep-alive mode")
        while True:
            time.sleep(60)
        return 0

    logger.info(f"Loaded {len(jobs)} cron job(s)")
    for job in jobs:
        logger.info(f"  - {job['name']}: {job['schedule']} -> {job.get('command', 'direct')}")

    last_runs: dict[str, float] = {}
    for job in jobs:
        last_runs[job["name"]] = time.time()

    while True:
        now = time.time()
        for job in jobs:
            name = job["name"]
            schedule = job["schedule"]

            nxt = croniter(schedule, last_runs[name]).get_next(float)
            if nxt <= now:
                execute_job(job)
                last_runs[name] = now

        if int(now) % 300 < 30:
            logger.info("Scheduler heartbeat — all jobs registered")

        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
