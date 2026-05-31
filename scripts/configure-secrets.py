#!/usr/bin/env python3
"""Configure secrets for the outreach agent deployment.

This script helps:
1. Generate an Azure Service Principal for GitHub Actions OIDC
2. Upload .env secrets to Azure Files (backup storage for DR)
3. Configure Container App secrets

Usage:
    python scripts/configure-secrets.py --help
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], check: bool = True) -> str:
    """Run a shell command and return stdout."""
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=check
    )
    return result.stdout.strip()


def setup_github_oidc(
    subscription_id: str,
    resource_group: str,
    container_app: str,
    acr_name: str,
    repo: str,
) -> dict:
    """Set up OIDC federation between GitHub and Azure.

    Returns the app details needed for GitHub secrets.
    """
    print("=== Setting up GitHub OIDC for Azure ===")

    # Create app registration
    app_name = f"outreach-gha-{acr_name}"
    try:
        app_id = run([
            "az", "ad", "app", "list",
            "--display-name", app_name,
            "--query", "[0].appId", "-o", "tsv",
        ])
        if not app_id or app_id == "None":
            raise RuntimeError("Not found")
        print(f"  Found existing app: {app_id}")
    except subprocess.CalledProcessError:
        app_id = run([
            "az", "ad", "app", "create",
            "--display-name", app_name,
            "--query", "appId", "-o", "tsv",
        ])
        print(f"  Created app: {app_id}")

    # Get tenant ID
    tenant_id = run(["az", "account", "show", "--query", "tenantId", "-o", "tsv"])

    # Create service principal
    sp_id = run([
        "az", "ad", "sp", "list",
        "--filter", f"appId eq '{app_id}'",
        "--query", "[0].id", "-o", "tsv",
    ])
    if not sp_id or sp_id == "None":
        sp_id = run([
            "az", "ad", "sp", "create",
            "--id", app_id,
            "--query", "id", "-o", "tsv",
        ])
        print(f"  Created service principal: {sp_id}")

    # Assign roles
    print("  Assigning roles...")
    roles = [
        ("Contributor", resource_group),
        ("AcrPush", resource_group),
    ]
    for role, scope in roles:
        try:
            run([
                "az", "role", "assignment", "create",
                "--assignee", app_id,
                "--role", role,
                "--scope", f"/subscriptions/{subscription_id}/resourceGroups/{scope}",
            ])
            print(f"    ✓ {role}")
        except subprocess.CalledProcessError:
            print(f"    ⚠ {role} (may already exist)")

    # Create federated credential for GitHub Actions
    print("  Creating federated credentials...")
    for entity in ["repo", "environment"]:
        cred_name = f"github-{entity}"
        try:
            if entity == "repo":
                subject = f"repo:{repo}:ref:refs/heads/main"
            else:
                subject = f"repo:{repo}:environment:production"

            run([
                "az", "ad", "app", "federated-credential", "create",
                "--id", app_id,
                "--parameters", f"{{\"name\":\"{cred_name}\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"{subject}\",\"audiences\":[\"api://AzureADTokenExchange\"]}}",
            ])
            print(f"    ✓ {cred_name}")
        except subprocess.CalledProcessError:
            print(f"    ⚠ {cred_name} (may already exist)")

    return {
        "AZURE_CLIENT_ID": app_id,
        "AZURE_TENANT_ID": tenant_id,
        "AZURE_SUBSCRIPTION_ID": subscription_id,
        "AZURE_RESOURCE_GROUP": resource_group,
        "AZURE_CONTAINER_APP": container_app,
        "AZURE_ACR_NAME": acr_name,
    }


def upload_env_to_azure_files(
    storage_account: str,
    share_name: str,
    env_file: Path,
) -> None:
    """Upload .env file to Azure Files share."""
    print(f"\n=== Uploading {env_file} to Azure Files ===")

    if not env_file.exists():
        print(f"  ✗ File not found: {env_file}")
        return

    # Get storage key
    key = run([
        "az", "storage", "account", "keys", "list",
        "--account-name", storage_account,
        "--query", "[0].value", "-o", "tsv",
    ])

    # Upload via azcopy or az storage file upload
    run([
        "az", "storage", "file", "upload",
        "--account-name", storage_account,
        "--account-key", key,
        "--share-name", share_name,
        "--source", str(env_file),
        "--path", ".env",
    ])
    print(f"  ✓ Uploaded to {share_name}/.env")


def set_container_app_secrets(
    resource_group: str,
    container_app: str,
    secrets: dict[str, str],
) -> None:
    """Set secrets on the Container App.

    Note: Container App secrets are mounted as env vars.
    For many secrets, prefer Azure Files (.env file) instead.
    """
    print(f"\n=== Setting Container App secrets ===")

    for name, value in secrets.items():
        try:
            run([
                "az", "containerapp", "secret", "set",
                "--name", container_app,
                "--resource-group", resource_group,
                "--secrets", f"{name}={value}",
            ])
            print(f"  ✓ {name}")
        except subprocess.CalledProcessError as e:
            print(f"  ✗ {name}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Configure secrets for outreach agent"
    )
    parser.add_argument(
        "--setup-oidc",
        action="store_true",
        help="Create Azure AD app + federated credentials for GitHub Actions",
    )
    parser.add_argument(
        "--upload-env",
        type=Path,
        metavar="PATH",
        help="Upload .env file to Azure Files backup storage",
    )
    parser.add_argument(
        "--repo",
        default="samkitshah1262/outreach",
        help="GitHub repo (owner/repo)",
    )
    parser.add_argument(
        "--subscription",
        default="591f9701-9184-4c01-8e59-98d9923a2493",
        help="Azure subscription ID",
    )
    parser.add_argument(
        "--resource-group",
        default="outreach-rg-q9grl94w",
        help="Azure resource group",
    )
    parser.add_argument(
        "--container-app",
        default="outreach-agent",
        help="Container App name",
    )
    parser.add_argument(
        "--acr-name",
        default="outreachacrq9grl94w",
        help="Azure Container Registry name",
    )
    parser.add_argument(
        "--storage-account",
        default="outreachdataq9grl94w",
        help="Storage account name",
    )
    parser.add_argument(
        "--share-name",
        default="outreach-data",
        help="File share name",
    )

    args = parser.parse_args()

    if not any([args.setup_oidc, args.upload_env]):
        parser.print_help()
        return 0

    if args.setup_oidc:
        creds = setup_github_oidc(
            subscription_id=args.subscription,
            resource_group=args.resource_group,
            container_app=args.container_app,
            acr_name=args.acr_name,
            repo=args.repo,
        )
        print("\n=== GitHub Secrets to Configure ===")
        for k, v in creds.items():
            print(f"  {k}={v}")
        print("\nAdd these in GitHub: Settings → Secrets and variables → Actions")

    if args.upload_env:
        upload_env_to_azure_files(
            storage_account=args.storage_account,
            share_name=args.share_name,
            env_file=args.upload_env,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
