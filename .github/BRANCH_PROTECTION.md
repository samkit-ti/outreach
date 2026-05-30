# Branch Protection Setup (Manual Steps)

These settings must be configured through the GitHub web UI. They cannot be committed as code.

## Required Settings

### 1. Block Direct Push to Main

Go to: **Settings → Branches → Add rule**

**Branch name pattern:** `main`

**Protect matching branches:**
- [x] **Restrict pushes that create files larger than 100MB**
- [x] **Require a pull request before merging**
  - [x] **Require approvals:** 1
  - [x] **Dismiss stale PR approvals when new commits are pushed**
  - [x] **Require review from CODEOWNERS**
- [x] **Require status checks to pass before merging**
  - Required status checks:
    - `lint-and-test (3.11)`
    - `lint-and-test (3.12)`
    - `shellcheck`
    - `validate-configs`
- [x] **Require conversation resolution before merging**
- [x] **Require signed commits** (recommended)
- [x] **Include administrators** (even you should use PRs)

### 2. Environment Protection (for Deploy)

Go to: **Settings → Environments → New environment**

**Environment name:** `production`

**Protection rules:**
- [x] **Required reviewers:** 1 (yourself)
- [x] **Wait timer:** 0 minutes
- [x] **Deployment branches:** `main` only

### 3. Repository Secrets

Go to: **Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:

| Secret Name | Description | How to Obtain |
|---|---|---|
| `VM_SSH_PRIVATE_KEY` | Private key for SSH into Azure VM | Generate on VM: `ssh-keygen -t ed25519 -C "github-actions"` |
| `VM_HOST` | Azure VM public IP or DNS | From Azure Portal |
| `VM_USER` | SSH username | Default: `hermes` |
| `VM_HOST_KEY` | Host key for known_hosts | Run `ssh-keyscan <VM_HOST>` on the VM |
| `SLACK_WEBHOOK_URL` | Slack webhook for deploy notifications | Optional - create in Slack app settings |

### 4. Deploy Keys (Alternative to PAT for repo checkout)

If using deploy keys instead of GitHub Actions checkout token:

Go to: **Settings → Deploy keys → Add deploy key**

- **Title:** `GitHub Actions CI/CD`
- **Key:** Paste the public key (the one matching fingerprint `SHA256:YrKJtlsqw3glw2+JrqmenL2JgeijqRbHd+Cqnu4uJI4`)
- [x] **Allow write access** (needed for git-sync.sh pushes)

## Verification

After setup, test with:
1. Create a branch: `git checkout -b feature/test-ci`
2. Make a small change, commit, push
3. Open a PR to `main`
4. Verify CI checks run
5. Verify you cannot merge without approval
6. After merging, verify deploy action runs
