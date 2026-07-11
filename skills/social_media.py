"""Social Media Agent — Posts to X (Twitter) and LinkedIn using Azure Foundry + X API v2."""

import argparse
import json
import logging
import os
import random
import sys
from datetime import datetime
from pathlib import Path

import requests
import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Azure Foundry LLM helper
# ---------------------------------------------------------------------------


def _azure_chat(messages: list[dict], temperature: float = 0.8, max_tokens: int = 280) -> str:
    """Call Azure Foundry chat completions (Kimi-K2.6)."""
    base_url = os.environ.get("AZURE_FOUNDRY_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("AZURE_FOUNDRY_API_KEY", "")
    model = os.environ.get("DEFAULT_MODEL", "Kimi-K2.6")

    if not base_url or not api_key:
        raise RuntimeError("AZURE_FOUNDRY_BASE_URL and AZURE_FOUNDRY_API_KEY required")

    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# X (Twitter) API
# ---------------------------------------------------------------------------


def _x_client():
    """Initialize Tweepy Client with OAuth 1.0a user context."""
    try:
        import tweepy
    except ImportError:
        raise RuntimeError(
            "tweepy not installed. Run: pip install tweepy>=4.14.0"
        )

    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_SECRET"],
    )


def _x_user_id() -> str:
    """Get the authenticated user's ID."""
    client = _x_client()
    me = client.get_me()
    if not me or not me.data:
        raise RuntimeError("Could not retrieve X user ID")
    return str(me.data.id)


# ---------------------------------------------------------------------------
# Content generation
# ---------------------------------------------------------------------------

CONTENT_PILLARS = [
    "AI/ML Breakthroughs — latest research and real-world applications",
    "EdTech Insights — education technology trends, analysis, and predictions",
    "Company Updates — product launches, milestones, team news from PS3Labs",
    "Thought Leadership — opinion pieces on AI in education and healthcare",
    "Behind the Scenes — engineering challenges, lessons learned, build stories",
]

POSTING_STRATEGIES = {
    "x": {
        "tone": "Concise, punchy, technical but accessible. Emoji-friendly. Max 280 chars.",
        "style": "Short threads allowed for complex topics. Use hooks. Ask questions to drive engagement.",
    },
    "linkedin": {
        "tone": "Professional, insightful, longer-form, data-driven. Avoid buzzwords.",
        "style": "Start with a strong hook. Include 1-2 key insights. End with a question or call-to-action.",
    },
}


def _generate_post(platform: str, topic: str | None = None, profile: str = "ps3labs") -> str:
    """Generate social media content using Azure Foundry."""
    pillar = random.choice(CONTENT_PILLARS)
    strategy = POSTING_STRATEGIES.get(platform, POSTING_STRATEGIES["x"])

    topic_hint = f"\nFOCUS TOPIC: {topic}" if topic else ""

    system_msg = (
        f"You are the social media lead for PS3Labs (ps3labs.ai), an AI agent studio "
        f"building for education and healthcare in India. "
        f"Today's content pillar: {pillar}."
    )

    user_msg = (
        f"PLATFORM: {platform.upper()}\n"
        f"TONE: {strategy['tone']}\n"
        f"STYLE: {strategy['style']}\n"
        f"{topic_hint}\n"
        f"\nWrite a single post. No preamble, no quotes around the text. "
        f"Just the raw post content ready to publish."
    )

    max_tokens = 280 if platform == "x" else 1500
    content = _azure_chat(
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.8,
        max_tokens=max_tokens,
    )

    # Clean up common LLM artifacts
    content = content.strip().strip('"').strip("'").strip("`")
    if platform == "x" and len(content) > 280:
        content = content[:277] + "..."

    return content


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_create_post(platform: str, profile: str, topic: str | None = None) -> dict:
    """Generate and publish a post."""
    logger.info(f"Creating {platform} post for profile={profile}")

    content = _generate_post(platform, topic=topic, profile=profile)
    logger.info(f"Generated content ({len(content)} chars): {content[:100]}...")

    if platform == "x":
        client = _x_client()
        resp = client.create_tweet(text=content)
        tweet_id = resp.data["id"] if resp and resp.data else None
        logger.info(f"Posted tweet id={tweet_id}")
        return {"platform": "x", "tweet_id": tweet_id, "text": content}

    if platform == "linkedin":
        logger.warning("LinkedIn posting not yet implemented — credentials missing")
        return {"platform": "linkedin", "posted": False, "text": content}

    raise ValueError(f"Unknown platform: {platform}")


def cmd_engagement(platform: str, profile: str) -> dict:
    """Check recent engagement metrics."""
    logger.info(f"Checking {platform} engagement for profile={profile}")

    if platform == "x":
        client = _x_client()
        user_id = _x_user_id()
        tweets = client.get_users_tweets(
            id=user_id,
            max_results=10,
            tweet_fields=["public_metrics", "created_at"],
        )

        metrics = []
        if tweets and tweets.data:
            for t in tweets.data:
                m = t.public_metrics or {}
                metrics.append({
                    "id": str(t.id),
                    "created_at": str(t.created_at),
                    " impressions": m.get("impression_count", 0),
                    "likes": m.get("like_count", 0),
                    "replies": m.get("reply_count", 0),
                    "retweets": m.get("retweet_count", 0),
                    "text": t.text[:80] + "..." if len(t.text) > 80 else t.text,
                })

        logger.info(f"Retrieved metrics for {len(metrics)} tweets")
        return {"platform": "x", "tweets": metrics}

    if platform == "linkedin":
        logger.warning("LinkedIn engagement not yet implemented")
        return {"platform": "linkedin", "engagement": []}

    raise ValueError(f"Unknown platform: {platform}")


def cmd_respond_dms(platform: str, profile: str) -> dict:
    """Check and respond to DMs."""
    logger.info(f"Checking {platform} DMs for profile={profile}")

    if platform == "x":
        client = _x_client()
        user_id = _x_user_id()

        # X API v2 DM endpoints require special access (Elevated or Academic).
        # Basic tier often lacks DM read access. Log gracefully.
        try:
            dms = client.get_direct_message_events(
                participant_id=user_id,
                max_results=20,
            )
            logger.info(f"Retrieved {len(dms.data) if dms and dms.data else 0} DM events")
            return {"platform": "x", "dms_checked": True, "count": len(dms.data) if dms and dms.data else 0}
        except Exception as exc:
            logger.warning(f"DM access not available or failed: {exc}")
            return {"platform": "x", "dms_checked": False, "error": str(exc)}

    if platform == "linkedin":
        logger.warning("LinkedIn DM responses not yet implemented")
        return {"platform": "linkedin", "dms_checked": False}

    raise ValueError(f"Unknown platform: {platform}")


def cmd_send_connections(platform: str, profile: str) -> dict:
    """Send LinkedIn connection requests."""
    logger.info(f"Sending {platform} connections for profile={profile}")
    logger.warning("LinkedIn connection requests not yet implemented")
    return {"platform": platform, "connections_sent": 0}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

COMMANDS = {
    "create-post": cmd_create_post,
    "engagement": cmd_engagement,
    "respond-dms": cmd_respond_dms,
    "send-connections": cmd_send_connections,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PS3Labs Social Media Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in COMMANDS:
        p = sub.add_parser(name, help=name.replace("-", " "))
        p.add_argument("--platform", required=True, choices=["x", "linkedin"])
        p.add_argument("--profile", default="ps3labs")
        if name == "create-post":
            p.add_argument("--topic", default=None, help="Optional topic override")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Load .env if present (mirrors __main__.py behaviour)
    try:
        from dotenv import load_dotenv
        for p in [Path(".env"), Path("/app/.env")]:
            if p.exists():
                load_dotenv(p)
                break
    except ImportError:
        pass

    cmd_fn = COMMANDS[args.command]
    kwargs = {"platform": args.platform, "profile": args.profile}
    if args.command == "create-post" and args.topic:
        kwargs["topic"] = args.topic

    try:
        result = cmd_fn(**kwargs)
        print(json.dumps(result, indent=2, default=str))
        return 0
    except Exception:
        logger.exception("Command failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
