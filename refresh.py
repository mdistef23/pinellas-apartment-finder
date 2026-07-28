#!/usr/bin/env python3
"""
Checks St. Petersburg + Pinellas Park for NEW rental listings that match the criteria,
diffs them against what's already been seen, and writes a dated report.

  python3 refresh.py             # check + report
  python3 refresh.py --quiet     # only print if something new turned up
  python3 refresh.py --auto-add  # also append qualifying finds to apartments.json
                                 # and rebuild the map + tracker

Reads criteria from apartments.json. Tracks everything ever seen in seen.json so
"new" genuinely means new since the last run.

Source: apartmentlist.com (the one major rental site that doesn't block automated
requests -- Zillow / Apartments.com / RentCafe all return 403).
"""
import json, re, sys, time, urllib.request, datetime, pathlib

HERE = pathlib.Path(__file__).resolve().parent
DATA = json.loads((HERE / "apartments.json").read_text())
CRIT = DATA["criteria"]
SEEN_FILE = HERE / "seen.json"
SQFT_CACHE = HERE / "sqft-cache.json"
REPORTS = HERE / "reports"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

CITIES = [
    ("St. Petersburg", "https://www.apartmentlist.com/fl/st-petersburg"),
    ("Pinellas Park", "https://www.apartmentlist.com/fl/pinellas-park"),
]


def fetch(url):
    q = "%s?price_min=%d&price_max=%d&beds=1,2" % (url, CRIT["price_min"], CRIT["price_max"])
    req = urllib.request.Request(q, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def parse(html_text):
    """Pull the embedded listings array out of the Next.js flight payload."""
    out = {}
    # The payload is JSON escaped inside a JS string, so \" appears as \\"
    for m in re.finditer(
        r'\\"rental_id\\":\\"(?P<id>[^\\"]+)\\",\\"lat\\":(?P<lat>-?[\d.]+),\\"lon\\":(?P<lon>-?[\d.]+),'
        r'\\"prices\\":\{(?P<prices>[^}]*)\},\\"display_name\\":\\"(?P<name>(?:[^\\"]|\\\\.)*)\\",'
        r'\\"slug\\":\\"(?P<slug>[^\\"]+)\\"(?P<rest>[^}]*)',
        html_text,
    ):
        prices = {}
        for bed, price in re.findall(r'\\"(\d+)\\":(\d+)', m.group("prices")):
            prices[int(bed)] = int(price)
        if not prices:
            continue
        out[m.group("id")] = {
            "id": m.group("id"),
            "name": m.group("name").replace('\\\\"', '"'),
            "lat": float(m.group("lat")),
            "lng": float(m.group("lon")),
            "prices": prices,
            "slug": m.group("slug"),
            # contract "free" == an individual owner posting a single unit, not a leasing office
            "private": '\\"contract\\":\\"free\\"' in m.group("rest"),
        }
    return out


def in_budget(prices):
    return any(CRIT["price_min"] <= p <= CRIT["price_max"] for p in prices.values())


def norm_name(s):
    """'1100 70TH Street N' and '1100 70th St N' are the same place."""
    s = re.sub(r"\(private owner\)|[^a-z0-9 ]", " ", s.lower())
    words = {"street": "st", "avenue": "ave", "boulevard": "blvd", "drive": "dr",
             "road": "rd", "lane": "ln", "circle": "cir", "north": "n",
             "south": "s", "east": "e", "west": "w", "apartment": "apt"}
    return " ".join(words.get(w, w) for w in s.split())


DUP_DEG = 0.0008  # ~250 ft -- same building, different unit


def same_building(lat, lng, coords):
    """True if (lat,lng) is within ~250 ft of anything already tracked.

    Was a rounded-grid key (4 decimals). A grid FAILS ON CELL BOUNDARIES: 1240 70th St N
    (27.78392) and 1260 70th St N (27.78403) are 40 ft apart but round to different cells,
    so #68 got auto-added on 7/26 as a "new" building -- exactly the thing Michael said
    never to do (he wants new BUILDINGS, not new vacancies). Distance, never a grid.
    """
    lat, lng = float(lat), float(lng)
    return any(abs(lat - a) <= DUP_DEG and abs(lng - b) <= DUP_DEG for a, b in coords)


def sqft_by_bed(slug, cache):
    """{bed_count: sq ft} for a listing, so size can be matched to the unit being priced.

    Was max_sqft(), which returned the largest floorplan on the page. That is wrong and it
    was wrong silently: the caller quotes the CHEAPEST unit's price and bed count, so the
    biggest apartment's size got glued onto the smallest apartment's rent. Measured 7/27:
    2135 8th Ave N was reported as a 1BR/1,262 sq ft when the 1BR is 576 (1,262 is the 3BR);
    445 32nd Ave N as 1BR/915 when the 1BR is 655. Never take max() across floorplans.
    """
    if slug in cache and isinstance(cache[slug], dict):
        # JSON has no integer keys -- {1: 780} round-trips as {"1": 780}. Without this coercion
        # every cached listing silently misses the bed lookup and gets dropped as "no size".
        return {int(k): v for k, v in cache[slug].items()}
    out = {}
    try:
        req = urllib.request.Request(
            "https://www.apartmentlist.com/" + slug.lstrip("/"),
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=45) as r:
            page = r.read().decode("utf-8", "replace")
        # bed and sqft appear in either order within the same floorplan object
        pairs = [(int(b), int(s)) for b, s in
                 re.findall(r'\\?"bed\w*\\?":\s*\\?"?(\d+)\\?"?[^{}]{0,220}?\\?"sqft\\?":\s*\\?"?(\d+)', page)]
        pairs += [(int(b), int(s)) for s, b in
                  re.findall(r'\\?"sqft\\?":\s*\\?"?(\d+)\\?"?[^{}]{0,220}?\\?"bed\w*\\?":\s*\\?"?(\d+)', page)]
        for bed, sq in pairs:
            if 200 <= sq <= 4000 and 0 <= bed <= 5:
                # smallest floorplan for that bed count = the one an entry price refers to
                out[bed] = min(sq, out.get(bed, sq))
    except Exception:
        out = {}
    cache[slug] = out
    time.sleep(0.6)
    return out


def auto_add(listings):
    """Append qualifying new listings to apartments.json and rebuild the site.

    Deliberately conservative: only listings whose size is trustworthy get added.
    A leasing-office complex's scraped sq ft is its LARGEST floorplan, not the unit
    being advertised at that price -- adding those would put a number on the map
    that isn't real. Those stay in the report for a human to judge.
    """
    path = HERE / "apartments.json"
    d = json.loads(path.read_text())
    apts = d["apartments"]
    n = max(a["num"] for a in apts)
    added = []

    norm = norm_name
    existing_names = {norm(a["name"]) for a in apts}
    existing_coords = [(float(a["lat"]), float(a["lng"])) for a in apts]

    for L in listings:
        if not L["private"]:
            continue
        name = "%s (private owner)" % L["name"]
        # Match on BOTH name and position -- listings get re-posted with reformatted
        # addresses, so the name alone lets duplicates through.
        if norm(name) in existing_names or same_building(L["lat"], L["lng"], existing_coords):
            continue
        n += 1
        beds = "-".join("%dBR" % b for b in sorted(L["prices"]))
        price = min(p for p in L["prices"].values()
                    if CRIT["price_min"] <= p <= CRIT["price_max"])
        apts.append({
            "num": n, "name": name, "price": "$%s" % format(price, ","),
            "beds": beds, "sqft": L["sqft"],
            "notes": ("🔑 INDEPENDENT OWNER — single unit, no leasing office. "
                      "%s sq ft. AUTO-ADDED %s by the daily check — details not yet "
                      "reviewed by hand; confirm on the call."
                      % (format(L["sqft"], ","), datetime.date.today().strftime("%b %d"))),
            "address": "%s, %s, FL" % (L["name"], L["city"]),
            "lat": L["lat"], "lng": L["lng"],
            "source": "apartmentlist private listing (auto)",
            "added": datetime.date.today().isoformat(),
            "status": "new", "tier": "A",
            "url": "https://www.apartmentlist.com/" + L["slug"].lstrip("/"),
        })
        existing_names.add(norm(name))
        existing_coords.append((float(L["lat"]), float(L["lng"])))
        added.append(n)
    if added:
        path.write_text(json.dumps(d, indent=2, ensure_ascii=False))
        import subprocess
        subprocess.run([sys.executable, str(HERE / "build.py")], check=True)
    return added


def main():
    quiet = "--quiet" in sys.argv
    seen = json.loads(SEEN_FILE.read_text()) if SEEN_FILE.exists() else {}
    tracked_names = {a["name"].lower() for a in DATA["apartments"]}
    today = datetime.date.today().isoformat()

    found, fresh, errors = {}, [], []
    for city, url in CITIES:
        try:
            listings = parse(fetch(url))
        except Exception as e:
            errors.append("%s: %s" % (city, e))
            continue
        if not listings:
            errors.append("%s: page fetched but 0 listings parsed -- the site's markup "
                          "probably changed; re-check the parser." % city)
            continue
        for rid, L in listings.items():
            if not in_budget(L["prices"]):
                continue
            L["city"] = city
            found[rid] = L
            already = rid in seen or L["name"].lower() in tracked_names
            if not already:
                fresh.append(L)

    # Fail loudly rather than silently reporting "0 new" when the scrape broke.
    if errors and not found:
        print("\n".join("ERROR  " + e for e in errors))
        print("\nNo listings retrieved -- NOT reporting '0 new', because that would be a lie.")
        sys.exit(1)

    for rid, L in found.items():
        seen.setdefault(rid, {"name": L["name"], "first_seen": today, "city": L["city"]})
    SEEN_FILE.write_text(json.dumps(seen, indent=1, sort_keys=True))

    # Enrich only the new ones with square footage (one page fetch each, cached).
    cache = json.loads(SQFT_CACHE.read_text()) if SQFT_CACHE.exists() else {}
    if fresh:
        for L in fresh:
            L["sqft_map"] = sqft_by_bed(L["slug"], cache)
            # size the unit you could actually rent: best sq ft among the IN-BUDGET beds
            ok = [b for b, p in L["prices"].items() if CRIT["price_min"] <= p <= CRIT["price_max"]]
            sizes = [L["sqft_map"][b] for b in ok if b in L["sqft_map"]]
            L["sqft"] = max(sizes) if sizes else None
            L["sqft_bed"] = (max(((L["sqft_map"][b], b) for b in ok if b in L["sqft_map"]),
                                 default=(None, None))[1])
        SQFT_CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))

    big = [L for L in fresh if (L.get("sqft") or 0) >= CRIT["sqft_min"]]
    small = [L for L in fresh if (L.get("sqft") or 0) < CRIT["sqft_min"]]
    for group in (big, small):
        group.sort(key=lambda L: (not L["private"], -(L.get("sqft") or 0)))

    if quiet and not big:
        return

    lines = ["APARTMENT CHECK -- %s" % datetime.date.today().strftime("%b %d, %Y"),
             "Criteria: $%d-$%d, 1-2BR, %s" % (CRIT["price_min"], CRIT["price_max"], CRIT["areas"]),
             "Scanned %d matching listings across %d cities." % (len(found), len(CITIES)), ""]
    if errors:
        lines += ["WARNINGS:"] + ["  ! " + e for e in errors] + [""]
    def block(L):
        # Every bed count carries ITS OWN square footage. Private-vs-complex makes no
        # difference -- a single-owner listing publishes multiple floorplans too, which is
        # exactly how the old max() bug produced 1BR/1,262 sq ft out of a 576 sq ft 1BR.
        smap = L.get("sqft_map") or {}
        beds = ", ".join(
            "%dBR $%s%s" % (b, format(p, ","),
                            (" / %s sq ft" % format(smap[b], ",")) if b in smap else " / sq ft n/a")
            for b, p in sorted(L["prices"].items()))
        if not L.get("sqft"):
            sq = "no sq ft published for any in-budget unit"
        else:
            sq = "best in-budget unit: %dBR at %s sq ft" % (L["sqft_bed"], format(L["sqft"], ","))
        return ["  %s%s" % (L["name"], "   [PRIVATE OWNER]" if L["private"] else ""),
                "     %s | %s | %s" % (beds, sq, L["city"]),
                "     https://www.apartmentlist.com/%s" % L["slug"].lstrip("/"),
                '     for apartments.json:  "lat":%s, "lng":%s' % (L["lat"], L["lng"]), ""]

    if not fresh:
        lines.append("No new listings since the last check.")
    else:
        if big:
            lines += [">>> %d NEW, %d+ SQ FT -- THE ONES THAT MATTER <<<"
                      % (len(big), CRIT["sqft_min"]), ""]
            for L in big:
                lines += block(L)
        else:
            lines += ["No new listings at %d+ sq ft." % CRIT["sqft_min"], ""]
        if small:
            lines += ["-" * 60,
                      "Also new, but under %d sq ft (or size not published) -- skim only:"
                      % CRIT["sqft_min"], ""]
            for L in small:
                lines += block(L)
        lines += ["To add one: copy an entry in apartments.json, fill in the fields above,",
                  "then run  python3 build.py  to rebuild the map + tracker."]

    if "--auto-add" in sys.argv and big:
        added = auto_add(big)
        if added:
            lines += ["", "=" * 60,
                      "AUTO-ADDED %d listing%s to the map + tracker as #%d-#%d."
                      % (len(added), "" if len(added) == 1 else "s", added[0], added[-1]),
                      "They're marked status 'new'. Open the tracker to see them."]

    report = "\n".join(lines)
    print(report)
    REPORTS.mkdir(exist_ok=True)
    # Never overwrite an earlier report from the same day.
    path = REPORTS / ("check-%s.txt" % today)
    n = 2
    while path.exists():
        path = REPORTS / ("check-%s-run%d.txt" % (today, n))
        n += 1
    path.write_text(report)


if __name__ == "__main__":
    main()
