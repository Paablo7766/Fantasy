"""Genera `Actualizar_Fantasy.bat`: un doble clic que salta el air-gap una vez.

El escudo de ``toolbox/net.py`` es el valor por defecto del proyecto: sin
``LALIGA_ENV=production`` no se abre un solo socket hacia LaLiga. Este script
no cambia ese contrato, solo escribe un lanzador que abre la puerta **dentro de
su propio proceso** de ``cmd``:

* ``set LALIGA_ENV=production`` vive en la ventana del ``.bat``. Al cerrarse,
  la variable desaparece con ella; no se escribe en ``.env`` ni en el sistema.
* ``set FANTASY_OFFLINE=0`` desactiva el modo aviÃ³n duro solo en esa ventana.
  Sin esto, un ``FANTASY_OFFLINE=1`` en el ``.env`` dejarÃ­a la pasada sin red y
  el usuario verÃ­a Â«0 llamadasÂ» creyendo que actualizÃ³.
* El comando por defecto es ``python cli.py optimize --fresh``: es el refresco
  principal (plantillas, tendencias y once) y sin ``--fresh`` se servirÃ­a de la
  cachÃ©, que es justo lo que el usuario quiere evitar al hacer doble clic.

Uso:

    python scripts/create_desktop_shortcut.py              # deja el .bat en la raÃ­z
    python scripts/create_desktop_shortcut.py --desktop    # ademÃ¡s copia al Escritorio
    python scripts/create_desktop_shortcut.py --command plan --fresh
    python scripts/create_desktop_shortcut.py --print      # no escribe, muestra el .bat
"""

from __future__ import annotations

import argparse
import locale
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BAT_NAME = "Actualizar_Fantasy.bat"
# ``refresh`` y no ``optimize``: solo ``refresh`` escribe la foto que sirve el
# panel. Con ``optimize`` el .bat descargaba de verdad pero dejaba intacta la
# foto de ayer, y el usuario veía datos viejos tras una descarga correcta.
DEFAULT_COMMAND = "refresh"
# Comandos de ``cli.py`` que descargan algo. ``refresh`` es el principal porque
# es el único que deja la foto nueva donde el panel la lee.
ALLOWED_COMMANDS = ("refresh", "optimize", "plan", "market", "squads", "trends", "agent")
# El ``.bat`` es texto ANSI para ``cmd.exe``: en Windows en español es cp1252.
# UTF-8 hacía que las comillas tipográficas de los echos salieran rotas.
BAT_ENCODING = ("cp1252" if os.name == "nt" else (locale.getpreferredencoding(False) or "utf-8"))


def _venv_python() -> Path:
    """IntÃ©rprete del venv del proyecto, si existe. Si no, el ``python`` del PATH."""
    candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    return candidate if candidate.is_file() else Path("python")


def render_batch(
    *,
    project_root: Path = ROOT,
    command: str = DEFAULT_COMMAND,
    fresh: bool = True,
) -> str:
    """Devuelve el contenido del ``.bat`` con finales de lÃ­nea CRLF.

    ``project_root`` se fija en tiempo de generaciÃ³n porque el fichero puede
    acabar en el Escritorio: ``%~dp0`` apuntarÃ­a allÃ­, no al proyecto.
    """
    if command not in ALLOWED_COMMANDS:
        raise ValueError(
            f"Comando no permitido: {command!r}. Usa uno de {', '.join(ALLOWED_COMMANDS)}."
        )
    root = Path(project_root).resolve()
    fresh_arg = " --fresh" if fresh else ""
    lines = [
        "@echo off",
        "REM ------------------------------------------------------------------",
        "REM  Salto controlado del air-gap de LALIGA Fantasy.",
        "REM",
        "REM  Generado por scripts/create_desktop_shortcut.py. No editar a mano:",
        "REM  vuelve a generarlo si cambias de ruta o de comando.",
        "REM",
        "REM  Las dos variables de abajo viven SOLO en esta ventana de cmd.",
        "REM  Al terminar, el escudo offline queda otra vez puesto: no se toca",
        "REM  el .env ni el entorno del sistema.",
        "REM ------------------------------------------------------------------",
        "chcp 65001 >NUL",
        "title Actualizar Fantasy",
        "cd /d \"" + str(root) + "\"",
        "if errorlevel 1 (",
        "  echo No se pudo entrar en el proyecto: " + str(root),
        "  pause",
        "  exit /b 1",
        ")",
        "",
        "REM Unica llave que abre la red en toolbox/net.py.",
        "set LALIGA_ENV=production",
        "REM Modo avion explicito a 0: si el .env lo trae a 1, esta ventana manda.",
        "set FANTASY_OFFLINE=0",
        "",
        "REM Si el panel ya esta abierto, se queda con la foto vieja: su uvicorn",
        "REM nacio en air-gap y solo el boton Actualizar abre la puerta desde",
        "REM dentro. Se para aqui para que [2/2] lo levante con red, si no",
        "REM Â«Conectar cuentaÂ» y el login de Google no tienen salida.",
        "echo [1/3] Parando backend y panel anteriores (si los hay)...",
        "if exist scripts\\stop_servers.ps1 (",
        "  powershell -NoProfile -ExecutionPolicy Bypass -File \"scripts\\stop_servers.ps1\" >NUL 2>&1",
        ")",
        "",
        "echo [2/3] Descargando datos nuevos de LALIGA (puede tardar varios minutos)...",
        "if exist \".venv\\Scripts\\python.exe\" (",
        "  \".venv\\Scripts\\python.exe\" cli.py " + command + fresh_arg,
        ") else (",
        "  python cli.py " + command + fresh_arg,
        ")",
        "set EXIT_CODE=%ERRORLEVEL%",
        "",
        "echo.",
        "if \"%EXIT_CODE%\"==\"0\" (",
        "  echo [3/3] Cache actualizada. Abriendo el panel con red mientras dure",
        "  echo       esta ventana: Conectar cuenta y Actualizar funcionaran.",
        ") else (",
        "  echo [3/3] La actualizacion fallo con codigo %EXIT_CODE%.",
        "  echo        El panel sigue sirviendo la foto anterior; no se ha borrado nada.",
        "  echo        Aun asi se abre con red, para poder reconectar la cuenta.",
        ")",
        "echo.",
        "if exist iniciar_todo.bat (",
        "  call iniciar_todo.bat",
        ") else (",
        "  echo No encontre iniciar_todo.bat; arranca el panel a mano.",
        ")",
        "echo.",
        "echo La ventana de produccion sigue abierta mientras este cmd siga vivo.",
        "echo Pulsa una tecla para cerrarla: el air-gap volvera a estar puesto.",
        "pause",
        "REM Se cierra la ventana de produccion: al limpiar las variables, el",
        "REM escudo offline vuelve a estar puesto (igualmente moririan con la",
        "REM consola, pero asi queda explicito en el propio lanzador).",
        "set LALIGA_ENV=",
        "set FANTASY_OFFLINE=",
        "exit /b %EXIT_CODE%",
        "",
    ]
    return "\r\n".join(lines)


def desktop_directory() -> Path | None:
    """Escritorio del usuario, incluido el redirigido a OneDrive."""
    home = Path.home()
    candidates = []
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if onedrive:
        candidates.append(Path(onedrive) / "Desktop")
    candidates.append(home / "Desktop")
    candidates.append(home / "Escritorio")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def write_shortcut(
    *,
    destination: Path | None = None,
    project_root: Path = ROOT,
    command: str = DEFAULT_COMMAND,
    fresh: bool = True,
) -> Path:
    """Escribe el ``.bat`` y devuelve su ruta. Idempotente: sobrescribe."""
    target = Path(destination) if destination is not None else Path(project_root) / BAT_NAME
    if target.suffix.lower() not in {".bat", ".cmd"}:
        target = target / BAT_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    # ``newline=""`` para que el CRLF llegue al disco tal cual: un .bat con
    # saltos LF a secas funciona en Windows, pero ``findstr`` y algunos
    # antivirus lo leen peor.
    #
    # ``encoding``: el ``.bat`` se lee como ANSI (cp1252 en España), no como
    # UTF-8. Escribirlo en UTF-8 hacía que ``«Conectar cuenta»`` saliera como
    # ``«Conectar cuenta»`` y la consola pintara mojibake en medio del lanzador.
    with target.open("w", encoding=BAT_ENCODING, errors="replace", newline="") as handle:
        handle.write(render_batch(project_root=project_root, command=command, fresh=fresh))
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="create_desktop_shortcut.py",
        description="Genera Actualizar_Fantasy.bat para saltar el air-gap con doble clic.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"Fichero o carpeta de destino. Por defecto, la raÃ­z del proyecto ({BAT_NAME}).",
    )
    parser.add_argument(
        "--command",
        default=DEFAULT_COMMAND,
        choices=ALLOWED_COMMANDS,
        help="Comando de cli.py que ejecutarÃ¡ el .bat.",
    )
    parser.add_argument(
        "--no-fresh",
        action="store_true",
        help="No aÃ±adir --fresh (el comando se servirÃ¡ de la cachÃ©).",
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="Copia ademÃ¡s el .bat al Escritorio del usuario.",
    )
    parser.add_argument(
        "--print",
        dest="dry_run",
        action="store_true",
        help="Muestra el .bat por stdout sin escribir nada.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fresh = not bool(args.no_fresh)
    if args.dry_run:
        sys.stdout.write(render_batch(command=args.command, fresh=fresh))
        return 0

    destination = Path(args.output) if args.output else ROOT / BAT_NAME
    written = write_shortcut(
        destination=destination,
        project_root=ROOT,
        command=args.command,
        fresh=fresh,
    )
    sys.stdout.write(f"Generado: {written}\n")
    if args.desktop:
        desktop = desktop_directory()
        if desktop is None:
            sys.stderr.write("Aviso: no se encontrÃ³ el Escritorio; solo queda la copia del proyecto.\n")
        else:
            copy = write_shortcut(
                destination=desktop,
                project_root=ROOT,
                command=args.command,
                fresh=fresh,
            )
            sys.stdout.write(f"Copiado al Escritorio: {copy}\n")
    sys.stdout.write(
        "Doble clic en el .bat para descargar. LALIGA_ENV solo existe en esa "
        "ventana: al cerrarla, el escudo offline vuelve a estar puesto.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
