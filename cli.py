#!/usr/bin/env python3
"""Punto de entrada de la caja de herramientas.

``python cli.py <comando> --json`` escribe un único objeto JSON por stdout.
No hay trazas de depuración en esa salida.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from toolbox.analyzer import build_optimize_command
from toolbox.auth import AuthError, TokenManager, complete_pkce_login, login_with_browser, start_pkce_login
from toolbox.bidding import build_agent_command, build_flip_command, build_needs_command
from toolbox.net import FantasyHttpError, LaligaClient
from toolbox.normalize import SCHEMA_VERSION
from toolbox.scrapers import build_trends
_LOGIN_HELP = (
    "Abre authorize_url, entra con Google y copia la petición cancelada que empieza "
    "por authredirect://com.lfp.laligafantasy?code= . "
    "Canjéala con `python cli.py auth exchange --redirect <url> --json`."
)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Escribe un único objeto JSON por stdout.")
    common.add_argument("--fresh", action="store_true", help="Ignora la caché de lectura.")
    common.add_argument("--league", default=None, help="Id de liga. Por defecto, LEAGUE_ID.")

    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Caja de herramientas determinista de LALIGA Fantasy.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    helps = {
        "market": "Mercado del día.",
        "squads": "Plantillas, cláusulas y desbloqueos.",
        "trends": "Titularidad, forma y valor de mercado.",
        "optimize": "Once titular óptimo por ILP.",
        "flip": "Fichajes para especular y pujas de último segundo.",
        "needs": "Caja de los rivales y alertas de clausulazo.",
    }
    for name, help_text in helps.items():
        sub.add_parser(name, parents=[common], help=help_text)
    agent = sub.add_parser("agent", parents=[common], help="Ciclo: alineación, mercado y gobernanza.")
    agent.add_argument(
        "--execute",
        action="store_true",
        help="En fases posteriores, ejecuta solo lo que context/USER.md marca como silencioso.",
    )

    auth = sub.add_parser("auth", help="Login PKCE y estado de los tokens.")
    auth_sub = auth.add_subparsers(dest="auth_action", required=True)
    auth_sub.add_parser("url", parents=[common], help="Genera la URL de autorización.")
    exchange = auth_sub.add_parser("exchange", parents=[common], help="Canjea la redirección authredirect://.")
    exchange.add_argument("--redirect", required=True, help="URL authredirect://com.lfp.laligafantasy?code=...")
    browser = auth_sub.add_parser(
        "browser",
        parents=[common],
        help="Abre Chrome, captura authredirect:// y guarda los tokens.",
    )
    browser.add_argument(
        "--timeout",
        type=float,
        default=300,
        help="Segundos de espera para elegir la cuenta de Google.",
    )
    auth_sub.add_parser("status", parents=[common], help="Dice si el access token está caducado, sin imprimirlo.")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = build_parser().parse_args(argv)
    command = str(args.command)
    try:
        payload, code = _dispatch(args)
    except (AuthError, FantasyHttpError) as exc:
        payload, code = _error_payload(command, exc), 1
    except Exception as exc:
        payload, code = _error_payload(command, exc), 1
    try:
        if getattr(args, "json", False):
            _emit_json(payload)
        else:
            _render_human(payload)
    except BrokenPipeError:
        return 0
    return code


def _dispatch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    command = str(args.command)
    if command == "optimize":
        with LaligaClient() as client:
            return _coded(build_optimize_command(client, league=args.league, fresh=bool(args.fresh)))
    if command == "flip":
        with LaligaClient() as client:
            return _coded(build_flip_command(client, league=args.league, fresh=bool(args.fresh)))
    if command == "needs":
        with LaligaClient() as client:
            return _coded(build_needs_command(client, league=args.league, fresh=bool(args.fresh)))
    if command == "agent":
        with LaligaClient() as client:
            return _coded(
                build_agent_command(
                    client,
                    league=args.league,
                    fresh=bool(args.fresh),
                    execute=bool(getattr(args, "execute", False)),
                )
            )
    if command == "trends":
        with LaligaClient() as client:
            return build_trends(league=args.league, fresh=bool(args.fresh), laliga=client), 0
    if command == "auth":
        return _auth(args), 0
    if command == "market":
        with LaligaClient() as client:
            return client.market_document(args.league, fresh=bool(args.fresh)), 0
    if command == "squads":
        with LaligaClient() as client:
            return client.squads_document(args.league, fresh=bool(args.fresh)), 0
    return _error_payload(command, FantasyHttpError(f"Comando desconocido: {command}.", code="unknown_command")), 2


def _coded(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    return payload, 0 if payload.get("ok") else 1


def _auth(args: argparse.Namespace) -> dict[str, Any]:
    action = str(args.auth_action)
    if action == "url":
        started = start_pkce_login()
        return {
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "command": "auth",
            "action": "url",
            "authorize_url": started["authorize_url"],
            "redirect_uri": started["redirect_uri"],
            "instructions": _LOGIN_HELP,
        }
    if action == "exchange":
        exchanged = complete_pkce_login(str(args.redirect))
        exchanged["schema_version"] = SCHEMA_VERSION
        return exchanged
    if action == "browser":
        if not args.json:
            sys.stderr.write("Se abre una ventana de Chrome. Elige tu cuenta de Google.\n")
        logged_in = login_with_browser(timeout_seconds=float(args.timeout))
        logged_in["schema_version"] = SCHEMA_VERSION
        return logged_in
    status = TokenManager().status()
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": "auth",
        "action": "status",
        "access_token_present": status.access_token_present,
        "refresh_token_present": status.refresh_token_present,
        "access_token_expires_at": status.access_token_expires_at,
        "access_token_expired": status.access_token_expired,
    }


def _error_payload(command: str, exc: Exception) -> dict[str, Any]:
    status: int | None = None
    details: dict[str, Any] | None = None
    if isinstance(exc, AuthError):
        code = exc.code
    elif isinstance(exc, FantasyHttpError):
        code = exc.code
        status = exc.status
        details = exc.details or None
    else:
        code = "unexpected"
    error: dict[str, Any] = {"code": code, "message": str(exc), "status": status}
    if details:
        error["details"] = details
    return {"ok": False, "schema_version": SCHEMA_VERSION, "command": command, "error": error}


def _emit_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")


def _render_human(payload: dict[str, Any]) -> None:
    if not payload.get("ok"):
        message = str((payload.get("error") or {}).get("message") or "Error.")
        sys.stderr.write(message + "\n")
        return
    command = payload.get("command")
    if command == "market":
        _render_market(payload)
        return
    if command == "squads":
        _render_squads(payload)
        return
    if command == "trends":
        _render_trends(payload)
        return
    if command == "optimize":
        _render_optimize(payload)
        return
    if command == "flip":
        _render_flip(payload)
        return
    if command == "needs":
        _render_needs(payload)
        return
    if command == "agent":
        _render_agent(payload)
        return
    if command == "auth" and payload.get("action") == "url":
        sys.stdout.write(str(payload["authorize_url"]) + "\n")
        sys.stderr.write(_LOGIN_HELP + "\n")
        return
    if command == "auth" and payload.get("action") == "status":
        state = "caducado" if payload["access_token_expired"] else "vigente"
        sys.stdout.write(
            f"Access token {state}. Refresh token: "
            f"{'sí' if payload['refresh_token_present'] else 'no'}.\n"
        )
        return
    if command == "auth" and payload.get("action") == "exchange":
        sys.stdout.write("Tokens guardados en .env.\n")
        return
    if command == "auth" and payload.get("action") == "browser":
        sys.stdout.write("Tokens guardados en .env.\n")
        if payload.get("league_saved") and payload.get("league_id"):
            name = str(payload.get("league_name") or "").strip()
            suffix = f" ({name})" if name else ""
            sys.stdout.write(f"LEAGUE_ID={payload['league_id']}{suffix}\n")
            return
        leagues = payload.get("leagues") or []
        if leagues:
            sys.stdout.write("Hay varias ligas. Escribe una en LEAGUE_ID:\n")
            for league in leagues:
                if isinstance(league, dict):
                    sys.stdout.write(f"- {league.get('league_id')} {league.get('name') or ''}\n")
            return
        sys.stdout.write("No se detectó LEAGUE_ID.\n")
        return
    _emit_json(payload)


def _render_market(payload: dict[str, Any]) -> None:
    sys.stdout.write(f"Liga {payload['league_id']} · {payload['count']} fichajes en el mercado\n")
    for listing in payload["listings"]:
        label = listing.get("nickname") or listing.get("name") or listing.get("player_id") or "jugador"
        position = listing.get("position") or "-"
        price = _eur(listing.get("sale_price"))
        bid = _eur(listing.get("leading_bid"))
        sys.stdout.write(f"- {label} ({position}) · venta {price} · puja líder {bid}\n")


def _render_squads(payload: dict[str, Any]) -> None:
    sys.stdout.write(f"Liga {payload['league_id']} · {payload['count']} plantillas\n")
    for squad in payload["squads"]:
        name = squad.get("manager_name") or squad.get("fantasy_team_name") or squad["team_id"]
        marker = " · propia" if squad.get("is_self") else ""
        locked = [
            player
            for player in squad["players"]
            if player["clause_lock"].get("is_locked")
        ]
        sys.stdout.write(f"- {name}{marker} · {len(squad['players'])} jugadores · {len(locked)} cláusulas bloqueadas\n")
        for player in locked:
            label = player.get("nickname") or player.get("name") or player.get("player_id")
            lock = player["clause_lock"]
            sys.stdout.write(f"    {label} · {lock['local_date']} {lock['local_time']}\n")
        if squad.get("error"):
            sys.stdout.write(f"    error: {squad['error']}\n")


def _render_trends(payload: dict[str, Any]) -> None:
    partial = " · parcial" if payload.get("partial") else ""
    sys.stdout.write(
        f"Liga {payload.get('league_id')} · {payload.get('catalog_count')} jugadores{partial}\n"
    )
    sys.stdout.write("Aceleración alcista\n")
    for player in payload.get("rising") or []:
        label = player.get("nickname") or player.get("name") or player["player_id"]
        sys.stdout.write(
            f"- {label} · aceleración {player.get('acceleration')} · titular {player.get('p_titular')}\n"
        )
    sys.stdout.write("Aceleración bajista\n")
    for player in payload.get("falling") or []:
        label = player.get("nickname") or player.get("name") or player["player_id"]
        sys.stdout.write(f"- {label} · aceleración {player.get('acceleration')}\n")
    sys.stdout.write("Infravalorados frente a Transfermarkt\n")
    for player in (payload.get("undervalued") or [])[:5]:
        label = player.get("nickname") or player.get("name") or player["player_id"]
        sys.stdout.write(f"- {label} · ratio {player.get('value_ratio')} · gap {player.get('gap_eur')}\n")
    alerts = payload.get("availability") or []
    if alerts:
        sys.stdout.write("Alertas de la jornada\n")
        for player in alerts[:8]:
            label = player.get("nickname") or player.get("name") or player["player_id"]
            sanction = player.get("sanction") or {}
            flags = player.get("fitness") or ""
            if sanction.get("on_verge"):
                flags = (flags + " · 4 amarillas").strip(" ·")
            if sanction.get("suspended"):
                flags = (flags + " · sancionado").strip(" ·")
            sys.stdout.write(f"- {label} · {flags or 'alerta'}\n")


def _render_optimize(payload: dict[str, Any]) -> None:
    if payload.get("matchday_void"):
        reasons = ", ".join(payload.get("void_reasons") or [])
        sys.stdout.write(f"Jornada a 0 ({reasons}). Caja {_eur(payload.get('cash_eur'))}.\n")
        return
    sys.stdout.write(
        f"XI {payload.get('formation')} · puntos esperados {payload.get('expected_points')} · "
        f"caja {_eur(payload.get('cash_eur'))}\n"
    )
    for player in payload.get("xi") or []:
        label = player.get("nickname") or player.get("name") or player.get("player_id")
        sys.stdout.write(f"- {player.get('position')} {label} · {player.get('objective')}\n")


def _render_flip(payload: dict[str, Any]) -> None:
    sys.stdout.write(f"{payload.get('count')} fichajes para especular · caja {_eur(payload.get('cash_eur'))}\n")
    for signing in payload.get("signings") or []:
        label = signing.get("nickname") or signing.get("name") or signing.get("player_id")
        snipe = signing.get("snipe") or {}
        when = snipe.get("fire_local_clock") or "sin cierre"
        sys.stdout.write(f"- {label} · puja {_eur(signing.get('bid_eur'))} · revelar {when}\n")


def _render_needs(payload: dict[str, Any]) -> None:
    sys.stdout.write(f"{payload.get('rival_count')} rivales · {len(payload.get('clause_alerts') or [])} clausulazos agendados\n")
    for alert in payload.get("clause_alerts") or []:
        label = alert.get("nickname") or alert.get("name") or alert.get("player_id")
        sys.stdout.write(
            f"- {alert.get('manager_name') or alert.get('team_id')} · {label} · "
            f"{alert.get('alert_local_date')} {alert.get('alert_local_time')}\n"
        )


def _render_agent(payload: dict[str, Any]) -> None:
    optimize = payload.get("optimize") or {}
    governance = payload.get("governance") or {}
    state = "ejecución pedida" if payload.get("execute_requested") else "solo plan"
    sys.stdout.write(f"Agente · {state} · formación {optimize.get('formation') or 'jornada a 0'}\n")
    for order in governance.get("orders") or []:
        sys.stdout.write(f"- {order.get('operation')}: {order.get('status')}\n")


def _eur(value: object) -> str:
    if not isinstance(value, int):
        return "-"
    sign = "-" if value < 0 else ""
    return sign + f"{abs(value):,}".replace(",", ".")


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            continue


if __name__ == "__main__":
    sys.exit(main())
