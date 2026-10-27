"""Generador del lanzador de escritorio: ``scripts/create_desktop_shortcut.py``.

Lo que hay que proteger del ``.bat`` no es su formato, es que sea un salto
**de ventana**: las variables se activan ahí y mueren con la consola. Si el
generador escribiera ``setx`` o tocara el ``.env``, subiría el escudo offline
de forma permanente y este proyecto dejaría de tener air-gap.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    path = ROOT / "scripts" / "create_desktop_shortcut.py"
    spec = importlib.util.spec_from_file_location("create_desktop_shortcut", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shortcut = _load_script()


class RenderBatchTests(unittest.TestCase):
    def test_production_flag_is_set_inside_the_script(self) -> None:
        body = shortcut.render_batch(project_root=ROOT)
        self.assertIn("set LALIGA_ENV=production", body)

    def test_offline_flag_is_turned_off_so_the_download_has_network(self) -> None:
        body = shortcut.render_batch(project_root=ROOT)
        self.assertIn("set FANTASY_OFFLINE=0", body)

    def test_it_never_writes_the_environment_permanently(self) -> None:
        body = shortcut.render_batch(project_root=ROOT)
        for forbidden in ("setx ", "REG ADD", "setx /M", ">> .env", ">>.env"):
            self.assertNotIn(forbidden, body)
        # La variable se limpia al terminar, igual que el ``finally`` del
        # endpoint: ``set LALIGA_ENV=`` sin valor no es lo mismo que asignarla.
        lines = [line.strip() for line in body.splitlines()]
        self.assertIn("set LALIGA_ENV=", lines)
        self.assertIn("set FANTASY_OFFLINE=", lines)
        self.assertLess(
            lines.index("set LALIGA_ENV=production"),
            lines.index("set LALIGA_ENV="),
            "el limpiado tiene que ir después de la descarga",
        )

    def test_the_default_command_writes_the_photo_the_panel_reads(self) -> None:
        """El .bat tiene que usar ``refresh``, no ``optimize``.

        ``optimize`` descargaba de verdad pero no escribía
        ``.cache/dashboard/``: el panel seguía sirviendo la foto de ayer con
        fecha nueva. El síntoma era «he conectado, ha llamado, y sigue con los
        datos del otro día».
        """
        body = shortcut.render_batch(project_root=ROOT)
        self.assertIn("cli.py refresh --fresh", body)
        self.assertNotIn("cli.py optimize", body)

    def test_it_stops_the_old_servers_before_raising_the_panel(self) -> None:
        """Un uvicorn nacido en air-gap no puede abrir Chrome para «Conectar»."""
        body = shortcut.render_batch(project_root=ROOT)
        self.assertIn("scripts\\stop_servers.ps1", body)
        self.assertLess(body.index("stop_servers.ps1"), body.index("cli.py refresh"))

    def test_it_leaves_the_panel_running_with_network(self) -> None:
        # El panel tiene que arrancar mientras la ventana de produccion sigue
        # abierta: si no, «Conectar cuenta» vuelve a quedarse sin salida.
        body = shortcut.render_batch(project_root=ROOT)
        self.assertIn("call iniciar_todo.bat", body)
        self.assertLess(body.index("cli.py refresh"), body.index("call iniciar_todo.bat"))

    def test_the_project_root_is_absolute(self) -> None:
        # El .bat puede acabar en el Escritorio y ``%~dp0`` apuntaría allí.
        body = shortcut.render_batch(project_root=ROOT)
        self.assertIn(f'cd /d "{ROOT.resolve()}"', body)

    def test_the_venv_interpreter_is_preferred_when_present(self) -> None:
        body = shortcut.render_batch(project_root=ROOT)
        self.assertIn('.venv\\Scripts\\python.exe', body)

    def test_unknown_command_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            shortcut.render_batch(project_root=ROOT, command="rm-rf")

    def test_lines_use_crlf(self) -> None:
        body = shortcut.render_batch(project_root=ROOT)
        self.assertIn("\r\n", body)
        self.assertEqual(body.replace("\r\n", "").count("\n"), 0)


class WriteShortcutTests(unittest.TestCase):
    def test_writing_creates_the_batch_with_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / shortcut.BAT_NAME
            written = shortcut.write_shortcut(destination=target, project_root=ROOT)
            self.assertEqual(written, target)
            raw = target.read_bytes()
            self.assertIn(b"set LALIGA_ENV=production", raw)
            self.assertIn(b"\r\n", raw)
            self.assertNotIn(b"\n\n", raw.replace(b"\r\n", b"\r\r"))

    def test_a_directory_is_completed_with_the_batch_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            written = shortcut.write_shortcut(destination=Path(directory), project_root=ROOT)
            self.assertEqual(written.name, shortcut.BAT_NAME)
            self.assertTrue(written.is_file())

    def test_the_batch_is_written_in_the_console_codepage(self) -> None:
        # El .bat lo abre cmd.exe como ANSI, no como UTF-8: las tildes de los
        # echos tienen que poder leerse con la página de códigos de Windows.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / shortcut.BAT_NAME
            shortcut.write_shortcut(
                destination=target,
                project_root=ROOT,
                command="optimize",
            )
            raw = target.read_bytes()
            self.assertNotIn(b"\xef\xbb\xbf", raw)  # sin BOM
            self.assertIn("Parando", raw.decode(shortcut.BAT_ENCODING))

    def test_the_main_entry_point_writes_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "salida.bat"
            self.assertEqual(shortcut.main(["--output", str(target)]), 0)
            self.assertTrue(target.is_file())
            self.assertIn("set LALIGA_ENV=production", target.read_text(encoding="utf-8"))

    def test_dry_run_does_not_touch_the_disk(self) -> None:
        module = shortcut
        original = module.write_shortcut
        calls: list[Path] = []
        module.write_shortcut = lambda **kwargs: calls.append(kwargs.get("destination"))  # type: ignore[assignment]
        try:
            self.assertEqual(module.main(["--print"]), 0)
        finally:
            module.write_shortcut = original
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
