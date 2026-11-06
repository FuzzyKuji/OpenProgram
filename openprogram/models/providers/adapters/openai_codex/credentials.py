"""ChatGPT subscription credential acquisition for the Codex provider.

CredentialProvider-first: the store is consulted, and on a miss the Codex
CLI's ``~/.codex/auth.json`` is imported once. A ``cli_delegated``
credential is read afresh from that file on every call.
"""
from __future__ import annotations

from pathlib import Path

from openprogram.models.auth.credential_provider import CredentialProvider
from openprogram.models.auth.types import (
    AuthConfigError,
    Credential,
    CredentialPool,
)

from . import auth_adapter


# ---------------------------------------------------------------------------
# Credential acquisition — CredentialProvider-first, with one-shot import fallback
# ---------------------------------------------------------------------------

def ensure_credential(manager: CredentialProvider, account_id: str) -> Credential:
    """Resolve a Codex credential for the given profile.

    Try the store first. If no pool exists, attempt a one-shot import
    from the Codex CLI's ``auth.json``; register the imported credential
    and retry acquisition (which may also refresh if the JWT is close to
    expiry). If neither path yields a credential, raise — the caller
    should render a "please run `codex login --device-auth`" message.
    """
    try:
        return manager.acquire_sync(auth_adapter.PROVIDER_ID, account_id)
    except AuthConfigError:
        pass  # fall through to import path

    imported = auth_adapter.import_from_codex_file(account_id=account_id)
    if imported is None:
        raise AuthConfigError(
            f"{auth_adapter.codex_auth_path()} not found or unusable. "
            "Run: codex login --device-auth",
            provider_id=auth_adapter.PROVIDER_ID,
            account_id=account_id,
        )
    manager.store.put_pool(CredentialPool(
        provider_id=auth_adapter.PROVIDER_ID,
        account_id=account_id,
        credentials=[imported],
    ))
    return manager.acquire_sync(auth_adapter.PROVIDER_ID, account_id)


def oauth_view(cred: Credential) -> Credential:
    """The OAuth credential this runtime calls with.

    A ``cli_delegated`` credential points read-only at the Codex CLI's
    ``auth.json``, which holds the ChatGPT OAuth tokens; it is read afresh on
    every call, so whoever refreshes that file (the Codex CLI, or another
    OpenProgram instance's own OAuth credential) keeps it current. A
    development instance gets only this delegated credential, since OAuth
    logins are never copied between instances."""
    if cred.kind != "cli_delegated":
        return cred
    store_path = (cred.payload.data or {}).get("store_path")
    viewed = auth_adapter.import_from_codex_file(
        account_id=cred.account_id,
        auth_path=Path(store_path) if store_path else None,
    )
    if viewed is None:
        raise AuthConfigError(
            f"{store_path or auth_adapter.codex_auth_path()} holds no ChatGPT "
            "OAuth login. Run: codex login --device-auth",
            provider_id=auth_adapter.PROVIDER_ID,
            account_id=cred.account_id,
        )
    return viewed


def account_id_for(cred: Credential) -> str:
    """Return the chatgpt_account_id for the credential.

    Prefers metadata (cheap, survives refreshes since _codex_refresh
    preserves metadata). Falls back to decoding the JWT."""
    account_id = cred.metadata.get("account_id")
    if isinstance(account_id, str) and account_id.strip():
        return account_id.strip()
    payload = cred.payload
    assert payload.kind in ("oauth", "device_code")
    return auth_adapter.extract_account_id(payload.auth_value)
