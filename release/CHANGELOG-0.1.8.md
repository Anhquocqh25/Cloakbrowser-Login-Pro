# CloakBrowser Login Pro 0.1.8

Reliability and local security hardening. Cloak fingerprint launch path is unchanged.

## Changes

- Encrypt proxy credentials at rest with Windows DPAPI (`cbenc1:…` in SQLite and profile sidecars). In-memory / launch still uses plaintext so CloakBrowser flags and proxy bridge behave as before.
- Auto-migrate existing plaintext proxy URLs on startup (after DB snapshot).
- Profile health: WebRTC/DNS no longer report fake **pass**; they are **configured only (not verified)**.
- SQLite: `WAL`, `busy_timeout`, and connection timeout for concurrent UI/worker access.
- Timestamps: timezone-aware UTC helpers; trash/backup/proxy pool comparisons no longer mix naive/aware datetimes.
- Update downloader: only allow trusted GitHub download hosts.
- Activity log and trash UI avoid printing full proxy passwords.

## Not changed

- `browser/launcher.py` fingerprint / Cloak launch flags
- `services/fingerprint_engine.py`
- CloakBrowser binary integration

## Upgrade notes

1. First launch of 0.1.8 takes a normal startup DB snapshot, then encrypts proxy fields.
2. Encrypted secrets are bound to the Windows user profile (DPAPI). Copying `app.db` to another Windows account will not decrypt proxy passwords.
3. If a proxy fails to decrypt, re-enter it in the Proxies page.
