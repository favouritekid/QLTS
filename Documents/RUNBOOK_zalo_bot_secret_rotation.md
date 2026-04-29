# Runbook — Zalo Bot Webhook Secret Rotation

**Last updated**: 2026-04-29
**Owner**: Ops + Bot integration lead
**Frequency**: Every 90 days (or immediately on suspected leak)
**Estimated downtime**: 0 (rolling restart) — see Step 4 for grace-window strategy

---

## Why rotate?

The Zalo Bot webhook is authenticated solely by the shared secret in
the `X-Bot-Api-Secret-Token` header (compared timing-safe in
`zalo_bot_webhooks.py`). There is no replay defense, no timestamp, no
HMAC envelope. A leaked secret therefore allows arbitrary spoofed
webhook deliveries until the secret changes.

The `ZALO_BOT_WEBHOOK_SECRET` env var has no built-in expiry. Without
a periodic rotation, a leak becomes **forever**. F-3 (OWASP review,
2026-04-28) classified this as MEDIUM severity operational risk.

---

## When to rotate

| Trigger | Urgency |
|---|---|
| Scheduled 90-day rotation | Within the same week |
| Secret committed to git, slack, screenshot, etc. | Immediately |
| Unexplained webhook traffic spike | Immediately |
| Departure of staff with prod env access | Within 24h |

---

## Procedure

### Step 1 — Generate the new secret

```bash
# 32 random URL-safe bytes (43 chars, ~256 bits entropy)
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Save the output to your password manager **immediately** under
`zalo-bot-webhook-secret-NEW`. Do NOT paste into chat or commit.

### Step 2 — Stage the new secret on the server

> ⚠️ **READ THIS FIRST** — Dual-secret accept (`ZALO_BOT_WEBHOOK_SECRET_PREVIOUS`)
> is **NOT shipped in code as of 2026-04-29**. Setting that env var
> alone does nothing — the webhook only reads `ZALO_BOT_WEBHOOK_SECRET`.
>
> Pick one path:
>
> - **Path A — Brief downtime acceptable (default)**: skip the
>   `_PREVIOUS` line below and edit only `ZALO_BOT_WEBHOOK_SECRET`.
>   Plan for ~5–15s of 401 webhook responses while the Zalo OA console
>   propagates. Zalo retries on non-2xx, but the secret check rejects
>   401 retries — accept that a handful of inbound messages during the
>   gap will be dropped (operationally trivial: 10 webhook events/min
>   peak, retries clear in seconds).
> - **Path B — True zero-downtime**: ship the Appendix A code change
>   first (~1h PR), redeploy backend, then proceed with the
>   `_PREVIOUS` line below as a real dual-accept window.

```bash
# On the prod host
cd /opt/qlts
sudo nano .env.production
# Path A (dual-accept NOT yet shipped):
#   Set ZALO_BOT_WEBHOOK_SECRET=<new_secret_value>
# Path B (dual-accept already shipped per Appendix A):
#   Set ZALO_BOT_WEBHOOK_SECRET_PREVIOUS=<old_secret_value>
#   Set ZALO_BOT_WEBHOOK_SECRET=<new_secret_value>
```

### Step 3 — Update the Zalo OA console

1. Log in to <https://oa.zalo.me/manage/menu/bot> with the bot owner account.
2. Navigate to **Bot Settings → Webhook**.
3. Replace the secret token with the new value.
4. Save.

The Zalo console sends a verification probe to the webhook URL — it
must succeed under the new secret. If you applied Appendix A
dual-secret support, success is guaranteed.

### Step 4 — Restart backend (rolling)

```bash
# Apply the new env var into the running stack without dropping requests
docker compose up -d --no-deps backend
```

The `--no-deps backend` recreates only the backend container and
respects nginx upstream timeouts; in-flight requests complete on the
old container before the new one takes over.

### Step 5 — Verify

```bash
# 1. Should see no 401 webhook rejections in the last 5 minutes
docker compose logs backend --tail=200 | grep -i "Invalid secret"

# 2. Should see successful webhook events flowing
docker compose logs backend --tail=200 | grep -i "zalo_bot webhook event"
```

If you see sustained 401s, roll the OA console secret back to the old
value (Step 3 reversed) and investigate. The old secret is still
listed under `ZALO_BOT_WEBHOOK_SECRET_PREVIOUS` so the webhook will
keep accepting it during your roll-back.

### Step 6 — Drop the old secret (after 1 hour)

After 1 hour with no 401s and no operator complaints, remove the old
secret from `.env.production`:

```bash
# On prod host
cd /opt/qlts
sudo nano .env.production
# Delete the ZALO_BOT_WEBHOOK_SECRET_PREVIOUS line entirely
docker compose up -d --no-deps backend
```

This finalises the rotation. The old secret is now revoked.

### Step 7 — Update password manager + audit

1. Move `zalo-bot-webhook-secret-NEW` → `zalo-bot-webhook-secret`.
2. Move the previous-current value → `zalo-bot-webhook-secret-RETIRED-<YYYY-MM-DD>`.
3. Add a Calendar reminder for 90 days from today: "Rotate Zalo Bot webhook secret".

---

## Rollback

If anything goes wrong before Step 6:

1. Revert `.env.production` to the prior commit (`git stash` or `git checkout`).
2. Revert the OA console secret (Step 3).
3. `docker compose up -d --no-deps backend`.
4. Verify webhook traffic resumes (Step 5).

The old secret is still valid until you delete it from `.env.production`,
so rollback is non-destructive within the cut-over window.

---

## Appendix A — Optional dual-secret code support (recommended)

To enable true zero-downtime rotation, extend `zalo_bot_webhooks.py`:

```python
configured_secret = settings.ZALO_BOT_WEBHOOK_SECRET or ""
previous_secret = settings.ZALO_BOT_WEBHOOK_SECRET_PREVIOUS or ""
if not configured_secret:
    return Response(status_code=401, content="Webhook secret not configured")

presented = request.headers.get("X-Bot-Api-Secret-Token", "") or ""
if not (
    hmac.compare_digest(presented, configured_secret)
    or (previous_secret and hmac.compare_digest(presented, previous_secret))
):
    return Response(status_code=401, content="Invalid secret")
```

Add `ZALO_BOT_WEBHOOK_SECRET_PREVIOUS: str = ""` to `app/config.py`.
The previous secret defaults to empty so the dual-accept branch is a
no-op when not rotating. Leave the env var unset outside rotation
windows.

This change is NOT in scope for the F-3 runbook PR itself — the
runbook ships first; the code change can follow as a one-line PR if
ops decides they want truly zero-downtime rotation.

---

## Related findings

- F-3 (MEDIUM, OWASP review 2026-04-28) — Webhook secret never rotates → leak is forever.
- See also: `Backend_FastAPI/app/routers/zalo_bot_webhooks.py:117-128` for the secret-check implementation.
