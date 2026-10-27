import os, traceback
from unittest.mock import patch
import cli
with patch.dict(os.environ, {"LALIGA_ACCESS_TOKEN": "", "LALIGA_REFRESH_TOKEN": "", "LEAGUE_ID": ""}):
    try:
        cli._dispatch(cli.build_parser().parse_args(["optimize","--json"]))
    except Exception as exc:
        traceback.print_exc()
