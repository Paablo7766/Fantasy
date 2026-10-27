import importlib.util

import toolbox.market_maker as installed

spec = importlib.util.spec_from_file_location(
    "mm_fresh", r"c:\Users\PABLO SANZ\Downloads\FANTASY\toolbox\market_maker.py"
)
fresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fresh)

for label, module in (("installed", installed), ("fresh", fresh)):
    row = module.evaluate_offer(8_800_000.0, 10_000_000.0, -800_000.0, mean_pct=0.08)
    print(label, row["recommendation"], row["reason"])
