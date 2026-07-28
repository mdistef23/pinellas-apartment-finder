#!/usr/bin/env python3
"""The other four sources: Zumper, PadMapper, Dwellsy, Craigslist.

Added 2026-07-28 after Michael said to go after everything still unmined. Each source is
different, so each is honest about what it can and can't tell us:

  Zumper / PadMapper  same company, same `window.__PRELOADED_STATE__` shape. Rich: address,
                      price range, size range, amenity tags, promotions, ratings, lease-day
                      limits, phone. Amenity tags let us actually CONFIRM in-unit laundry.
  Dwellsy             __NEXT_DATA__ with address, beds, baths, rent, coordinates, phone.
                      No square footage published in the list -- so size stays unknown.
  Craigslist          static result list: title, price, location, link only. Beds/size live on
                      the detail page. This is where private landlords post, so it's worth the
                      extra fetch.

  python3 others.py [--json out.json] [--limit-cl N]

Two traps this file exists to avoid:
  1. "Dishwasher" CONTAINS the substring "washer". Matching bare "washer" marks every listing
     with a dishwasher as having in-unit laundry. Tags are matched explicitly, never by substring.
  2. A size RANGE is the same trap as max() across floorplans -- max_square_feet is the biggest
     unit in the building, not the one at the advertised rent. Only min_square_feet is used, and
     it's labelled as the smallest floorplan.
"""
import json, math, pathlib, re, sys, time, urllib.request, datetime

HERE = pathlib.Path(__file__).resolve().parent
APTS = HERE / "apartments.json"
REPORTS = HERE / "reports"
FLOOD_CACHE = HERE / "flood-cache.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

PRICE_MIN, PRICE_MAX, SQFT_MIN = 1200, 1600, 700
DUP_FEET = 250.0
DOWNTOWN = (27.7709, -82.6403)

# Explicit vocabularies. NOT substring matching -- see the module docstring.
IN_UNIT_TAGS = {
    "in-unit laundry", "in unit laundry", "washer and dryer", "washer & dryer",
    "washer/dryer", "washer / dryer", "full size stackable washer and dryer included",
    "full size, front-load, stacked washer and dryer",
    "full-size, front-load, side-by-side, washer and dryer",
    "washer and dryer in unit", "in-unit washer and dryer", "w/d in unit",
}
SHARED_TAGS = {
    "onsite laundry", "on-site laundry", "laundry facilities", "laundry room",
    "laundry hookups", "washer/dryer hookups", "washer and dryer hookups",
    "community laundry", "shared laundry",
}


def get(url, timeout=45):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


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


def sane_sqft(v):
    """A square footage that a human could actually live in, or None.

    Feeds publish junk in this field: Zumper's "unknown" is 2^63, and zeros show up too.
    Anything outside 200-5000 is not a measurement, it's a placeholder.
    """
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 200 <= n <= 5000 else None


def laundry_from_tags(tags):
    low = {str(t).strip().lower() for t in (tags or [])}
    if low & IN_UNIT_TAGS:
        return True
    if low & SHARED_TAGS:
        return False
    return None


def balanced_json(text, start):
    """Parse the JSON object that begins at `start`, matching braces."""
    depth, k, instr, esc = 0, start, False, False
    while k < len(text):
        c = text[k]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        elif c == '"':
            instr = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:k + 1])
        k += 1
    raise ValueError("unbalanced JSON")


# ------------------------------------------------------------------ Zumper / PadMapper
ZUMPER_URLS = [
    ("Zumper", "https://www.zumper.com/apartments-for-rent/st-petersburg-fl?price_min=1200&price_max=1600"),
    ("Zumper", "https://www.zumper.com/apartments-for-rent/pinellas-park-fl?price_min=1200&price_max=1600"),
    ("Zumper", "https://www.zumper.com/apartments-for-rent/largo-fl?price_min=1200&price_max=1600"),
    ("Zumper", "https://www.zumper.com/houses-for-rent/st-petersburg-fl?price_min=1200&price_max=1600"),
    ("PadMapper", "https://www.padmapper.com/apartments/st-petersburg-fl?price-min=1200&price-max=1600"),
    ("PadMapper", "https://www.padmapper.com/apartments/pinellas-park-fl?price-min=1200&price-max=1600"),
]


def zumper_like(url):
    page = get(url)
    m = re.search(r"window\.__PRELOADED_STATE__\s*=\s*", page)
    if not m:
        raise RuntimeError("no __PRELOADED_STATE__ (markup changed or blocked)")
    d = balanced_json(page, m.end())
    return (d.get("currentSearch") or {}).get("listables", {}).get("listables") or []


def former_name(url, current):
    """Pull the building name out of the URL slug when it differs from the displayed one.

    Zumper keeps the original slug through a rebrand, so the slug is a free "also known as".
    Generic slugs like '2-bedroom-pinellas-park-fl' aren't names and are ignored.
    """
    if not url:
        return None
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"-(fl|saint-petersburg|st-petersburg|pinellas-park|largo|greater-\w+)$", "", slug)
    slug = re.sub(r"^p?\d+-?", "", slug)
    if not slug or re.match(r"^\d*-?(studio|\d-bedroom)", slug):
        return None
    pretty = slug.replace("-", " ").title()
    if not current or norm(pretty).split()[:2] != norm(current).split()[:2]:
        return pretty
    return None


def from_zumper(rec, source, host):
    price = rec.get("min_price") or rec.get("max_price")
    if not price or not (PRICE_MIN <= price <= PRICE_MAX):
        return None
    tags = list(rec.get("amenity_tags") or []) + list(rec.get("building_amenity_tags") or [])
    url = rec.get("url") or rec.get("pa_url") or rec.get("pb_url") or ""
    if url and not url.startswith("http"):
        url = host + url
    lease = []
    for k, div in (("min_lease_days", 30), ("max_lease_days", 30)):
        if rec.get(k):
            lease.append(int(round(rec[k] / div)))
    return {
        "source": source,
        "name": rec.get("building_name") or rec.get("address") or rec.get("title") or "?",
        "address": ", ".join(x for x in [rec.get("address"), rec.get("city"),
                                         rec.get("state")] if x),
        "city": rec.get("city") or "",
        "lat": rec.get("lat"), "lng": rec.get("lng"),
        "price": price,
        "beds": rec.get("min_bedrooms"),
        # min only: max_square_feet is the building's biggest unit, not the one priced above.
        # sane() because Zumper uses 2^63 as its "unknown" sentinel for min_square_feet --
        # unfiltered that renders as "9,223,372,036,854,776,000 sq ft" and, worse, scores as
        # the biggest apartment ever built and sorts to rank #1.
        "sqft": sane_sqft(rec.get("min_square_feet")),
        "sqft_is_smallest_floorplan": bool(sane_sqft(rec.get("max_square_feet"))
                                           and sane_sqft(rec.get("max_square_feet"))
                                           != sane_sqft(rec.get("min_square_feet"))),
        "laundry": laundry_from_tags(tags),
        "amenities": sorted(set(tags))[:20],
        "promotion": rec.get("promotion") if isinstance(rec.get("promotion"), str) else None,
        # Zumper rates out of TEN, ApartmentList out of five. Storing a bare number would put
        # a 9.6 next to a 4.25 in the same column and read as the worse property.
        "rating": rec.get("rating") or rec.get("external_rating"),
        "rating_scale": 10,
        # The URL slug is often the building's FORMER name -- Golf Terrace is now The
        # Oceanaire, Bay Point Villas is now Atlas at Bay Point. Not an error, but reviews
        # and flood history are filed under the old name, so keep it.
        "also_known_as": former_name(url, rec.get("building_name")),
        "phone": rec.get("phone"),
        "property_type": rec.get("property_type"),
        "lease_months": sorted(set(lease)) if lease else [],
        "listed_on": rec.get("listed_on"),
        "url": url,
    }


# ------------------------------------------------------------------------------ Dwellsy
def dwellsy():
    out = []
    for city in ("st-petersburg-fl", "pinellas-park-fl", "largo-fl"):
        try:
            page = get("https://www.dwellsy.com/search/%s" % city)
        except Exception as e:
            print("  dwellsy %s failed: %s" % (city, str(e)[:60]))
            continue
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
        if not m:
            print("  dwellsy %s: no __NEXT_DATA__" % city)
            continue
        for r in (json.loads(m.group(1))["props"]["pageProps"].get("results") or []):
            price = r.get("amount")
            if not price or not (PRICE_MIN <= price <= PRICE_MAX):
                continue
            beds = r.get("bedrooms")
            if beds is not None and not (1 <= beds <= 2):
                continue
            link = r.get("detailsLink") or r.get("addressLink") or ""
            if link and not link.startswith("http"):
                link = "https://www.dwellsy.com" + link
            out.append({
                "source": "Dwellsy",
                "name": r.get("address") or r.get("address_1") or "?",
                "address": ", ".join(x for x in [r.get("address_1"), r.get("address_city"),
                                                 r.get("address_state")] if x)
                           or (r.get("address") or ""),
                "city": r.get("address_city") or "",
                "lat": r.get("latitude"), "lng": r.get("longitude"),
                "price": price, "beds": beds,
                # Dwellsy's list view publishes no square footage at all. Leaving it None is
                # the honest answer; a size filter can't be applied to these.
                "sqft": None, "laundry": None, "amenities": [],
                "promotion": None, "rating": None,
                "phone": r.get("phone_number"),
                "property_type": None, "lease_months": [], "listed_on": None,
                "url": link,
            })
        time.sleep(0.6)
    return out


# --------------------------------------------------------------------------- Craigslist
CL_SEARCH = ("https://tampa.craigslist.org/search/pnl/apa?min_price=%d&max_price=%d"
             "&minSqft=%d&min_bedrooms=1&max_bedrooms=2" % (PRICE_MIN, PRICE_MAX, SQFT_MIN))


def craigslist(limit=40):
    """Craigslist gives title/price/link in the list; beds, size and coordinates need the
    detail page. Worth it: this is where private landlords post, which is the whole point."""
    page = get(CL_SEARCH)
    items = re.findall(
        r'<li class="cl-static-search-result" title="([^"]*)">\s*<a href="([^"]+)".*?'
        r'<div class="price">\$([\d,]+)</div>\s*<div class="location">\s*([^<]*)',
        page, re.S)
    if not items:
        raise RuntimeError("0 Craigslist results parsed — markup changed")
    out = []
    for title, url, price, loc in items[:limit]:
        price = int(price.replace(",", ""))
        if not (PRICE_MIN <= price <= PRICE_MAX):
            continue
        rec = {"source": "Craigslist", "name": title.strip(), "address": loc.strip(),
               "city": loc.strip(), "lat": None, "lng": None, "price": price,
               "beds": None, "sqft": None, "laundry": None, "amenities": [],
               "promotion": None, "rating": None, "phone": None, "property_type": None,
               "lease_months": [], "listed_on": None, "url": url}
        try:
            d = get(url, timeout=30)
            m = re.search(r'<span class="housing">([^<]*)', d)
            if m:
                t = m.group(1)
                b = re.search(r"(\d+)\s*BR", t, re.I)
                s = re.search(r"([\d,]+)\s*ft", t, re.I)
                if b:
                    rec["beds"] = int(b.group(1))
                if s:
                    rec["sqft"] = int(s.group(1).replace(",", ""))
            m = re.search(r'data-latitude="([-\d.]+)"\s+data-longitude="([-\d.]+)"', d)
            if m:
                rec["lat"], rec["lng"] = float(m.group(1)), float(m.group(2))
            body = re.search(r'<section id="postingbody">(.*?)</section>', d, re.S)
            txt = re.sub(r"<[^>]+>", " ", body.group(1)) if body else ""
            low = txt.lower()
            if re.search(r"in[- ]unit (washer|laundry)|washer.{0,6}dryer in|w/?d in unit", low):
                rec["laundry"] = True
            elif re.search(r"hook[- ]?ups?|on[- ]site laundry|laundry (room|facilit)", low):
                rec["laundry"] = False
            rec["desc"] = re.sub(r"\s+", " ", txt).strip()[:400]
        except Exception:
            pass
        time.sleep(0.5)
        out.append(rec)
    return out


# --------------------------------------------------------------------------------- main
def main():
    data = json.loads(APTS.read_text())
    tracked = data["apartments"]
    pts = [(float(a["lat"]), float(a["lng"]), a["num"], a["name"]) for a in tracked]
    names = {norm(a["name"]) for a in tracked}
    akeys = {}
    for a in tracked:
        for src in (a.get("address"), a.get("name")):
            k = addr_key(src)
            if k:
                akeys.setdefault(k, a)

    found, errors = [], []
    for source, url in ZUMPER_URLS:
        host = "https://www.zumper.com" if source == "Zumper" else "https://www.padmapper.com"
        try:
            recs = zumper_like(url)
            got = [x for x in (from_zumper(r, source, host) for r in recs) if x]
            found += got
            print("  %-10s %-58s %3d listings, %3d in budget" %
                  (source, url.split("/")[-1][:58], len(recs), len(got)))
        except Exception as e:
            errors.append("%s %s: %s" % (source, url.split("/")[-1][:40], str(e)[:70]))
        time.sleep(0.7)

    try:
        d = dwellsy()
        found += d
        print("  %-10s %3d in budget" % ("Dwellsy", len(d)))
    except Exception as e:
        errors.append("Dwellsy: %s" % str(e)[:70])

    lim = int(sys.argv[sys.argv.index("--limit-cl") + 1]) if "--limit-cl" in sys.argv else 40
    try:
        c = craigslist(lim)
        found += c
        print("  %-10s %3d in budget (detail pages fetched)" % ("Craigslist", len(c)))
    except Exception as e:
        errors.append("Craigslist: %s" % str(e)[:70])

    if errors and not found:
        print("\n".join("ERROR " + e for e in errors))
        print("\nEvery source failed — NOT reporting an empty market.")
        sys.exit(1)

    # dedupe against the map, and against each other (Zumper and PadMapper share inventory)
    fresh, dupes, seen = [], [], []
    for f in found:
        if f["lat"] is None or f["lng"] is None:
            f["_nogeo"] = True
        hit = akeys.get(addr_key(f["address"]) or addr_key(f["name"]) or ("", ""))
        if hit:
            dupes.append((f, "#%d %s (same address)" % (hit["num"], hit["name"])))
            continue
        if norm(f["name"]) in names:
            dupes.append((f, "same name as a tracked property"))
            continue
        if f.get("lat") is not None:
            near = [t for t in pts if feet_apart(f["lat"], f["lng"], t[0], t[1]) <= DUP_FEET]
            if near:
                dupes.append((f, "#%d %s (same building)" % (near[0][2], near[0][3])))
                continue
            prev = [s for s in seen if s.get("lat") is not None
                    and feet_apart(f["lat"], f["lng"], s["lat"], s["lng"]) <= DUP_FEET]
            if prev:
                dupes.append((f, "already found via %s" % prev[0]["source"]))
                continue
        seen.append(f)
        f["miles"] = (feet_apart(f["lat"], f["lng"], *DOWNTOWN) / 5280.0
                      if f.get("lat") is not None else None)
        fresh.append(f)

    fcache = json.loads(FLOOD_CACHE.read_text()) if FLOOD_CACHE.exists() else {}
    import listing as _listing
    for f in fresh:
        if f.get("lat") is not None:
            f["zone"] = _listing.flood_zone(f["lat"], f["lng"], cache=fcache)
    FLOOD_CACHE.write_text(json.dumps(fcache, indent=1, sort_keys=True))

    def qualifies(f):
        return (f.get("sqft") or 0) >= SQFT_MIN

    strong = [f for f in fresh if qualifies(f) and f.get("laundry") is True]
    maybe = [f for f in fresh if qualifies(f) and f.get("laundry") is not True]
    unknown = [f for f in fresh if not qualifies(f)]

    L = ["OTHER SOURCES SCAN — %s" % datetime.date.today().strftime("%b %d, %Y"),
         "Zumper · PadMapper · Dwellsy · Craigslist",
         "$%d–$%d · 1–2BR · %d+ sq ft · in-unit washer/dryer" % (PRICE_MIN, PRICE_MAX, SQFT_MIN),
         ""]
    if errors:
        L += ["WARNINGS:"] + ["  ! " + e for e in errors] + [""]
    L += ["%d listings in budget across the four sources." % len(found),
          "%d dropped as already tracked or duplicated between sources." % len(dupes),
          "%d new. Of those: %d clear %d sq ft with in-unit W/D confirmed, %d clear the size "
          "but not the laundry, %d publish no size."
          % (len(fresh), len(strong), SQFT_MIN, len(maybe), len(unknown)), ""]

    def block(f, i):
        bits = ["$%s" % format(f["price"], ",")]
        if f.get("beds"):
            bits.append("%sBR" % f["beds"])
        bits.append("%s sq ft%s" % (format(f["sqft"], ","),
                                    " (smallest floorplan)" if f.get("sqft_is_smallest_floorplan") else "")
                    if f.get("sqft") else "size not published")
        if f.get("sqft"):
            bits.append("$%.2f/sq ft" % (f["price"] / f["sqft"]))
        out = ["%2d. %s   [%s]" % (i, f["name"][:60], f["source"]),
               "    " + " · ".join(bits),
               "    %s%s" % (f["address"][:70],
                             " · %.1f mi from downtown" % f["miles"] if f.get("miles") is not None else "")]
        lm = {True: "in-unit W/D ✓", False: "NO in-unit W/D"}.get(f.get("laundry"),
                                                                 "laundry not published")
        out.append("    %s%s" % (lm, " · FEMA %s" % f["zone"] if f.get("zone") else ""))
        if f.get("promotion"):
            out.append("    💰 %s" % f["promotion"][:140])
        if f.get("rating"):
            out.append("    ★ %s/%d%s" % (f["rating"], f.get("rating_scale") or 5,
                                          "  (also known as %s)" % f["also_known_as"]
                                          if f.get("also_known_as") else ""))
        if f.get("lease_months"):
            out.append("    lease: %s months" % "/".join(str(x) for x in f["lease_months"]))
        if f.get("phone"):
            out.append("    ☎ %s" % f["phone"])
        if f.get("url"):
            out.append("    %s" % f["url"])
        out.append("")
        return out

    for title, grp in [("✅ CLEARS SIZE, IN-UNIT W/D CONFIRMED", strong),
                       ("📞 CLEARS SIZE, LAUNDRY UNCONFIRMED", maybe),
                       ("❔ NO SIZE PUBLISHED — can't be filtered, listed for completeness", unknown)]:
        L += ["=" * 78, "%s  (%d)" % (title, len(grp)), "=" * 78, ""]
        for i, f in enumerate(sorted(grp, key=lambda x: -(x.get("sqft") or 0)), 1):
            L += block(f, i)

    report = "\n".join(L)
    print(report)
    REPORTS.mkdir(exist_ok=True)
    p = REPORTS / ("others-%s.txt" % datetime.date.today().isoformat())
    n = 2
    while p.exists():
        p = REPORTS / ("others-%s-run%d.txt" % (datetime.date.today().isoformat(), n))
        n += 1
    p.write_text(report)
    print("report: %s" % p)
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        pathlib.Path(out).write_text(json.dumps(fresh, indent=1, ensure_ascii=False, default=str))
        print("candidates: %s" % out)


if __name__ == "__main__":
    main()
