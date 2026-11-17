# ADR-008: Bearer-token authentication with rotating refresh sessions

- **Status:** Accepted
- **Date:** 2026-11-17
- **Decision owners:** BatchFlow project

## Context

BatchFlow exposes a React/TypeScript client and a FastAPI API. Protected operations require authenticated identity and backend-enforced role/record authorization. The design must support logout, session revocation and safe recovery from expired access tokens without storing long-lived bearer credentials in browser-accessible storage.

## Decision

Use short-lived signed JWT access tokens as bearer credentials and opaque, rotating refresh tokens backed by persisted session families.

### Access token

- Lifetime: 15 minutes.
- Sent only in the HTTP `Authorization: Bearer <token>` header.
- Claims include subject/user id (`sub`), session-family id (`sid`), issuer (`iss`), audience (`aud`), issued-at (`iat`), expiry (`exp`) and token id (`jti`).
- Verify signature, an explicit algorithm allowlist, issuer, audience, required claims and expiry. Never trust an algorithm selected by an untrusted token header.
- Keep access tokens in frontend memory only. Do not persist them in localStorage/sessionStorage, URLs, logs or analytics.
- Access tokens are stateless. Logout revokes refresh capability, but an already-issued access token can remain valid until its 15-minute expiry. This bounded revocation delay is accepted for the MVP.

### Refresh token and session family

- Generate a cryptographically random 256-bit opaque refresh token at login.
- Absolute session-family lifetime: 30 days from login; refresh does not extend this absolute expiry in the MVP.
- Store only the lowercase hexadecimal SHA-256 hash of each refresh token in `auth_refresh_tokens`; never store the raw token.
- Send the refresh token only in a `Secure; HttpOnly; SameSite=Lax` cookie scoped to the refresh endpoint. The API's protected business endpoints still require bearer access tokens.
- Rotate on every successful refresh in one database transaction: lock the session and presented token, mark the old token consumed, create the successor token row, and issue a new access JWT.
- Retain consumed token hashes. If a consumed refresh token is presented again, treat it as token reuse and revoke the entire session family. Require a new login.
- Logout revokes the session family and clears the refresh cookie.
- Refresh/logout endpoints validate the request Origin and use same-site deployment. Apply appropriate CSRF protections if deployment topology changes.

### Signing-key operations

- Signing keys, issuer and audience are environment/secret-manager configuration, never repository content.
- Use a maintained JWT library and a fixed algorithm allowlist.
- Support key identifiers and a bounded key-rotation overlap at least as long as the access-token lifetime.
- Do not log credentials or token values.

## Database impact

Add:
- `auth_sessions`: one row per login/session family, with user, creation, absolute expiry, last-use and revocation metadata.
- `auth_refresh_tokens`: one row per refresh-token generation, with unique token hash, session FK, issue/expiry, consumed timestamp and successor reference.
- Partial unique index on `auth_refresh_tokens(session_id)` where `consumed_at IS NULL`, ensuring one unconsumed refresh token per session family.
- Index for user session listing/revocation.

The full schema is specified in `docs/database-schema.md`.

## Consequences

**Positive**
- Short access-token lifetime limits exposure if an access token leaks.
- Refresh-token rotation and reuse detection provide session-family revocation.
- Logout and administrative session revocation are persisted and auditable.
- Browser JavaScript cannot directly read the refresh token.

**Trade-offs**
- Refresh and logout endpoints need cookie and Origin handling.
- Access JWT revocation is not immediate; the maximum normal delay is 15 minutes.
- Refresh rotation requires a transaction and retention of consumed token hashes for the session lifetime.
- Key management and clock synchronization become operational responsibilities.

## Required tests

1. Valid access token authenticates; expired, malformed, wrong-issuer, wrong-audience and invalid-signature tokens are rejected.
2. Unsupported JWT algorithms are rejected.
3. Refresh rotates exactly once under concurrent requests.
4. Reuse of a consumed refresh token revokes the complete session family.
5. Logout revokes refresh capability and clears the cookie.
6. An access token issued before logout expires within the documented 15-minute bound.
7. Inactive users and revoked/expired session families cannot refresh.
8. No raw access or refresh token appears in database rows, logs or error responses.
