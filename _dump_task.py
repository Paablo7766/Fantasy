import faulthandler, os, sys, threading, time
os.environ["FANTASY_OFFLINE"] = "1"
faulthandler.enable()
import cli
def dump():
    for _ in range(8):
        time.sleep(6)
        print("---- DUMP ----", flush=True)
        faulthandler.dump_traceback()
threading.Thread(target=dump, daemon=True).start()
try:
    cli.main(["optimize","--json"])
except SystemExit as e:
    print("exit", e.code)
