#!/usr/bin/env python3
"""Hunt for properties matching Michael's 2026-07-28 criteria, across the whole search area.

  $1,200-$1,600 · 1-2BR · 700+ sq ft · IN-UNIT washer/dryer (hard) · 6-12 month lease
  any building type (apartment / house / townhouse / condo)
  St. Petersburg primary, Pinellas Park, Largo edge
  plus: move-in specials, good reviews, updated units, high ceilings, top floor

  python3 scan.py                 # scan + report
  python3 scan.py --json out.json # also dump candidates for the map builder

Every candidate is measured against its own live detail page -- size paired to the bed count
it belongs to, laundry read off the amenity list, flood zone from a live FEMA point query.
Anything already on the map (same building, within 250 ft) is dropped and SAID to be dropped,
because a silent filter looks identical to a market with nothing in it.
"""
import json, math, pathlib, re, sys, urllib.parse, urllib.request, datetime
import listing

HERE = pathlib.Path(__file__).resolve().parent
APTS = HERE / "apartments.json"
DETAIL_CACHE = HERE / "listing-cache.json"
FLOOD_CACHE = HERE / "flood-cache.json"
REPORTS = HERE / "reports"

PRICE_MIN, PRICE_MAX = 1200, 1600
SQFT_MIN = 700
DUP_FEET = 250.0

# Michael: St. Pete mainly, Pinellas Park too, "maybe even a little largo".
# The rest are the near-in south-county edge; each candidate carries its city so the
# report can be read by area rather than as one undifferentiated pile.
CITIES = [
    ("St. Petersburg", "fl/st-petersburg",  "primary"),
    ("Pinellas Park",  "fl/pinellas-park",  "primary"),
    ("Lealman",        "fl/lealman",        "primary"),   # unincorporated, sits inside St. Pete
    ("Kenneth City",   "fl/kenneth-city",   "primary"),   # ditto
    ("Largo",          "fl/largo",          "edge"),
    ("Gulfport",       "fl/gulfport",       "edge"),
    ("South Pasadena", "fl/south-pasadena", "edge"),
    ("Seminole",       "fl/seminole",       "edge"),
    ("St. Pete Beach", "fl/st-pete-beach",  "edge"),
    ("Treasure Island", "fl/treasure-island", "edge"),
    ("Madeira Beach",  "fl/madeira-beach",  "edge"),
    ("Bay Pines",      "fl/bay-pines",      "edge"),
    ("Tierra Verde",   "fl/tierra-verde",   "edge"),
]

# Downtown St. Pete, for reporting how far out each find actually is -- "a little Largo"
# and north Largo at 27.93 are not the same request.
DOWNTOWN = (27.7709, -82.6403)


def feet_apart(lat1, lng1, lat2, lng2):
    dlat = (float(lat1) - float(lat2)) * 364000
    dlng = (float(lng1) - float(lng2)) * 364000 * math.cos(math.radians(float(lat1)))
    return math.hypot(dlat, dlng)


def norm_name(s):
    s = re.sub(r"\(private owner\)|[^a-z0-9 ]", " ", (s or "").lower())
    words = {"street": "st", "avenue": "ave", "boulevard": "blvd", "drive": "dr",
             "road": "rd", "lane": "ln", "circle": "cir", "terrace": "ter",
             "north": "n", "south": "s", "east": "e", "west": "w", "apartment": "apt"}
    return " ".join(words.get(w, w) for w in s.split())


def search(city_slug, in_unit_only=False):
    """One city's search payload.

    The site's own has_in_unit_laundry filter is NOT trusted as the gate. It disagrees with
    the property's own amenity list in both directions -- Imperial Palms passes the filter
    while its amenity list has no in-unit laundry at all -- so filtering server-side would
    both admit places that fail the requirement and hide places that meet it. Every listing
    gets checked against its own detail page instead; the filter is available for a quick pass.
    """
    q = "price_min=%d&price_max=%d&beds=1,2" % (PRICE_MIN, PRICE_MAX)
    if in_unit_only:
        q += "&amenities=has_in_unit_laundry"
    url = "https://www.apartmentlist.com/%s?%s" % (city_slug, q)
    page = listing.get(url)
    out = {}
    for m in re.finditer(
        r'\\"rental_id\\":\\"(?P<id>[^\\"]+)\\",\\"lat\\":(?P<lat>-?[\d.]+),\\"lon\\":(?P<lon>-?[\d.]+),'
        r'\\"prices\\":\{(?P<prices>[^}]*)\},\\"display_name\\":\\"(?P<name>(?:[^\\"]|\\\\.)*)\\",'
        r'\\"slug\\":\\"(?P<slug>[^\\"]+)\\"(?P<rest>[^}]*)', page
    ):
        prices = {int(b): int(p) for b, p in re.findall(r'\\"(\d+)\\":(\d+)', m.group("prices"))}
        if not prices:
            continue
        out[m.group("id")] = {
            "id": m.group("id"), "name": m.group("name").replace('\\\\"', '"'),
            "lat": float(m.group("lat")), "lng": float(m.group("lon")),
            "prices": prices, "slug": m.group("slug"),
            "private": '\\"contract\\":\\"free\\"' in m.group("rest"),
        }
    if not out:
        # 0 results and a broken parser look identical from here, and treating one as the
        # other is how a scan reports "nothing available" during a week that had plenty.
        # Re-fetch the city with no filters: if listings parse then, the filters genuinely
        # matched nothing; if they don't, the markup moved and we must fail loudly.
        bare = listing.get("https://www.apartmentlist.com/%s" % city_slug)
        if re.search(r'\\"rental_id\\":\\"', bare):
            return {}
        raise RuntimeError("0 listings parsed for %s even unfiltered -- markup changed"
                           % city_slug)
    return out


def main():
    data = json.loads(APTS.read_text())
    tracked = data["apartments"]
    tracked_pts = [(float(a["lat"]), float(a["lng"]), a["num"], a["name"]) for a in tracked]
    tracked_names = {norm_name(a["name"]) for a in tracked}
    # The listing slug is the only exact key. "49th Street" came back as a fresh find at
    # 589 ft from tracked #33 "49th Street Apartments" -- same slug, same property; the
    # site just publishes a slightly different coordinate for it. Distance and name both
    # missed it, so match the slug first.
    tracked_slugs = {re.sub(r"^https?://[^/]+/", "", (a.get("url") or "")).strip("/")
                     for a in tracked if a.get("url")}

    dcache = json.loads(DETAIL_CACHE.read_text()) if DETAIL_CACHE.exists() else {}
    fcache = json.loads(FLOOD_CACHE.read_text()) if FLOOD_CACHE.exists() else {}

    found, dropped_dupe, errors = {}, [], []
    for city, slug, kind in CITIES:
        try:
            res = search(slug)
        except Exception as e:
            errors.append("%s: %s" % (city, str(e)[:100]))
            continue
        for rid, L in res.items():
            L["city"], L["area"] = city, kind
            near = [(t[2], t[3], feet_apart(L["lat"], L["lng"], t[0], t[1])) for t in tracked_pts]
            near = [n for n in near if n[2] <= DUP_FEET]
            if (near or norm_name(L["name"]) in tracked_names
                    or L["slug"].strip("/") in tracked_slugs):
                dropped_dupe.append((L, near[0] if near else None))
                continue
            found[rid] = L

    # Fail loudly. A scrape that broke must never look like a market with nothing in it.
    if errors and not found:
        print("\n".join("ERROR  " + e for e in errors))
        print("\nNothing retrieved — NOT reporting '0 found', because that would be a lie.")
        sys.exit(1)

    cands = []
    for L in found.values():
        d = listing.detail(L["slug"], cache=dcache)
        sq_by_bed = d["sqft_by_bed"]
        price_by_bed = d["price_by_bed"] or L["prices"]
        ok = [(sq_by_bed[b], b, price_by_bed.get(b) or L["prices"].get(b))
              for b in sq_by_bed
              if b in (set(price_by_bed) | set(L["prices"]))
              and PRICE_MIN <= (price_by_bed.get(b) or L["prices"].get(b) or 0) <= PRICE_MAX
              and sq_by_bed[b] >= SQFT_MIN]
        if not ok:
            continue
        sqft, bed, price = max(ok)
        L.update(sqft=sqft, bed=bed, price=price, detail=d,
                 miles=feet_apart(L["lat"], L["lng"], *DOWNTOWN) / 5280.0,
                 zone=listing.flood_zone(L["lat"], L["lng"], cache=fcache))
        cands.append(L)

    DETAIL_CACHE.write_text(json.dumps(dcache, indent=1, sort_keys=True))
    FLOOD_CACHE.write_text(json.dumps(fcache, indent=1, sort_keys=True))

    def score(L):
        d = L["detail"]
        s = 0.0
        s += (L["sqft"] - SQFT_MIN) / 100.0                 # size over the bar
        s += (PRICE_MAX - L["price"]) / 100.0               # room under budget
        if d.get("in_unit_laundry") is True:
            s += 6                                          # the hard requirement, confirmed
        if d.get("specials"):
            s += 2
        if d.get("rating") and d["rating"] >= 4:
            s += 2 + (d.get("review_count") or 0) / 20.0
        for f, w in (("top_floor", 2), ("updated", 1.5), ("high_ceilings", 1.5),
                     ("ground_floor", -1.5)):
            if f in (d.get("flags") or []):
                s += w
        z = (L.get("zone") or "")
        if z.startswith("VE"):
            s -= 6
        elif z.startswith("AE") or z.startswith("A "):
            s -= 4
        # He asked for St. Pete mainly. Distance from downtown is the honest penalty --
        # "Largo" covers everything from 4 miles out to 14, and only one of those is
        # "a little Largo".
        s -= max(0.0, L.get("miles", 0) - 5) * 0.6
        if L["private"]:
            s += 1
        return s

    cands.sort(key=score, reverse=True)

    L_ = ["APARTMENT SCAN — %s" % datetime.date.today().strftime("%b %d, %Y"),
          "$%d-$%d · 1-2BR · %d+ sq ft · IN-UNIT washer/dryer · 6-12 mo lease · any building type"
          % (PRICE_MIN, PRICE_MAX, SQFT_MIN),
          "Areas: %s" % ", ".join(c[0] for c in CITIES), ""]
    if errors:
        L_ += ["WARNINGS:"] + ["  ! " + e for e in errors] + [""]
    L_ += ["Scanned %d in-budget 1-2BR listings across %d areas."
           % (len(found) + len(dropped_dupe), len(CITIES)),
           "Dropped %d as buildings already on the map (his rule: new buildings, not new "
           "vacancies)." % len(dropped_dupe),
           "%d cleared %d+ sq ft at an in-budget price." % (len(cands), SQFT_MIN), ""]

    def block(Lx, i):
        d = Lx["detail"]
        laundry = {True: "in-unit W/D ✓", False: "NO in-unit W/D",
                   "unclear": "laundry UNCLEAR — ask"}.get(d.get("in_unit_laundry"),
                                                           "laundry not published")
        out = ["%2d. %s%s" % (i, Lx["name"], "   [PRIVATE OWNER]" if Lx["private"] else ""),
               "    $%s · %dBR · %s sq ft · $%.2f/sq ft · %s (%.1f mi from downtown)"
               % (format(Lx["price"], ","), Lx["bed"], format(Lx["sqft"], ","),
                  Lx["price"] / Lx["sqft"], Lx["city"], Lx.get("miles", 0)),
               "    %s · FEMA %s" % (laundry, Lx.get("zone") or "unknown")]
        if d.get("laundry_note"):
            out.append("    ⚠ %s" % d["laundry_note"])
        leases = sorted(set(d.get("lease_lengths") or []))
        if leases:
            out.append("    lease: %s months" % "/".join(str(x) for x in leases))
        if d.get("specials"):
            out.append("    💰 DEAL: %s" % d["specials"][:150])
        if d.get("rating"):
            out.append("    ★ %.2f from %d reviews" % (d["rating"], d.get("review_count") or 0))
        if d.get("flags"):
            out.append("    perks: %s" % ", ".join(d["flags"]))
        if d.get("phone"):
            out.append("    ☎ %s" % d["phone"])
        out += ["    https://www.apartmentlist.com/%s" % Lx["slug"].lstrip("/"),
                '    "lat":%s, "lng":%s' % (Lx["lat"], Lx["lng"]), ""]
        return out

    if dropped_dupe:
        L_ += ["-" * 78, "DROPPED AS ALREADY-TRACKED BUILDINGS", "-" * 78]
        for Lx, near in dropped_dupe[:25]:
            if near:
                L_.append("  %-44s  %3.0f ft from #%d %s"
                          % (Lx["name"][:44], near[2], near[0], near[1][:28]))
            else:
                L_.append("  %-44s  same name as a tracked property" % Lx["name"][:44])
        if len(dropped_dupe) > 25:
            L_.append("  ... and %d more" % (len(dropped_dupe) - 25))
        L_.append("")

    # In-unit washer/dryer is a hard requirement, so the report must not blend a confirmed
    # yes with an unknown and a flat no. Three buckets, and the "no" bucket is kept visible
    # rather than deleted -- some of them are strong on every other axis and worth one call.
    def bucket(Lx):
        v = Lx["detail"].get("in_unit_laundry")
        return 0 if v is True else (1 if v in (None, "unclear") else 2)

    groups = [(0, "✅ MEETS EVERYTHING — in-unit washer/dryer confirmed"),
              (1, "📞 WORTH A CALL — laundry not published, everything else fits"),
              (2, "❌ NO IN-UNIT WASHER/DRYER — fails the hard rule, listed so it isn't re-researched")]
    for g, title in groups:
        grp = [c for c in cands if bucket(c) == g]
        L_ += ["", "=" * 78, "%s  (%d)" % (title, len(grp)), "=" * 78, ""]
        for i, Lx in enumerate(grp, 1):
            L_ += block(Lx, i)
    report = "\n".join(L_)
    print(report)
    REPORTS.mkdir(exist_ok=True)
    p = REPORTS / ("scan-%s.txt" % datetime.date.today().isoformat())
    n = 2
    while p.exists():
        p = REPORTS / ("scan-%s-run%d.txt" % (datetime.date.today().isoformat(), n))
        n += 1
    p.write_text(report)
    print("report: %s" % p)
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        pathlib.Path(out).write_text(json.dumps(cands, indent=1, ensure_ascii=False, default=str))
        print("candidates: %s" % out)
    return


if __name__ == "__main__":
    main()
