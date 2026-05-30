# GitHub Actions Workflows

## CI (`ci.yml`)

Runs on every push to `main`/`develop` and every PR to `main`.

**Jobs:**
- `lint-and-test`: Ruff linter, Ruff formatter check, MyPy type checker, pytest with coverage
  - Runs on Python 3.11 and 3.12
- `shellcheck`: Lint all shell scripts
- `validate-configs`: Validate JSON and YAML files, check shell script executable permissions

## Deploy (`deploy.yml`)

Runs on every push to `main` (after CI passes).

**Requirements:**
- Repository secrets must be configured (see BRANCH_PROTECTION.md)
- Branch protection with required status checks

**Process:**
1. Checkout code
2. Setup SSH agent with VM private key
3. Add VM to known_hosts
4. Rsync code to `/opt/hermes-agent/repo/` on VM
5. Run deploy script on VM
6. Verify hermes-gateway service is active

**Notifications:**
- Slack notification on failure (if SLACK_WEBHOOK_URL is configured)
