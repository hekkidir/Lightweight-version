"""
notify.py — best-effort failure notification.

alert(message, webhook) POSTs a JSON {"text": message} to a webhook (Slack /
Discord / generic). No-op when the webhook is empty. Uses stdlib urllib only —
no new dependency. Never raises: a failed alert must not mask the original error.
"""
import json
import logging
import urllib.request

log = logging.getLogger("notify")


def alert(message: str, webhook: str) -> None:
    if not webhook:
        return
    try:
        data = json.dumps({"text": message}).encode()
        req = urllib.request.Request(
            webhook, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)  # noqa: S310 (operator-supplied URL)
    except Exception:
        log.warning("alert webhook failed (original error still raised)")
