#!/usr/bin/env python3
"""Zillow as a SECOND discovery source — the hidden-gem hunt.

Status change worth recording: the project's settled notes say Zillow 403s everything,
including through a real browser (verified 7/22). As of 2026-07-28 that is no longer true
for SEARCH pages -- they return a full __NEXT_DATA__ payload over plain HTTP. Detail pages
still 403, so Zillow gives us discovery (address, rent, beds, coordinates, link) and not
the amenity/sq-ft depth ApartmentList gives.

What that means for honesty: sq ft here comes from ZILLOW'S OWN FILTER, not from a number
we read and checked. It is labelled that way everywhere it surfaces, and it is never
written onto the map as a measured size. After the 7/26 sq-ft mess, an unverified number
that looks verified is the exact failure to avoid.

  python3 zillow.py            # report
  python3 zillow.py --json out.json
"""
import json, math, pathlib, re, sys, urllib.parse, urllib.request, datetime

HERE = pathlib.Path(__file__).resolve().parent
APTS = HERE / "apartments.json"
REPORTS = HERE / "reports"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

PRICE_MIN, PRICE_MAX, SQFT_MIN = 1200, 1600, 700
DUP_FEET = 250.0
DOWNTOWN = (27.7709, -82.6403)
# St. Pete + Pinellas Park + Lealman + the near Largo/Seminole edge.
BOUNDS = {"west": -82.84, "east": -82.58, "south": 27.68, "north": 27.90}


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
    """(house number, street name) — the part two sites always agree on.

    Needed because coordinate dedupe fails ACROSS sources: ApartmentList puts
    316 11th Ave at 27.78289/-82.63114 and Zillow puts the same building 2,195 ft away,
    which is eight times any same-building threshold. Unit numbers and the N/S/E/W
    suffix are dropped from the name but the suffix is kept as part of the key, because
    316 11th Ave N and 316 11th Ave S are genuinely different addresses in this city.
    """
    s = norm(s.split(",")[0])
    s = re.sub(r"\b(apt|unit|ste|suite|#)\s*\w*\b", " ", s)
    m = re.match(r"\s*(\d+)\s+(.*)", s)
    if not m:
        return None
    num, rest = m.group(1), m.group(2).split()
    rest = [t for t in rest if t not in ("st", "ave", "blvd", "dr", "rd", "ln", "cir", "ter",
                                         "way", "ct", "pl", "hwy")]
    return (num, " ".join(rest[:2]))


def page(n):
    fs = {"mp": {"min": PRICE_MIN, "max": PRICE_MAX}, "beds": {"min": 1, "max": 2},
          "sqft": {"min": SQFT_MIN},
          "fr": {"value": True}, "fsba": {"value": False}, "fsbo": {"value": False},
          "nc": {"value": False}, "cmsn": {"value": False}, "auc": {"value": False},
          "fore": {"value": False}, "rs": {"value": False}}
    sqs = {"pagination": {"currentPage": n}, "isMapVisible": False, "mapBounds": BOUNDS,
           "filterState": fs, "isListVisible": True, "usersSearchTerm": "St. Petersburg, FL"}
    url = ("https://www.zillow.com/st-petersburg-fl/rentals/?searchQueryState="
           + urllib.parse.quote(json.dumps(sqs, separators=(",", ":"))))
    body = urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=45)\
        .read().decode("utf-8", "replace")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', body, re.S)
    if not m:
        raise RuntimeError("no __NEXT_DATA__ — Zillow markup changed or we got walled")
    d = json.loads(m.group(1))["props"]["pageProps"]["searchPageState"]["cat1"]
    return d["searchResults"]["listResults"], d.get("searchList", {}).get("totalResultCount")


def price_of(r):
    """Cheapest in-budget rent this listing advertises."""
    got = []
    for u in (r.get("units") or []):
        m = re.search(r"[\d,]+", u.get("price") or "")
        if m:
            got.append((int(m.group(0).replace(",", "")), u.get("beds")))
    if not got:
        for k in ("minBaseRent", "price"):
            m = re.search(r"[\d,]+", str(r.get(k) or ""))
            if m:
                got.append((int(m.group(0).replace(",", "")), None))
    inb = [g for g in got if PRICE_MIN <= g[0] <= PRICE_MAX]
    return min(inb) if inb else (min(got) if got else (None, None))


def main():
    data = json.loads(APTS.read_text())
    tracked = data["apartments"]
    pts = [(float(a["lat"]), float(a["lng"]), a["num"], a["name"]) for a in tracked]
    names = {norm(a["name"]) for a in tracked}
    addrs = {norm(a.get("address", "").split(",")[0]) for a in tracked}
    akeys = {}
    for a in tracked:
        for src in (a.get("address"), a.get("name")):
            k = addr_key(src or "")
            if k:
                akeys.setdefault(k, a)

    seen, pages, total = {}, 0, None
    while pages < 8:
        pages += 1
        try:
            res, total = page(pages)
        except Exception as e:
            print("page %d failed: %s" % (pages, str(e)[:120]))
            break
        if not res:
            break
        for r in res:
            if r.get("zpid") or r.get("id"):
                seen[r.get("zpid") or r["id"]] = r
        if len(res) < 40:
            break

    if not seen:
        print("Zillow returned nothing — treating as a FAILED source, not an empty market.")
        sys.exit(1)

    fresh, dupes, coord_conflicts = [], [], []
    for r in seen.values():
        ll = r.get("latLong") or {}
        lat, lng = ll.get("latitude"), ll.get("longitude")
        if lat is None:
            continue
        near = [(t[2], t[3], feet_apart(lat, lng, t[0], t[1])) for t in pts]
        near = [n for n in near if n[2] <= DUP_FEET]
        addr = (r.get("address") or "")
        hit = akeys.get(addr_key(addr) or ("", ""))
        if hit:
            gap = feet_apart(lat, lng, hit["lat"], hit["lng"])
            dupes.append((addr, (hit["num"], hit["name"], gap)))
            if gap > DUP_FEET:
                coord_conflicts.append((addr, hit, gap, lat, lng))
            continue
        if near or norm(addr.split(",")[0]) in addrs or norm(r.get("buildingName") or "") in names:
            dupes.append((addr, near[0] if near else None))
            continue
        price, beds = price_of(r)
        if price is None or not (PRICE_MIN <= price <= PRICE_MAX):
            continue
        # Single-listing records carry the real numbers: beds, baths, livingArea (an actual
        # measured size, not a filter promise), homeType, and daysOnZillow -- which finally
        # answers "how recently was this listed", something ApartmentList never publishes.
        info = (r.get("hdpData") or {}).get("homeInfo") or {}
        sqft = r.get("area") or info.get("livingArea")
        url = r.get("detailUrl") or ""
        if url and not url.startswith("http"):
            url = "https://www.zillow.com" + url
        fresh.append({
            "name": r.get("buildingName") or addr.split(",")[0],
            "address": addr, "lat": lat, "lng": lng, "price": price,
            "beds": r.get("beds") or info.get("bedrooms") or beds,
            "baths": r.get("baths") or info.get("bathrooms"),
            "sqft": int(sqft) if sqft else None,
            "home_type": (info.get("homeType") or "").replace("_", " ").title() or None,
            "days_on_zillow": info.get("daysOnZillow"),
            "rent_zestimate": info.get("rentZestimate"),
            "price_cut": info.get("priceReduction"),
            "is_building": bool(r.get("isBuilding")),
            "miles": feet_apart(lat, lng, *DOWNTOWN) / 5280.0,
            "url": url,
            "units": r.get("units") or [],
        })

    # Individual homes first: a single-unit house/condo from a private landlord is the
    # "hidden gem" Michael is after, and it's exactly what a big-complex feed buries.
    fresh.sort(key=lambda f: (f["is_building"], f["miles"]))

    L = ["ZILLOW SCAN — %s" % datetime.date.today().strftime("%b %d, %Y"),
         "$%d-$%d · 1-2BR · %d+ sq ft (ZILLOW'S filter — sq ft NOT independently verified)"
         % (PRICE_MIN, PRICE_MAX, SQFT_MIN),
         "",
         "Zillow reports %s matching rentals in the search box; pulled %d listings over %d pages."
         % (total, len(seen), pages),
         "Dropped %d already on the map. %d are new to us." % (len(dupes), len(fresh)),
         "",
         "Individual listings carry Zillow's own beds / baths / living area / home type /",
         "days-on-market, so those numbers are real. Managed BUILDINGS publish only a price",
         "range per bed count — same trap as everywhere else, so no size is claimed for them.",
         "Zillow detail pages still 403, so amenities (in-unit W/D) can't be read here — that",
         "stays a phone question on anything sourced from Zillow.",
         ""]
    if coord_conflicts:
        L += ["=" * 78,
              "⚠ SAME ADDRESS, DIFFERENT PIN — one of the two sites has it in the wrong place",
              "=" * 78,
              "A pin in the wrong spot is how Calais Park sat 4.5 miles west of itself on the",
              "7/20 map. These are the same street address on both sites but far apart on the",
              "map. Worth checking which coordinate is right before trusting the pin.", ""]
        for addr, hit, gap, lat, lng in coord_conflicts:
            L += ["  %s" % addr,
                  "    map has #%d %s at %.5f, %.5f" % (hit["num"], hit["name"],
                                                        hit["lat"], hit["lng"]),
                  "    Zillow puts it at %.5f, %.5f — %.0f ft (%.2f mi) apart"
                  % (lat, lng, gap, gap / 5280.0), ""]

    L += ["=" * 78, "INDIVIDUAL HOMES / CONDOS / TOWNHOUSES (the hidden-gem end)", "=" * 78, ""]
    singles = [f for f in fresh if not f["is_building"]]
    singles.sort(key=lambda f: (-(f["sqft"] or 0) / 1000.0 + f["miles"] / 10.0))
    for n, f in enumerate(singles, 1):
        bits = ["$%s" % format(f["price"], ",")]
        if f["beds"]:
            bits.append("%sBR" % f["beds"])
        if f["baths"]:
            bits.append("%gBA" % f["baths"])
        bits.append("%s sq ft" % format(f["sqft"], ",") if f["sqft"] else "sq ft n/a")
        if f["sqft"]:
            bits.append("$%.2f/sq ft" % (f["price"] / f["sqft"]))
        L += ["%2d. %s" % (n, f["address"]),
              "    " + " · ".join(bits),
              "    %s · %.1f mi from downtown%s"
              % (f["home_type"] or "type n/a", f["miles"],
                 " · listed %s days ago" % f["days_on_zillow"]
                 if f["days_on_zillow"] is not None else "")]
        if f.get("price_cut"):
            L.append("    💰 price cut: %s" % f["price_cut"])
        if f.get("rent_zestimate") and f["rent_zestimate"] > f["price"] + 50:
            L.append("    📉 asking $%s under Zillow's own rent estimate of $%s"
                     % (format(f["rent_zestimate"] - f["price"], ","),
                        format(f["rent_zestimate"], ",")))
        L += ["    %s" % f["url"], '    "lat":%s, "lng":%s' % (f["lat"], f["lng"]), ""]
    if not singles:
        L.append("  (none — everything Zillow returned is a managed building)\n")
    L += ["=" * 78, "MANAGED BUILDINGS", "=" * 78, ""]
    m = 0
    for f in fresh:
        if not f["is_building"]:
            continue
        m += 1
        units = ", ".join("%sBR %s" % (u.get("beds"), u.get("price")) for u in f["units"][:3])
        L += ["%2d. %-44s %.1f mi" % (m, f["name"][:44], f["miles"]),
              "    %s" % (units or "$%s" % format(f["price"], ",")),
              "    %s" % f["url"], ""]

    report = "\n".join(L)
    print(report)
    REPORTS.mkdir(exist_ok=True)
    p = REPORTS / ("zillow-%s.txt" % datetime.date.today().isoformat())
    k = 2
    while p.exists():
        p = REPORTS / ("zillow-%s-run%d.txt" % (datetime.date.today().isoformat(), k))
        k += 1
    p.write_text(report)
    print("report: %s" % p)
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        pathlib.Path(out).write_text(json.dumps(fresh, indent=1, ensure_ascii=False))
        print("leads: %s" % out)


if __name__ == "__main__":
    main()
