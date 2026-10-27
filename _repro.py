import faulthandler, os, sys, time, threading
from unittest.mock import patch
os.environ["FANTASY_NET_PACING"]="0"
import cli
def dump():
    for i in range(12):
        time.sleep(10)
        print("=== DUMP", i, "===", flush=True)
        faulthandler.dump_traceback()
threading.Thread(target=dump, daemon=True).start()
t=time.time()
with patch.dict(os.environ, {"LALIGA_ACCESS_TOKEN": "", "LALIGA_REFRESH_TOKEN": "", "LEAGUE_ID": ""}):
    code = cli.main(["optimize","--json"])
print("code", code, round(time.time()-t,1))
