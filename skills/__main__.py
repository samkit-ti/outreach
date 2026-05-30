"""Entry point for the outreach agent container.

Runs a lightweight cron scheduler based on config/config.yaml.
No hermes framework dependency — skills are self-contained.
"""

import importlib
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from croniter import croniter

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


def load_config() -> dict:
    """Load agent configuration from YAML."""
    paths = [
        Path("/app/config/config.yaml"),
        Path(os.environ.get("HERMES_DIR", ".")).parent / "config" / "config.yaml",
        Path("config/config.yaml"),
    ]
    for p in paths:
        if p.exists():
            logger.info(f"Loading config from {p}")
            with open(p) as f:
                return yaml.safe_load(f)
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


def run_skill_direct(name: str) -> None:
    """Try to run a skill's main run_* function directly via import."""
    module_name = SKILL_MAP.get(name)
    if not module_name:
        return False

    # Guess the function name from the module name
    func_guesses = [
        f"run_daily_{name}",
        f"run_weekly_{name}",
        f"run_{name}",
        "main",
    ]

    try:
        module = importlib.import_module(module_name)
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

    # Try direct skill invocation first (better logging, no subprocess overhead)
    if run_skill_direct(name):
        return

    # Fall back to subprocess
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

    # Track last run times to avoid duplicate triggers
    last_runs: dict[str, float] = {}
    for job in jobs:
        last_runs[job["name"]] = time.time()

    # Main loop — check every 30 seconds
    while True:
        now = time.time()
        for job in jobs:
            name = job["name"]
            schedule = job["schedule"]

            # croniter with last_runs gives us the next scheduled time after last_runs
            nxt = croniter(schedule, last_runs[name]).get_next(float)
            if nxt <= now:
                execute_job(job)
                last_runs[name] = now

        # Log a heartbeat every 5 minutes
        if int(now) % 300 < 30:
            logger.info("Scheduler heartbeat — all jobs registered")

        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
