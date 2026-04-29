import asyncio
import base64
import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional


log = logging.getLogger(__name__)


class PushService:
    def __init__(
        self,
        *,
        redis_client,
        caregivers: dict,
        alert_engine,
        retention_audit_days: int,
        webpush_enabled: bool,
        vapid_public_key: str,
        vapid_private_key: str,
        vapid_claims_email: str,
    ) -> None:
        self.redis = redis_client
        self.caregivers = caregivers
        self.alert_engine = alert_engine
        self.retention_audit_days = retention_audit_days
        self.enabled = webpush_enabled
        self.vapid_public_key = vapid_public_key
        self.vapid_private_key = vapid_private_key
        self.vapid_claims_email = vapid_claims_email

    @staticmethod
    def subscriptions_key(staff_id: str) -> str:
        return f"push:sub:{staff_id}"

    def subscriptions_for_staff(self, staff_id: str) -> list[dict]:
        raw = self.redis.get(self.subscriptions_key(staff_id))
        if not raw:
            return []
        try:
            stored = json.loads(raw)
            subs = stored if isinstance(stored, list) else [stored]
            return [{**sub, "staff_id": staff_id} for sub in subs if isinstance(sub, dict)]
        except Exception:
            return []

    def all_subscriptions(self) -> list[dict]:
        subs = []
        for key in self.redis.scan_iter("push:sub:*"):
            staff_id = key.split("push:sub:", 1)[-1]
            raw = self.redis.get(key)
            if not raw:
                continue
            try:
                stored = json.loads(raw)
                if isinstance(stored, list):
                    subs.extend([{**sub, "staff_id": staff_id} for sub in stored if isinstance(sub, dict)])
                elif isinstance(stored, dict):
                    subs.append({**stored, "staff_id": staff_id})
            except Exception:
                pass
        return subs

    def register_subscription(self, staff_id: str, endpoint: str, p256dh: str, auth: str) -> dict:
        key = self.subscriptions_key(staff_id)
        raw = self.redis.get(key)
        subs: list[dict] = json.loads(raw) if raw else []
        subs = [sub for sub in subs if sub.get("endpoint") != endpoint]
        subs.append({"endpoint": endpoint, "p256dh": p256dh, "auth": auth})
        self.redis.set(key, json.dumps(subs))
        self.redis.expire(key, 86400 * 30)
        replayed = self.replay_active_alerts_for_staff(staff_id)
        log.info("Push subscribe: staff=%s endpoint=%s - replayed=%s", staff_id, endpoint[:40], replayed)
        return {"status": "subscribed", "staff_id": staff_id, "subscriptions": len(subs), "replayed_active_alerts": replayed}

    def unregister_subscription(self, staff_id: str, endpoint: str) -> dict:
        key = self.subscriptions_key(staff_id)
        raw = self.redis.get(key)
        if raw:
            subs = [sub for sub in json.loads(raw) if sub.get("endpoint") != endpoint]
            self.redis.set(key, json.dumps(subs))
        return {"status": "unsubscribed"}

    def send_web_push_sync(self, payload: dict, staff_ids: Optional[list[str]] = None) -> dict:
        target_ids = list(dict.fromkeys(staff_ids or []))
        result = {
            "enabled": self.enabled,
            "target_staff": target_ids,
            "expected_staff": len(target_ids),
            "subscriptions": 0,
            "sent": 0,
            "expired": 0,
            "errors": [],
            "staff": [],
        }
        if not self.enabled:
            return result
        try:
            from pywebpush import WebPushException, webpush
        except ImportError:
            log.warning("pywebpush non installe, push desactive")
            result["errors"].append("pywebpush non installe")
            return result

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        raw_key = self.vapid_private_key.replace("\\n", "\n").strip()
        if "BEGIN" not in raw_key:
            padding = "=" * ((4 - len(raw_key) % 4) % 4)
            key_bytes = base64.urlsafe_b64decode(raw_key + padding)
            private_value = int.from_bytes(key_bytes, "big")
            private_key_obj = ec.derive_private_key(private_value, ec.SECP256R1())
            pem = private_key_obj.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode("utf-8")
        else:
            pem = raw_key

        tmp = tempfile.NamedTemporaryFile(prefix="ehpad-vapid-", suffix=".pem", delete=False)
        tmp.write(pem.encode("utf-8"))
        tmp.flush()
        tmp.close()
        key_path = tmp.name

        try:
            subs = []
            if target_ids:
                for staff_id in target_ids:
                    staff_subs = self.subscriptions_for_staff(staff_id)
                    result["staff"].append({
                        "staff_id": staff_id,
                        "status": "pending" if staff_subs else "not_subscribed",
                        "subscriptions": len(staff_subs),
                        "sent": 0,
                        "expired": 0,
                        "errors": [],
                    })
                    subs.extend(staff_subs)
            else:
                subs = self.all_subscriptions()
                grouped = {}
                for sub in subs:
                    grouped.setdefault(sub.get("staff_id", "unknown"), 0)
                    grouped[sub.get("staff_id", "unknown")] += 1
                result["staff"] = [
                    {"staff_id": staff_id, "status": "pending", "subscriptions": count, "sent": 0, "expired": 0, "errors": []}
                    for staff_id, count in grouped.items()
                ]
            result["subscriptions"] = len(subs)

            staff_result = {row["staff_id"]: row for row in result["staff"]}
            for sub in subs:
                staff_id = sub.get("staff_id", "unknown")
                row = staff_result.get(staff_id)
                try:
                    webpush(
                        subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                        data=json.dumps(payload, ensure_ascii=False),
                        vapid_private_key=key_path,
                        vapid_claims={"sub": f"mailto:{self.vapid_claims_email}"},
                        ttl=120,
                    )
                    result["sent"] += 1
                    if row:
                        row["sent"] += 1
                        row["status"] = "sent"
                except WebPushException as exc:
                    code = getattr(getattr(exc, "response", None), "status_code", None)
                    if code in {404, 410}:
                        result["expired"] += 1
                        if row:
                            row["expired"] += 1
                            row["status"] = "expired"
                        key = self.subscriptions_key(staff_id)
                        raw = self.redis.get(key)
                        if raw:
                            try:
                                stored = json.loads(raw)
                                stored = [
                                    item for item in (stored if isinstance(stored, list) else [stored])
                                    if item.get("endpoint") != sub["endpoint"]
                                ]
                                self.redis.set(key, json.dumps(stored))
                            except Exception:
                                pass
                    else:
                        result["errors"].append(f"webpush {code or 'error'}")
                        if row:
                            row["errors"].append(f"webpush {code or 'error'}")
                            row["status"] = "error"
                except Exception:
                    log.exception("Erreur envoi Web Push")
                    result["errors"].append("erreur envoi webpush")
                    if row:
                        row["errors"].append("erreur envoi webpush")
                        row["status"] = "error"
        finally:
            try:
                os.unlink(key_path)
            except FileNotFoundError:
                pass
            except Exception as exc:
                log.warning("Impossible de supprimer le fichier VAPID temporaire %s: %s", key_path, exc)
        return result

    async def send_web_push_async(self, payload: dict, staff_ids: Optional[list[str]] = None) -> dict:
        return await asyncio.to_thread(self.send_web_push_sync, payload, staff_ids)

    @staticmethod
    def payload_for_alert(alert: dict) -> dict:
        level = int(alert.get("level") or 0)
        labels = {2: "Attention", 3: "Alerte", 4: "URGENCE", 5: "DANGER VITAL"}
        return {
            "title": f"N{level} {labels.get(level, 'Alerte')} - {alert.get('resident_name') or alert.get('resident_id')}",
            "body": f"Ch.{alert.get('room', '?')} - {alert.get('reason', 'Alerte active')}",
            "level": level,
            "resident_id": alert.get("resident_id", ""),
            "alert_id": alert.get("id", ""),
        }

    def target_staff_ids(self, alert: dict) -> list[str]:
        level = int(alert.get("level") or 0)
        if level < 2:
            return []
        ignored = {"dashboard", "samu_15", "son", "son_fort"}
        ids = []
        for item in alert.get("notified_staff") or []:
            if not isinstance(item, dict):
                continue
            staff_id = item.get("id")
            if staff_id and staff_id not in ignored and staff_id in self.caregivers and staff_id not in ids:
                ids.append(staff_id)
        if level in {2, 3}:
            caregiver = alert.get("caregiver")
            return [caregiver] if caregiver in self.caregivers else ids
        if level == 4:
            return [staff_id for staff_id in ("soignant_A", "soignant_B", "soignant_C", "chef_garde") if staff_id in self.caregivers]
        return [staff_id for staff_id in ("soignant_A", "soignant_B", "soignant_C", "chef_garde", "direction") if staff_id in self.caregivers]

    @staticmethod
    def delivery_key(alert_id: str) -> str:
        return f"push:delivery:{alert_id}"

    def record_delivery(self, alert: dict, result: dict, replay: bool = False) -> dict:
        alert_id = alert.get("id") or alert.get("alert_id")
        if not alert_id:
            return result
        delivered_staff = sum(1 for row in result.get("staff", []) if int(row.get("sent") or 0) > 0)
        summary = {
            "alert_id": alert_id,
            "resident_id": alert.get("resident_id"),
            "resident_name": alert.get("resident_name"),
            "level": int(alert.get("level") or 0),
            "target_staff": result.get("target_staff", []),
            "expected_staff": result.get("expected_staff", 0),
            "delivered_staff": delivered_staff,
            "subscriptions": result.get("subscriptions", 0),
            "sent": result.get("sent", 0),
            "expired": result.get("expired", 0),
            "errors": result.get("errors", []),
            "staff": result.get("staff", []),
            "replay": replay,
            "at": datetime.utcnow().isoformat() + "Z",
        }
        self.redis.setex(self.delivery_key(alert_id), self.retention_audit_days * 86400, json.dumps(summary, ensure_ascii=False))
        self.redis.lpush("push:audit", json.dumps(summary, ensure_ascii=False))
        self.redis.ltrim("push:audit", 0, 999)
        self.redis.expire("push:audit", self.retention_audit_days * 86400)
        return summary

    def delivery_summary(self, alert_id: str) -> Optional[dict]:
        raw = self.redis.get(self.delivery_key(alert_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def attach_delivery(self, alert: dict) -> dict:
        if not alert or not alert.get("id"):
            return alert
        delivery = self.delivery_summary(alert["id"])
        if delivery:
            alert = dict(alert)
            alert["push_delivery"] = delivery
        return alert

    def dispatch_alert_push_sync(self, alert: dict, replay: bool = False, forced_staff_ids: Optional[list[str]] = None) -> dict:
        level = int(alert.get("level") or 0)
        if level < 2:
            return {"enabled": self.enabled, "target_staff": [], "expected_staff": 0, "subscriptions": 0, "sent": 0, "expired": 0, "errors": [], "staff": []}
        staff_ids = forced_staff_ids or self.target_staff_ids(alert)
        result = self.send_web_push_sync(self.payload_for_alert(alert), staff_ids=staff_ids)
        return self.record_delivery(alert, result, replay=replay)

    async def dispatch_alert_push_async(self, alert: dict, replay: bool = False, forced_staff_ids: Optional[list[str]] = None) -> dict:
        return await asyncio.to_thread(self.dispatch_alert_push_sync, alert, replay, forced_staff_ids)

    def replay_active_alerts_for_staff(self, staff_id: str) -> int:
        sent = 0
        for alert in list(self.alert_engine.active_alerts.values()):
            data = alert.to_dict() if hasattr(alert, "to_dict") else dict(alert)
            if int(data.get("level") or 0) < 2:
                continue
            if staff_id not in self.target_staff_ids(data):
                continue
            result = self.dispatch_alert_push_sync(data, replay=True, forced_staff_ids=[staff_id])
            if result.get("sent", 0) > 0:
                sent += 1
        return sent
