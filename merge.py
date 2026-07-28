#!/usr/bin/env python3
"""Merge scan + Zillow finds into apartments.json, tiered against the 7/28 criteria.

  python3 merge.py cands.json zleads.json [--write] [--zillow-top N]

Tiers:
  A  meets every hard criterion, in-unit washer/dryer CONFIRMED on the listing
  B  everything fits but laundry isn't published — one phone call decides it
  C  fails a hard criterion; kept so it doesn't get re-researched (his standing rule)
  L  Zillow lead: real size/beds/rent from Zillow, but its detail pages 403 so amenities
     are unknown. Never promoted above B without a call.

Nothing here invents a number. A Zillow lead carries Zillow's own measured living area and
says so; it does not get an amenity list it never published.
"""
import json, math, pathlib, re, sys, datetime

HERE = pathlib.Path(__file__).resolve().parent
APTS = HERE / "apartments.json"
FLOOD_CACHE = HERE / "flood-cache.json"
DUP_FEET = 250.0
DOWNTOWN = (27.7709, -82.6403)


def feet_apart(lat1, lng1, lat2, lng2):
    dlat = (float(lat1) - float(lat2)) * 364000
    dlng = (float(lng1) - float(lng2)) * 364000 * math.cos(math.radians(float(lat1)))
    return math.hypot(dlat, dlng)


def norm(s):
    s = re.sub(r"\(private owner\)|[^a-z0-9 ]", " ", (s or "").lower())
    w = {"street": "st", "avenue": "ave", "boulevard": "blvd", "drive": "dr", "road": "rd",
         "lane": "ln", "circle": "cir", "terrace": "ter", "north": "n", "south": "s",
         "east": "e", "west": "w", "saint": "st", "apartment": "apt"}
    return " ".join(w.get(x, x) for x in s.split())


def addr_key(s):
    s = norm((s or "").split(",")[0])
    s = re.sub(r"\b(apt|unit|ste|suite|#)\s*\w*\b", " ", s)
    m = re.match(r"\s*(\d+)\s+(.*)", s)
    if not m:
        return None
    rest = [t for t in m.group(2).split()
            if t not in ("st", "ave", "blvd", "dr", "rd", "ln", "cir", "ter", "way", "ct",
                         "pl", "hwy")]
    return (m.group(1), " ".join(rest[:2]))


class Index:
    """Everything already on the map, keyed every way a duplicate can hide.

    Three keys, because each one alone has already let a duplicate through on this project:
    coordinates missed 1240 vs 1260 70th St N (grid boundary), the name missed
    "49th Street" vs "49th Street Apartments", and both missed 316 11th Ave when two
    sites geocoded it 2,195 ft apart.
    """

    def __init__(self, apts):
        self.pts = [(float(a["lat"]), float(a["lng"]), a) for a in apts]
        self.names = {norm(a["name"]): a for a in apts}
        self.slugs = {re.sub(r"^https?://[^/]+/", "", (a.get("url") or "")).strip("/"): a
                      for a in apts if a.get("url")}
        self.akeys = {}
        for a in apts:
            for src in (a.get("address"), a.get("name")):
                k = addr_key(src)
                if k:
                    self.akeys.setdefault(k, a)

    def hit(self, name, address, lat, lng, url=None):
        if url:
            s = re.sub(r"^https?://[^/]+/", "", url).strip("/")
            if s in self.slugs:
                return self.slugs[s], "same listing"
        k = addr_key(address) or addr_key(name)
        if k and k in self.akeys:
            return self.akeys[k], "same street address"
        if norm(name) in self.names:
            return self.names[norm(name)], "same name"
        for plat, plng, a in self.pts:
            d = feet_apart(lat, lng, plat, plng)
            if d <= DUP_FEET:
                return a, "%.0f ft away — same building" % d
        return None, None

    def add(self, a):
        self.pts.append((float(a["lat"]), float(a["lng"]), a))
        self.names[norm(a["name"])] = a
        if a.get("url"):
            self.slugs[re.sub(r"^https?://[^/]+/", "", a["url"]).strip("/")] = a
        for src in (a.get("address"), a.get("name")):
            k = addr_key(src)
            if k:
                self.akeys.setdefault(k, a)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cands = json.loads(pathlib.Path(args[0]).read_text()) if args else []
    zl = json.loads(pathlib.Path(args[1]).read_text()) if len(args) > 1 else []
    ztop = int(sys.argv[sys.argv.index("--zillow-top") + 1]) if "--zillow-top" in sys.argv else 30

    data = json.loads(APTS.read_text())
    apts = data["apartments"]
    idx = Index(apts)
    n = max(a["num"] for a in apts)
    added, skipped = [], []
    today = datetime.date.today().isoformat()

    # --- ApartmentList candidates: full detail, so they can reach tier A ---------------
    for c in cands:
        d = c.get("detail") or {}
        url = "https://www.apartmentlist.com/" + c["slug"].lstrip("/")
        dup, why = idx.hit(c["name"], c.get("address") or c["name"], c["lat"], c["lng"], url)
        if dup:
            skipped.append((c["name"], dup["num"], why))
            continue
        laundry = d.get("in_unit_laundry")
        tier = "A" if laundry is True else ("B" if laundry in (None, "unclear") else "C")
        n += 1
        entry = {
            "num": n,
            "name": c["name"] + (" (private owner)" if c.get("private") else ""),
            "price": "$%s" % format(c["price"], ","),
            "beds": "%dBR" % c["bed"],
            "sqft": c["sqft"],
            "address": "%s, %s, FL" % (c["name"], c["city"]),
            "lat": c["lat"], "lng": c["lng"],
            "city": c["city"],
            "miles_downtown": round(c.get("miles") or 0, 1),
            "source": "apartmentlist",
            "url": url,
            "added": today, "status": "new", "tier": tier,
            "laundry": laundry,
            "lease_months": sorted(set(d.get("lease_lengths") or [])),
            "specials": d.get("specials"),
            "rating": d.get("rating"), "reviews": d.get("review_count"),
            "review_quotes": d.get("review_quotes") or [],
            "amenities": d.get("amenities") or [],
            "perks": d.get("flags") or [],
            "description": (d.get("description") or "")[:900],
            "flood_zone": c.get("zone"),
            "phone": d.get("phone"),
            "verified": True, "verified_on": today,
            "tier_why": {"A": "in-unit washer/dryer confirmed, meets everything",
                         "B": "laundry not published — one call decides it",
                         "C": "no in-unit washer/dryer"}[tier],
        }
        if d.get("laundry_note"):
            entry["laundry_note"] = d["laundry_note"]
        apts.append(entry)
        idx.add(entry)
        added.append(entry)

    # --- Zillow leads: real size, unknown amenities. Capped and ranked. ----------------
    singles = [z for z in zl if not z.get("is_building") and z.get("sqft")]

    def zscore(z):
        s = (z["sqft"] - 700) / 100.0 + (1600 - z["price"]) / 100.0
        s -= max(0.0, z["miles"] - 5) * 0.8
        if z.get("price_cut"):
            s += 1.5
        if z.get("rent_zestimate") and z["rent_zestimate"] > z["price"] + 150:
            s += 2                       # asking well under Zillow's own estimate
        if (z.get("days_on_zillow") or 99) <= 14:
            s += 1                       # fresh listings go fast
        if (z.get("home_type") or "").lower() in ("single family", "townhouse", "condo"):
            s += 1                       # he asked for houses/townhouses/condos too
        return s

    singles.sort(key=zscore, reverse=True)

    # ztop is a CEILING ON THE MAP, not a per-run quota. Read as a per-run quota it walks
    # further down the ranked list every single day -- the first daily run after this was
    # written added another 12 leads that had already been rejected as not good enough,
    # and it would have kept going until all 76 were on the map. That is precisely the
    # pile-up Michael asked to stop.
    existing_leads = sum(1 for a in apts if a.get("tier") == "L")
    room = max(0, ztop - existing_leads)
    if room == 0 and singles:
        print("Zillow leads already at the cap of %d — none added. Raise --zillow-top to widen."
              % ztop)
    # Below this score a lead is just an ordinary listing with an unknown washer/dryer;
    # it isn't a find, and it isn't worth a pin.
    MIN_SCORE = 4.0
    taken = 0
    for z in singles:
        if taken >= room or zscore(z) < MIN_SCORE:
            break
        dup, why = idx.hit(z["name"], z["address"], z["lat"], z["lng"], z.get("url"))
        if dup:
            skipped.append((z["address"], dup["num"], why))
            continue
        n += 1
        taken += 1
        entry = {
            "num": n,
            "name": z["address"].split(",")[0],
            "price": "$%s" % format(z["price"], ","),
            "beds": "%sBR" % z["beds"] if z.get("beds") else "?",
            "sqft": z["sqft"],
            "address": z["address"],
            "lat": z["lat"], "lng": z["lng"],
            "city": "St. Petersburg",
            "miles_downtown": round(z["miles"], 1),
            "source": "zillow",
            "url": z["url"],
            "added": today, "status": "new", "tier": "L",
            "laundry": None,
            "home_type": z.get("home_type"),
            "days_listed": z.get("days_on_zillow"),
            "rent_estimate": z.get("rent_zestimate"),
            "price_cut": z.get("price_cut"),
            "perks": [],
            "verified": True, "verified_on": today,
            "tier_why": ("Zillow lead — size/beds/rent are Zillow's own figures; its detail "
                         "pages block us, so in-unit washer/dryer is unconfirmed. Ask on the call."),
        }
        apts.append(entry)
        idx.add(entry)
        added.append(entry)

    # --- Zumper / PadMapper / Dwellsy / Craigslist -----------------------------------
    others = []
    if "--others" in sys.argv:
        others = json.loads(pathlib.Path(sys.argv[sys.argv.index("--others") + 1]).read_text())
    for o in others:
        if o.get("lat") is None or not o.get("sqft") or o["sqft"] < 700:
            continue          # no coordinates = no pin; no size = can't clear the hard filter
        dup, why = idx.hit(o["name"], o.get("address") or o["name"], o["lat"], o["lng"],
                           o.get("url"))
        if dup:
            skipped.append((o["name"], dup["num"], why))
            continue
        laundry = o.get("laundry")
        tier = "A" if laundry is True else ("B" if laundry is None else "C")
        n += 1
        entry = {
            "num": n, "name": o["name"],
            "price": "$%s" % format(o["price"], ","),
            "beds": "%sBR" % o["beds"] if o.get("beds") else "?",
            "sqft": o["sqft"],
            "address": o.get("address") or o["name"],
            "lat": o["lat"], "lng": o["lng"],
            "city": o.get("city") or "",
            "miles_downtown": round(o["miles"], 1) if o.get("miles") is not None else None,
            "source": o["source"].lower(),
            "url": o.get("url") or "",
            "added": today, "status": "new", "tier": tier,
            "laundry": laundry,
            "lease_months": o.get("lease_months") or [],
            "specials": o.get("promotion"),
            # Zumper rates out of 10; the tracker renders whatever scale is stored here.
            "rating": o.get("rating"), "rating_scale": o.get("rating_scale") or 5,
            "reviews": None,
            "amenities": o.get("amenities") or [],
            "perks": [],
            "also_known_as": o.get("also_known_as"),
            "flood_zone": o.get("zone"),
            "phone": o.get("phone"),
            "description": (o.get("desc") or "")[:900],
            "sqft_note": ("smallest floorplan in the building — the unit at this rent may differ"
                          if o.get("sqft_is_smallest_floorplan") else None),
            "verified": True, "verified_on": today,
            "tier_why": {"A": "in-unit washer/dryer confirmed on the listing",
                         "B": "laundry not published — one call decides it",
                         "C": "no in-unit washer/dryer"}[tier],
        }
        apts.append(entry)
        idx.add(entry)
        added.append(entry)

    print("Added %d (%d ApartmentList, %d Zillow leads). Skipped %d as already tracked."
          % (len(added), sum(1 for a in added if a["source"] == "apartmentlist"),
             sum(1 for a in added if a["source"] == "zillow"), len(skipped)))
    for name, num, why in skipped[:20]:
        print("   skip  %-46s -> #%s (%s)" % (name[:46], num, why))
    if len(skipped) > 20:
        print("   ... and %d more skipped" % (len(skipped) - 20))
    from collections import Counter
    print("Tiers now:", dict(Counter(a.get("tier") for a in apts)))
    print("Total properties:", len(apts))

    if "--write" in sys.argv:
        APTS.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print("WROTE apartments.json")


if __name__ == "__main__":
    main()
