"""OAuth 2.0 con PKCE contra el Azure B2C de LALIGA Fantasy.

La cuenta de Google no tiene contraseña en este tenant: el flujo ROPC
(``B2C_1A_ResourceOwnerv2``) no crea sesión. El flujo válido es
Authorization Code + PKCE, política ``B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN``.

Cómo sacar el código inicial
-----------------------------
1. ``start_pkce_login()`` escribe el ``code_verifier`` en ``.cache/pkce.json``
   y devuelve la URL de autorización. Ábrela en el navegador.
2. Inicia sesión con Google. La app oficial redirige a un esquema que el
   navegador no abre:

       authredirect://com.lfp.laligafantasy?code=...&state=...

3. En las herramientas de red del navegador, con "Preserve log" activo, esa
   petición aparece como cancelada o fallida. Copia la URL completa, incluido
   el esquema ``authredirect://``. No copies el access token de otra petición.
4. Pasa esa URL a ``extract_authorization_code()`` o, desde la CLI,
   ``python cli.py auth exchange --redirect "<url>" --json``.
5. El ``code`` es de un solo uso y caduca en pocos minutos. Tiene que
   canjearse con el mismo ``code_verifier`` que generó la URL. Volver a
   ejecutar el paso 1 invalida el código que aún no hayas canjeado.

``python cli.py auth browser`` abre una ventana de Chrome o Edge con perfil
persistente, escucha la navegación a ``authredirect://`` y hace el canje.
Si esa redirección no se intercepta, se puede pegar la URL en la terminal
mientras la ventana sigue abierta.

El ``access_token`` dura 24 horas. El ``refresh_token`` dura 90 días.
``TokenManager`` renueva el primero con el segundo y reescribe ``.env``.
Cuando el refresh token caduca, Azure responde ``invalid_grant`` y hay que
repetir este login. No hay modo silencioso para eso.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from toolbox import project_root
from toolbox import api_meter
from toolbox.cache import cache_root

logger = logging.getLogger("fantasy.auth")

OAUTH_BASE = "https://login.laliga.es/laligadspprob2c.onmicrosoft.com/oauth2/v2.0"
AUTHORIZE_ENDPOINT = f"{OAUTH_BASE}/authorize"
TOKEN_ENDPOINT = f"{OAUTH_BASE}/token"
# Política del login social (Google). No es la política ROPC de usuario/contraseña.
SIGNIN_POLICY = "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN"
# Client id público de la app oficial. No es un secreto.
CLIENT_ID = "af88bcff-1157-40a0-b579-030728aacf0b"
REDIRECT_URI = "authredirect://com.lfp.laligafantasy"
SCOPE = "openid offline_access"
ACCESS_TOKEN_SKEW_SECONDS = 120
TOKEN_HTTP_TIMEOUT = 30.0
BROWSER_LOGIN_TIMEOUT_SECONDS = 300.0
BROWSER_PROFILE_DIRNAME = "browser_profile"
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_AUTH_REDIRECT_RE = re.compile(
    r"(authredirect://com\.lfp\.laligafantasy/?\?[^\"'\s<>\\]+)",
    re.IGNORECASE,
)
_HOST_REDIRECT_RE = re.compile(
    r"(com\.lfp\.laligafantasy/?\?[^\"'\s<>\\]*code=[^\"'\s<>\\]*)",
    re.IGNORECASE,
)

_CODE_RE = re.compile(r"^[A-Za-z0-9._~+/-]+=*$")


class AuthError(Exception):
    """Fallo de credenciales. El mensaje no incluye tokens."""

    def __init__(self, message: str, *, code: str = "auth_required") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TokenStatus:
    access_token_present: bool
    refresh_token_present: bool
    access_token_expires_at: str | None
    access_token_expired: bool


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().strip('"').strip("'")


def _bare_token(value: str) -> str:
    text = _clean(value)
    if text.lower().startswith("bearer "):
        return text[7:].strip()
    return text


def _quote_env(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded)


def jwt_payload(token: str) -> dict[str, Any] | None:
    """Lee el payload de un JWT sin verificar la firma. None si no es un JWT."""
    parts = token.split(".")
    if len(parts) < 2:
        return None
    try:
        parsed = json.loads(_b64url_decode(parts[1]))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def jwt_expiry(token: str) -> datetime | None:
    payload = jwt_payload(token)
    if payload is None:
        return None
    exp = payload.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    return datetime.fromtimestamp(float(exp), tz=timezone.utc)


def extract_authorization_code(redirect_or_code: str) -> str:
    """Extrae ``code`` de ``authredirect://com.lfp.laligafantasy?code=...``.

    También acepta el código pelado, por si la barra de direcciones ya lo
    separó. Rechaza cadenas vacías y URLs sin ese parámetro.
    """
    text = redirect_or_code.strip().strip('"').strip("'")
    if not text:
        raise AuthError("El código de autorización está vacío.", code="invalid_code")
    if "code=" in text or text.lower().startswith("authredirect:"):
        parsed = urllib.parse.urlparse(text)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
        if "code" not in query and "?" in text:
            query = urllib.parse.parse_qs(text.split("?", 1)[1], keep_blank_values=False)
        values = query.get("code") or []
        code = values[0].strip() if values else ""
        if not code:
            raise AuthError(
                "La redirección no contiene el parámetro code. "
                "Copia la URL authredirect:// completa desde la pestaña de red.",
                code="invalid_code",
            )
        return code
    if _CODE_RE.fullmatch(text):
        return text
    raise AuthError(
        "No se pudo extraer el code. Pega la URL authredirect://com.lfp.laligafantasy?code=...",
        code="invalid_code",
    )


def extract_state(redirect: str) -> str | None:
    text = redirect.strip()
    if "state=" not in text:
        return None
    parsed = urllib.parse.urlparse(text)
    query = urllib.parse.parse_qs(parsed.query)
    if "state" not in query and "?" in text:
        query = urllib.parse.parse_qs(text.split("?", 1)[1])
    values = query.get("state") or []
    if not values or not values[0].strip():
        return None
    return values[0].strip()


def make_pkce_pair() -> tuple[str, str]:
    """Devuelve ``(code_verifier, code_challenge)`` con método S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, _b64url(digest)


def build_authorize_url(code_challenge: str, state: str) -> str:
    params = {
        "p": SIGNIN_POLICY,
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": secrets.token_urlsafe(16),
    }
    return f"{AUTHORIZE_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _pkce_path() -> Path:
    directory = cache_root()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "pkce.json"


def _load_env() -> None:
    load_dotenv(project_root() / ".env", override=False)


def _redact(text: str) -> str:
    cleaned = re.sub(
        r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
        "[jwt]",
        text,
    )
    return cleaned[:400]


def write_env_values(updates: dict[str, str], *, path: Path | None = None) -> Path:
    """Sustituye claves en ``.env`` sin tocar el resto. No registra los valores.

    Si el fichero no se puede escribir (contenedor con el código en solo
    lectura, ``.env`` inyectado por ``env_file`` y propiedad de otro uid), el
    token recién canjeado **no se pierde**: se aplica al entorno del proceso,
    que es lo que usa ``TokenManager``. Se avisa por log en lugar de lanzar,
    porque un fallo de persistencia no debe tumbar un refresco que ya tiene
    credenciales válidas. El precio es que ese token no sobrevive a un
    reinicio; el ``refresh_token`` del ``.env`` sigue sirviendo para pedir otro.
    """
    path = path or (project_root() / ".env")
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in existing:
        stripped = line.strip()
        replaced = False
        for key, value in updates.items():
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                output.append(f"{key}={_quote_env(value)}")
                seen.add(key)
                replaced = True
                break
        if not replaced:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={_quote_env(value)}")
    try:
        path.write_text("\n".join(output) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "No se pudo escribir %s (%s). El token nuevo queda solo en memoria: "
            "el siguiente reinicio volverá a renovarlo con el refresh token.",
            path,
            exc.__class__.__name__,
        )
    for key, value in updates.items():
        os.environ[key] = value
    return path


def _post_token(form: dict[str, str]) -> dict[str, Any]:
    from toolbox.net import offline_mode

    if offline_mode():
        # Modo avión: renovar el token también es tráfico saliente. El login se
        # hace sin la variable puesta; aquí solo se avisa.
        raise AuthError(
            "Modo avión (FANTASY_OFFLINE=1): no se renueva el token contra LALIGA.",
            code="offline",
        )
    url = f"{TOKEN_ENDPOINT}?p={urllib.parse.quote(SIGNIN_POLICY)}"
    try:
        with api_meter.call(url=url, retry=form.get("grant_type") == "refresh_token") as probe:
            response = httpx.post(
                url,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=TOKEN_HTTP_TIMEOUT,
            )
            probe.status = response.status_code
    except httpx.HTTPError as exc:
        raise AuthError(f"No se pudo contactar con el proveedor de identidad: {exc}", code="network") from exc
    if response.status_code >= 400:
        detail = _redact(response.text)
        if response.status_code == 400 and ("invalid_grant" in detail or "AADB2C90090" in detail):
            if form.get("grant_type") == "authorization_code":
                raise AuthError(
                    "El código de login fue rechazado. Es de un solo uso y caduca en minutos. "
                    "Genera otra URL con `python cli.py auth url` y canjea la redirección nueva "
                    "sin volver a lanzar ese paso en medio.",
                    code="invalid_grant",
                )
            raise AuthError(
                "La sesión de LALIGA ha caducado o el refresh token ya no es válido "
                "(dura 90 días). Repite el login PKCE.",
                code="invalid_grant",
            )
        raise AuthError(f"El proveedor de identidad respondió HTTP {response.status_code}.", code="token_endpoint")
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise AuthError("El proveedor de identidad no devolvió JSON.", code="invalid_json") from exc
    if not isinstance(payload, dict):
        raise AuthError("La respuesta de token no es un objeto JSON.", code="invalid_json")
    return payload


def _store_token_payload(payload: dict[str, Any], *, previous_refresh: str) -> tuple[str, str]:
    access = _bare_token(str(payload.get("access_token") or payload.get("id_token") or ""))
    refresh = _bare_token(str(payload.get("refresh_token") or previous_refresh))
    if not access:
        raise AuthError("La respuesta no trae access_token.", code="invalid_json")
    if not refresh:
        raise AuthError("La respuesta no trae refresh_token.", code="invalid_json")
    write_env_values({"LALIGA_ACCESS_TOKEN": access, "LALIGA_REFRESH_TOKEN": refresh})
    return access, refresh


class TokenManager:
    """Lee los tokens de ``.env`` y los renueva antes de expirar o tras un 401."""

    def __init__(self) -> None:
        _load_env()
        self._access = _bare_token(os.getenv("LALIGA_ACCESS_TOKEN", ""))
        self._refresh = _bare_token(os.getenv("LALIGA_REFRESH_TOKEN", ""))
        self._lock = threading.Lock()

    def status(self) -> TokenStatus:
        with self._lock:
            expiry = jwt_expiry(self._access) if self._access else None
            expired = True
            if self._access and expiry is None:
                expired = False
            elif expiry is not None:
                expired = datetime.now(timezone.utc).timestamp() >= expiry.timestamp() - ACCESS_TOKEN_SKEW_SECONDS
            return TokenStatus(
                access_token_present=bool(self._access),
                refresh_token_present=bool(self._refresh),
                access_token_expires_at=expiry.isoformat() if expiry else None,
                access_token_expired=expired if self._access else True,
            )

    def authorization_value(self) -> str:
        token = self._current_or_refresh()
        return f"Bearer {token}"

    def force_refresh(self) -> str:
        """Canjea el refresh token aunque el access token aún no haya caducado."""
        with self._lock:
            access, _refresh = self._refresh_unlocked()
            return access

    def current_token(self) -> str:
        with self._lock:
            return self._access

    def refresh_after_401(self, stale_token: str | None = None) -> str:
        """Renueva solo si el token que falló sigue siendo el vigente.

        Varios workers pueden recibir 401 a la vez. El primero canjea el refresh
        token; los demás, al entrar al lock, ven que ``self._access`` ya cambió
        y reutilizan el nuevo sin una segunda llamada al proveedor.
        """
        with self._lock:
            if stale_token and self._access and self._access != stale_token:
                return self._access
            access, _refresh = self._refresh_unlocked()
            return access

    def _current_or_refresh(self) -> str:
        with self._lock:
            if self._access and not _is_expiring(self._access):
                return self._access
            access, _refresh = self._refresh_unlocked()
            return access

    def _refresh_unlocked(self) -> tuple[str, str]:
        if not self._refresh:
            raise AuthError(
                "No hay LALIGA_REFRESH_TOKEN en .env. "
                "Genera la URL con `python cli.py auth url`, inicia sesión con Google "
                "y canjea la redirección authredirect://com.lfp.laligafantasy?code=...",
                code="auth_required",
            )
        payload = _post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": self._refresh,
                "client_id": CLIENT_ID,
                "scope": SCOPE,
            }
        )
        self._access, self._refresh = _store_token_payload(payload, previous_refresh=self._refresh)
        return self._access, self._refresh


def _is_expiring(access_token: str, *, now: datetime | None = None) -> bool:
    expiry = jwt_expiry(access_token)
    if expiry is None:
        return False
    current = now or datetime.now(timezone.utc)
    return current.timestamp() >= expiry.timestamp() - ACCESS_TOKEN_SKEW_SECONDS


def start_pkce_login() -> dict[str, str]:
    """Genera la URL de login y persiste el verifier. No imprime el verifier."""
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(16)
    _pkce_path().write_text(
        json.dumps({"code_verifier": verifier, "state": state}),
        encoding="utf-8",
    )
    return {
        "authorize_url": build_authorize_url(challenge, state),
        "redirect_uri": REDIRECT_URI,
        "state": state,
    }


def complete_pkce_login(redirect_or_code: str) -> dict[str, Any]:
    """Canjea el código de la redirección y guarda los tokens en ``.env``."""
    path = _pkce_path()
    if not path.exists():
        raise AuthError(
            "No hay un login PKCE en curso. Ejecuta primero `python cli.py auth url`.",
            code="pkce_missing",
        )
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthError("El archivo PKCE está corrupto. Genera otra URL de login.", code="pkce_missing") from exc
    if not isinstance(stored, dict) or not stored.get("code_verifier"):
        raise AuthError("El archivo PKCE no tiene code_verifier.", code="pkce_missing")
    incoming_state = extract_state(redirect_or_code)
    expected_state = str(stored.get("state") or "")
    if incoming_state is not None and expected_state and incoming_state != expected_state:
        raise AuthError(
            "El state de la redirección no coincide con el login iniciado. No reutilices una URL antigua.",
            code="invalid_state",
        )
    code = extract_authorization_code(redirect_or_code)
    payload = _post_token(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": str(stored["code_verifier"]),
            "scope": SCOPE,
        }
    )
    access, refresh = _store_token_payload(payload, previous_refresh="")
    path.unlink(missing_ok=True)
    expiry = jwt_expiry(access)
    return {
        "ok": True,
        "command": "auth",
        "action": "exchange",
        "persisted_to": ".env",
        "access_token_expires_at": expiry.isoformat() if expiry else None,
        "refresh_token_present": bool(refresh),
        "access_token_ttl_hours": 24,
        "refresh_token_ttl_days": 90,
    }


def league_id_from_env() -> str | None:
    _load_env()
    value = _clean(os.getenv("LEAGUE_ID"))
    return value or None


_browser_lock = threading.Lock()


def callback_url(url: str) -> str | None:
    """Devuelve la redirección ``authredirect://`` si la URL lo es."""
    text = url.strip().strip('"').strip("'")
    if text.lower().startswith("authredirect://"):
        return text
    return None


def _candidate_texts(text: str) -> list[str]:
    raw = text.strip()
    if not raw:
        return []
    pieces = [raw]
    decoded = urllib.parse.unquote(raw)
    if decoded != raw:
        pieces.append(decoded)
        twice = urllib.parse.unquote(decoded)
        if twice != decoded:
            pieces.append(twice)
    return pieces


def _with_real_code(url: str) -> str | None:
    try:
        code = extract_authorization_code(url)
    except AuthError:
        return None
    if not code:
        return None
    return url


def find_auth_redirect(text: str) -> str | None:
    """Localiza ``authredirect://com.lfp.laligafantasy?code=`` dentro de cualquier texto.

    Acepta la URL directa, la misma cadena codificada y el host embebido en
    una cabecera, un evento CDP o un volcado JSON. Ignora otros ``code=``
    (por ejemplo el de Google) que no pertenecen a este esquema.
    """
    for piece in _candidate_texts(text):
        match = _AUTH_REDIRECT_RE.search(piece)
        if match and "code=" in match.group(1).lower():
            found = _with_real_code(match.group(1).rstrip(",;"))
            if found:
                return found
        host = _HOST_REDIRECT_RE.search(piece)
        if host:
            url = "authredirect://" + host.group(1).lstrip("/")
            if url.lower().startswith("authredirect://authredirect://"):
                url = url[len("authredirect://") :]
            found = _with_real_code(url.rstrip(",;"))
            if found:
                return found
        direct = callback_url(piece.strip().strip('"').strip("'"))
        if direct and "code=" in direct.lower():
            found = _with_real_code(direct)
            if found:
                return found
    return None


def _mentions_auth_code(text: str) -> bool:
    for piece in _candidate_texts(text):
        lowered = piece.lower()
        if "com.lfp.laligafantasy?code=" in lowered or "code=" in lowered:
            return True
    return False


def _public_leagues(details: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw = (details or {}).get("leagues") or []
    public: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and item.get("league_id"):
            public.append({"league_id": str(item["league_id"]), "name": item.get("name")})
    return public


def persist_detected_league() -> dict[str, Any]:
    """Si la cuenta tiene una sola liga, la escribe en ``LEAGUE_ID``."""
    from toolbox.net import FantasyHttpError, LaligaClient

    with LaligaClient() as client:
        try:
            found, _source = client.resolve_league(None, fresh=True)
        except FantasyHttpError as exc:
            if exc.code in {"league_required", "league_not_found"}:
                leagues = _public_leagues(exc.details)
                if exc.code == "league_not_found" and len(leagues) == 1:
                    found = leagues[0]
                else:
                    return {
                        "league_id": None,
                        "league_name": None,
                        "league_saved": False,
                        "leagues": leagues,
                    }
            else:
                raise AuthError(
                    "Los tokens ya están en .env, pero no pude leer las ligas de la cuenta.",
                    code="league_lookup",
                ) from exc
        else:
            found = {"league_id": str(found["league_id"]), "name": found.get("name")}
    league_id = str(found["league_id"])
    write_env_values({"LEAGUE_ID": league_id})
    return {
        "league_id": league_id,
        "league_name": found.get("name"),
        "league_saved": True,
        "leagues": [{"league_id": league_id, "name": found.get("name")}],
    }


def _import_playwright() -> Any:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise AuthError(
            "Falta Playwright. Instálalo con `python -m pip install playwright` "
            "y `python -m playwright install chromium`.",
            code="browser_missing",
        ) from exc
    return sync_playwright, PlaywrightError


def _launch_login_context(playwright: Any, playwright_error: type[Exception]) -> Any:
    """Abre el Chrome o Edge instalado, con perfil persistente y sin marca de automatización."""
    profile = cache_root() / BROWSER_PROFILE_DIRNAME
    profile.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    attempts: tuple[dict[str, str], ...] = ({"channel": "chrome"}, {"channel": "msedge"})
    for extra in attempts:
        try:
            return playwright.chromium.launch_persistent_context(
                str(profile),
                headless=False,
                locale="es-ES",
                no_viewport=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--start-maximized",
                ],
                ignore_default_args=["--enable-automation"],
                **extra,
            )
        except playwright_error as exc:
            last_error = exc
    detail = ""
    if last_error is not None:
        detail = " " + str(last_error).splitlines()[0][:180]
    raise AuthError(
        "No se pudo abrir Chrome ni Edge. Cierra otra ventana de este login si sigue abierta."
        + detail,
        code="browser_missing",
    )


def _attach_redirect_watch(context: Any, page: Any, consider: Any) -> None:
    """Escucha peticiones, redirecciones HTTP y el esquema ``authredirect://`` por CDP."""

    def on_request(request: Any) -> None:
        consider(getattr(request, "url", ""))

    def on_response(response: Any) -> None:
        consider(getattr(response, "url", ""))
        status = getattr(response, "status", None)
        if status not in _REDIRECT_STATUSES:
            return
        headers = getattr(response, "headers", None) or {}
        location = headers.get("location") or headers.get("Location") or ""
        consider(str(location))

    def on_frame(frame: Any) -> None:
        consider(getattr(frame, "url", ""))

    def on_cdp(event: Any) -> None:
        try:
            blob = json.dumps(event, ensure_ascii=False, default=str)
        except TypeError:
            blob = str(event)
        if _mentions_auth_code(blob):
            consider(blob)

    bound: set[int] = set()

    def bind(target: Any) -> None:
        ident = id(target)
        if ident in bound:
            return
        bound.add(ident)
        target.on("request", on_request)
        target.on("requestfailed", on_request)
        target.on("framenavigated", on_frame)
        target.on("response", on_response)
        target.on("popup", bind)
        try:
            client = context.new_cdp_session(target)
            client.send("Network.enable")
            client.on("Network.requestWillBeSent", on_cdp)
            try:
                client.send("Page.enable")
            except Exception:
                pass
            client.on("Page.frameScheduledNavigation", on_cdp)
        except Exception:
            return

    context.on("request", on_request)
    context.on("requestfailed", on_request)
    context.on("response", on_response)
    context.on("page", bind)
    bind(page)
    for existing in list(context.pages):
        bind(existing)


def _prompt_manual_redirect(store: Any, done: threading.Event) -> None:
    """Permite pegar ``authredirect://...`` en la terminal mientras el navegador sigue abierto."""
    if not sys.stdin or not sys.stdin.isatty():
        return
    sys.stderr.write(
        "\nSi el navegador no entrega la redirección, pega aquí la URL\n"
        "authredirect://com.lfp.laligafantasy?code=... y pulsa Enter.\n"
    )
    sys.stderr.flush()

    def reader() -> None:
        while not done.is_set():
            try:
                line = sys.stdin.readline()
            except Exception:
                return
            if line == "":
                return
            text = line.strip()
            if not text:
                continue
            found = find_auth_redirect(text)
            if not found:
                stripped = text.strip().strip('"').strip("'")
                try:
                    extract_authorization_code(stripped)
                except AuthError:
                    sys.stderr.write(
                        "No reconocí el code. Pega la URL completa authredirect://com.lfp.laligafantasy?code=...\n"
                    )
                    sys.stderr.flush()
                    continue
                found = stripped
            store(found)
            if done.is_set():
                return

    threading.Thread(target=reader, name="auth-redirect-paste", daemon=True).start()


def _raise_login_window(page: Any) -> None:
    try:
        page.bring_to_front()
    except Exception:
        return


def _capture_auth_redirect(timeout_seconds: float) -> str:
    """Abre la URL de login y devuelve el ``authredirect://`` en cuanto aparece."""
    sync_playwright, playwright_error = _import_playwright()
    started = start_pkce_login()
    captured: dict[str, str] = {}
    cancelled = {"value": False}
    closing = {"value": False}
    done = threading.Event()
    capture_lock = threading.Lock()

    def store(url: str) -> None:
        with capture_lock:
            if captured.get("url"):
                return
            captured["url"] = url
            done.set()

    def consider(url: object) -> None:
        if not isinstance(url, str):
            return
        found = find_auth_redirect(url)
        if found:
            store(found)

    with sync_playwright() as playwright:
        context = _launch_login_context(playwright, playwright_error)
        try:
            page = context.pages[0] if context.pages else context.new_page()

            def on_close() -> None:
                if closing["value"] or captured.get("url"):
                    return
                if any(not item.is_closed() for item in context.pages):
                    return
                cancelled["value"] = True
                done.set()

            page.on("close", on_close)
            _attach_redirect_watch(context, page, consider)
            _raise_login_window(page)
            try:
                page.goto(started["authorize_url"], wait_until="domcontentloaded", timeout=60_000)
            except playwright_error as exc:
                if not captured.get("url"):
                    raise AuthError(
                        "La ventana de login no pudo abrir la página de LALIGA.",
                        code="browser_missing",
                    ) from exc
            _raise_login_window(page)
            _prompt_manual_redirect(store, done)
            deadline = time.monotonic() + timeout_seconds
            while not done.is_set():
                if time.monotonic() >= deadline:
                    break
                open_pages = [item for item in context.pages if not item.is_closed()]
                if not open_pages:
                    cancelled["value"] = True
                    break
                for current in open_pages:
                    try:
                        consider(current.url)
                        for frame in current.frames:
                            consider(getattr(frame, "url", ""))
                    except playwright_error:
                        pass
                try:
                    open_pages[0].wait_for_timeout(200)
                except playwright_error:
                    if done.is_set() or captured.get("url"):
                        break
                    cancelled["value"] = True
                    break
            redirect = captured.get("url")
        finally:
            closing["value"] = True
            done.set()
            try:
                context.close()
            except Exception:
                pass
    if redirect:
        return redirect
    if cancelled["value"]:
        raise AuthError(
            "La ventana de login se cerró antes de elegir la cuenta de Google.",
            code="login_cancelled",
        )
    raise AuthError(
        "Se agotó la espera sin ver authredirect://. "
        "Vuelve a conectar y elige la cuenta de Google, o pega la URL en la terminal "
        "mientras la ventana está abierta.",
        code="login_timeout",
    )


def login_with_browser(*, timeout_seconds: float = BROWSER_LOGIN_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Abre el login, canjea el código y guarda tokens y ``LEAGUE_ID`` en ``.env``.

    La respuesta no incluye el código ni los tokens.
    """
    if timeout_seconds <= 0:
        raise AuthError("El tiempo de espera del login tiene que ser positivo.", code="invalid_code")
    if not _browser_lock.acquire(blocking=False):
        raise AuthError("Ya hay una ventana de login abierta.", code="login_in_progress")
    try:
        redirect = _capture_auth_redirect(timeout_seconds)
        exchanged = complete_pkce_login(redirect)
        league = persist_detected_league()
    finally:
        _browser_lock.release()
    exchanged["action"] = "browser"
    exchanged.update(league)
    return exchanged
