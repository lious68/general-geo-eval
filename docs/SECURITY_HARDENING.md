# Security maintenance

2026-10-15: business APIs require authentication by default. Service gateway maintains separate credential verification. Result backfills and score recalculation require administrator role. CORS is limited to the deployed HTTPS origins.

Passwords use salted scrypt. Legacy SHA256 accounts migrate after successful login; new passwords require 12 characters. Public administrator initialization is disabled. For a fresh installation run `venv/bin/python scripts/init_admin.py` from the repository root in a local console; the password is read with getpass, never a command argument. Existing administrator accounts are not reset.

Citation fetches resolve and validate public IPs on every redirect, connect to the validated address directly, verify TLS hostname/certificate, and bound response size and redirects. Unsupported schemes/ports and non-public addresses are rejected.

All public HTTP application paths redirect to HTTPS. Update clients to use HTTPS directly; redirects cannot undo a credential already sent over HTTP. ACME validation remains on HTTP. The GEO backend listens on loopback; the zhun SSH tunnel continues to reach it. Database files use mode600 and the service uses umask0077.

MODELVERSE_API_KEY must be provided through server environment configuration. Previously exposed credentials must be revoked at the provider; removing source defaults does not revoke keys or erase Git history. No credentials belong in this repository.

Verification: 82 backend tests passed; frontend audit reported zero advisories after compatible dependency updates; production-compatible build and evaluation hub browser checks passed. Admin HTTPS login and read APIs, anonymous denial, HTTP redirect and zhun tunnel health were verified. Certificate renewal configuration is retained.

Outstanding operations: provider-side credential revocation; rotate previously disclosed host passwords and verify SSH key access before disabling password authentication. Dedicated service-user migration and a full Python dependency audit remain follow-up work. Do not treat this as proof that every vulnerability has been eliminated.
