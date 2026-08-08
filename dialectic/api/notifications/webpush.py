# api/notifications/webpush.py - Web Push (VAPID) channel
"""
ARCHITECTURE: Web Push sender for the installed PWA — the browser's push
service (FCM/APNs-web/Mozilla) delivers even when the app is fully closed.
WHY: the four devices in daily use run the PWA; Expo push only serves the
(unshipped) native app. This channel is what makes a pocket buzz.
TRADEOFF: pywebpush is synchronous (requests) — sends run in a thread so the
message pipeline is never blocked on a push service.
"""

import asyncio
import json
import logging
import os
from typing import Optional

from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)

# Push payloads must stay well under the 4KB Web Push limit.
MAX_BODY_LENGTH = 200


def vapid_public_key() -> Optional[str]:
    return os.getenv("VAPID_PUBLIC_KEY")


def _vapid_config() -> Optional[dict]:
    private_key = os.getenv("VAPID_PRIVATE_KEY")
    subject = os.getenv("VAPID_SUBJECT")
    if not private_key or not subject:
        return None
    return {"private_key": private_key, "claims": {"sub": subject}}


def _send_one(subscription_info: dict, payload: str, config: dict) -> None:
    """Blocking single send — always called via asyncio.to_thread."""
    webpush(
        subscription_info=subscription_info,
        data=payload,
        vapid_private_key=config["private_key"],
        vapid_claims=dict(config["claims"]),  # pywebpush mutates the dict (adds exp)
        ttl=3600,
    )


async def send_web_notifications(
    db,
    recipient_user_ids: list[str],
    title: str,
    body: str,
    data: dict,
    tag: Optional[str] = None,
) -> dict:
    """
    Send a notification to every web-push subscription of the recipients.

    Prunes subscriptions the push service reports gone (404/410) — a user who
    uninstalled the PWA or cleared site data stops costing a request forever.
    """
    config = _vapid_config()
    if config is None:
        logger.warning("Web push disabled: VAPID_PRIVATE_KEY/VAPID_SUBJECT not set")
        return {"sent": 0, "errors": ["vapid_unconfigured"]}

    rows = await db.fetch(
        """SELECT id, endpoint, p256dh, auth FROM web_push_subscriptions
           WHERE user_id = ANY($1::uuid[])""",
        recipient_user_ids,
    )
    if not rows:
        return {"sent": 0, "errors": []}

    payload = json.dumps({
        "title": title,
        "body": body[:MAX_BODY_LENGTH],
        "tag": tag,
        "data": data,
    })

    sent = 0
    errors = []
    for row in rows:
        subscription_info = {
            "endpoint": row["endpoint"],
            "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
        }
        try:
            await asyncio.to_thread(_send_one, subscription_info, payload, config)
            sent += 1
            await db.execute(
                "UPDATE web_push_subscriptions SET last_success_at = NOW() WHERE id = $1",
                row["id"],
            )
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else None
            if status in (404, 410):
                await db.execute(
                    "DELETE FROM web_push_subscriptions WHERE id = $1", row["id"]
                )
                logger.info(f"Pruned dead web push subscription {row['id']} ({status})")
            else:
                logger.warning(f"Web push failed ({status}): {e}")
            errors.append({"subscription": str(row["id"]), "error": str(status or e)})
        except Exception as e:
            logger.exception("Unexpected web push error")
            errors.append({"subscription": str(row["id"]), "error": str(e)})

    return {"sent": sent, "errors": errors}
