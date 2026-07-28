#!/usr/bin/env python3
"""Find (and optionally remove) properties that are the same BUILDING as one already tracked.

Michael's rule: he wants new buildings, not new vacancies in a building already on the map.
The old auto-add keyed dedupe off a rounded coordinate grid, which fails on cell boundaries --
1240 and 1260 70th St N are 40 ft apart but round into different cells, so #68 was added as
a "new" find. Distance-based, and it reports what it drops so the filter is visible.

  python3 dedupe.py           # report only
  python3 dedupe.py --write   # remove the later duplicate, keep the first-added
"""
import json, math, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
APTS = HERE / "apartments.json"
FEET = 250.0


def feet_apart(a, b):
    dlat = (float(a["lat"]) - float(b["lat"])) * 364000        # ft per degree latitude
    dlng = (float(a["lng"]) - float(b["lng"])) * 364000 * math.cos(math.radians(float(a["lat"])))
    return math.hypot(dlat, dlng)


def main():
    data = json.loads(APTS.read_text())
    apts = data["apartments"]
    dupes = []
    for i, a in enumerate(apts):
        for b in apts[:i]:
            d = feet_apart(a, b)
            if d <= FEET:
                dupes.append((a, b, d))
                break

    if not dupes:
        print("No duplicate buildings. %d properties." % len(apts))
        return
    print("DUPLICATE BUILDINGS (within %d ft of one already tracked):\n" % FEET)
    for a, b, d in dupes:
        print("  #%-3d %-42s" % (a["num"], a["name"][:42]))
        print("       is %3.0f ft from  #%-3d %s" % (d, b["num"], b["name"]))
        print("       -> dropping #%d (added later); keeping #%d\n" % (a["num"], b["num"]))

    if "--write" in sys.argv:
        drop = {a["num"] for a, _, _ in dupes}
        data["apartments"] = [x for x in apts if x["num"] not in drop]
        APTS.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print("REMOVED %d: %s  (%d -> %d properties)"
              % (len(drop), sorted(drop), len(apts), len(data["apartments"])))


if __name__ == "__main__":
    main()
