"""Avisos push al móvil (Web Push + VAPID) cuando termina una descarga.

La descarga ya corre en el servidor (hilo de Render), así que sigue aunque el
móvil esté apagado o la app cerrada. Lo que faltaba era avisar: al terminar,
``notify_refresh_done`` manda una notificación a cada dispositivo suscrito y el
sistema operativo la entrega aunque la app no esté abierta.

Configuración (variables de entorno en Render; sin ellas todo queda inerte):

    VAPID_PUBLIC_KEY   clave pública en base64url (la que usa el navegador)
    VAPID_PRIVATE_KEY  clave privada en base64url (``python -m toolbox.web_push --gen``)
    VAPID_SUBJECT      ``mailto:tu@correo`` (opcional)

Suscripciones: tabla ``push_subscriptions`` en Supabase (se crea una vez):

    create table if not exists push_subscriptions (
        endpoint text primary key,
        subscription text not null,
        updated_at timestamptz not null default now()
    );

Sin Supabase se guardan en ``.cache/push_subscriptions.json``. Todo es a prueba
de fallos: un aviso que no sale nunca tumba ni retrasa la descarga.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
from typing import Any

from toolbox import cache as cache_module

logger = logging.getLogger("fantasy.web_push")

TABLE = "push_subscriptions"
_lock = threading.Lock()
_client: Any = None


def public_key() -> str:
    return os.getenv("VAPID_PUBLIC_KEY", "").strip()


def _private_key() -> str:
    return os.getenv("VAPID_PRIVATE_KEY", "").strip()


def enabled() -> bool:
    return bool(public_key() and _private_key())


def _subject() -> str:
    return os.getenv("VAPID_SUBJECT", "").strip() or "mailto:admin@example.com"


def generate_keys() -> tuple[str, str]:
    """Par VAPID nuevo (público, privado) en base64url sin relleno."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    raw_private = key.private_numbers().private_value.to_bytes(32, "big")
    raw_public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    return b64(raw_public), b64(raw_private)


# ---------------------------------------------------------------------------
# Almacén de suscripciones
# ---------------------------------------------------------------------------
def _remote() -> bool:
    return cache_module._use_remote(explicit_root=False)


def _supabase() -> Any:
    global _client
    with _lock:
        if _client is None:
            _client = cache_module.create_client(
                os.environ["SUPABASE_URL"].strip(), os.environ["SUPABASE_KEY"].strip()
            )
        return _client


def _local_path():
    return cache_module.cache_root() / "push_subscriptions.json"


def _read_local() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_local_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_local(data: dict[str, dict[str, Any]]) -> None:
    path = _local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _valid(sub: Any) -> bool:
    if not isinstance(sub, dict):
        return False
    keys = sub.get("keys")
    return (
        isinstance(sub.get("endpoint"), str)
        and sub["endpoint"].startswith("https://")
        and isinstance(keys, dict)
        and isinstance(keys.get("p256dh"), str)
        and isinstance(keys.get("auth"), str)
    )


def save_subscription(sub: Any) -> bool:
    if not _valid(sub):
        return False
    endpoint = sub["endpoint"]
    try:
        if _remote():
            _supabase().table(TABLE).upsert(
                {"endpoint": endpoint, "subscription": json.dumps(sub)}, on_conflict="endpoint"
            ).execute()
        else:
            with _lock:
                data = _read_local()
                data[endpoint] = sub
                _write_local(data)
        return True
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo guardar la suscripción push")
        return False


def remove_subscription(endpoint: str) -> None:
    try:
        if _remote():
            _supabase().table(TABLE).delete().eq("endpoint", endpoint).execute()
        else:
            with _lock:
                data = _read_local()
                if data.pop(endpoint, None) is not None:
                    _write_local(data)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo borrar la suscripción push")


def list_subscriptions() -> list[dict[str, Any]]:
    try:
        if _remote():
            rows = _supabase().table(TABLE).select("subscription").execute().data or []
            out = []
            for row in rows:
                try:
                    sub = json.loads(row.get("subscription") or "")
                except ValueError:
                    continue
                if _valid(sub):
                    out.append(sub)
            return out
        with _lock:
            return [s for s in _read_local().values() if _valid(s)]
    except Exception:  # noqa: BLE001
        logger.exception("No se pudieron leer las suscripciones push")
        return []


# ---------------------------------------------------------------------------
# Envío
# ---------------------------------------------------------------------------
def send_to_all(title: str, body: str, *, url: str = "/", tag: str = "fantasy") -> int:
    """Manda el aviso a todos los dispositivos. Devuelve cuántos lo aceptaron."""
    if not enabled():
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush no está instalado: no se envían avisos.")
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag}, ensure_ascii=False)
    sent = 0
    for sub in list_subscriptions():
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=_private_key(),
                vapid_claims={"sub": _subject()},
                ttl=24 * 3600,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                remove_subscription(sub["endpoint"])
            else:
                logger.warning("Aviso push rechazado (%s): %s", status, exc)
        except Exception:  # noqa: BLE001
            logger.exception("Fallo enviando un aviso push")
    return sent


def notify_refresh_done(*, ok: bool, detail: str | None = None) -> None:
    """Aviso de fin de descarga, en un hilo aparte para no frenar nada."""
    if not enabled():
        return
    if ok:
        title, body = "Fantasy actualizado", detail or "Datos nuevos listos. Toca para ver tu plan."
    else:
        title, body = "Fantasy: la actualización falló", detail or "Se mantiene la foto anterior."
    threading.Thread(
        target=send_to_all,
        args=(title, body),
        kwargs={"tag": "refresh-done"},
        name="web-push-notify",
        daemon=True,
    ).start()


if __name__ == "__main__":
    import sys

    if "--gen" in sys.argv:
        pub, priv = generate_keys()
        print(f"VAPID_PUBLIC_KEY={pub}")
        print(f"VAPID_PRIVATE_KEY={priv}")
    else:
        print("Uso: python -m toolbox.web_push --gen")
