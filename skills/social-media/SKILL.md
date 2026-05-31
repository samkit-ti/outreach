---
id: social-media
description: |
  Social media automation for X (Twitter) and LinkedIn.
  Supports posting, engagement, DMs, and connection requests
  for the PS3Labs brand profiles.
author: PS3Labs
version: 1.0.0
tags: [social, x, linkedin, marketing]
---

# Social Media Agent

Manages PS3Labs presence on X (Twitter) and LinkedIn.

## Platforms

### X (Twitter) — @ps3labs
- Post tweets (2-3x daily)
- Reply to mentions and DMs
- Engage with relevant accounts
- Follow industry leaders

### LinkedIn — PS3Labs Company Page
- Post articles and updates (3-4x weekly)
- Respond to comments and messages
- Send connection requests to target audience
- Engage with industry content

## Commands

### create-post
Generate and publish a post for a platform.

Usage:
```bash
# Create X post
python -m skills.social_media create-post --platform x --profile ps3labs

# Create LinkedIn post
python -m skills.social_media create-post --platform linkedin --profile ps3labs

# Custom topic
python -m skills.social_media create-post --platform x --topic "AI in education"
```

### engagement
Check and respond to engagement (mentions, comments, replies).

Usage:
```bash
python -m skills.social_media engagement --platform x --profile ps3labs
python -m skills.social_media engagement --platform linkedin --profile ps3labs
```

### respond-dms
Respond to direct messages.

Usage:
```bash
python -m skills.social_media respond-dms --platform x
python -m skills.social_media respond-messages --platform linkedin
```

### send-connections
Send connection requests on LinkedIn.

Usage:
```bash
python -m skills.social_media send-connections --platform linkedin --profile ps3labs
```

## Content Strategy

### Posting Schedule
- **X**: 8:00 AM, 2:00 PM daily
- **LinkedIn**: 9:00 AM Mon/Wed/Fri, 3:00 PM Tue/Thu

### Content Pillars
1. **AI/ML Breakthroughs** — Share latest research and applications
2. **EdTech Insights** — Education technology trends and analysis
3. **Company Updates** — Product launches, milestones, team news
4. **Thought Leadership** — Opinion pieces on AI in education
5. **Behind the Scenes** — Engineering challenges, lessons learned

### Tone Guidelines
- **X**: Concise, punchy, technical but accessible, emoji-friendly
- **LinkedIn**: Professional, insightful, longer-form, data-driven

## API Requirements

### X API v2
Required credentials:
- `X_API_KEY` — API Key
- `X_API_SECRET` — API Secret
- `X_ACCESS_TOKEN` — Access Token
- `X_ACCESS_SECRET` — Access Token Secret
- `X_BEARER_TOKEN` — Bearer Token (for read operations)

### LinkedIn API
Required credentials:
- `LINKEDIN_CLIENT_ID` — OAuth Client ID
- `LINKEDIN_CLIENT_SECRET` — OAuth Client Secret
- `LINKEDIN_ACCESS_TOKEN` — Access Token

## Safety Limits
- Max 50 tweets/day
- Max 100 LinkedIn connections/week
- Max 20 LinkedIn messages/day
- No automated liking (to avoid bot detection)
- Human review required for sensitive topics
