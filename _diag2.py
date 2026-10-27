import os, json
from unittest.mock import patch
import cli
with patch.dict(os.environ, {"LALIGA_ACCESS_TOKEN": "", "LALIGA_REFRESH_TOKEN": "", "LEAGUE_ID": ""}):
    payload, code = cli._dispatch(cli.build_parser().parse_args(["optimize","--json"]))
print(code)
print(json.dumps(payload, indent=2)[:1500])
