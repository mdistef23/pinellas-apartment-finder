#!/usr/bin/env python3
"""One place that reads an ApartmentList detail page and returns everything we filter on.

Everything downstream (re-measure, daily scan, tracker build) uses this, so a parsing fix
lands in one file instead of three. Nothing here estimates: if a field isn't published,
it comes back None and the caller says "unknown" rather than inventing a value.

The sq-ft rule that matters (learned the hard way on 7/26):
  A listing page carries MANY floorplans -- private single-owner listings included; the
  old assumption that "private == one unit" is disproved. Taking max() across them glued
  the 3BR's size onto the 1BR's rent (2135 8th Ave N reported 1,262 sq ft when the 1BR
  is 576). Size is ALWAYS paired to the bed count it belongs to.
"""
import json, re, time, urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

# In-unit washer/dryer is a HARD requirement (Michael, 7/28). "On-Site Laundry" and
# "Laundry Facilities" are the building's shared room -- they do NOT qualify.
IN_UNIT_LABELS = ("in unit laundry", "in-unit laundry", "washer/dryer", "washer / dryer",
                  "washer & dryer", "washer and dryer", "w/d in unit", "in unit washer")
SHARED_LABELS = ("on-site laundry", "on site laundry", "laundry facilities",
                 "laundry room", "community laundry", "shared laundry",
                 "washer/dryer hookup", "w/d hookup", "hookups")


def get(url, timeout=45):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _json_after(text, key):
    """Extract the JSON array/object that follows `"key":` by matching brackets.

    Regex can't be trusted here -- floorplan objects nest `units:[...]` inside themselves,
    so a lazy `\\[.*?\\]` stops at the wrong bracket and silently truncates the unit list.
    """
    i = text.find('"%s":' % key)
    if i < 0:
        return None
    j = text.find(":", i) + 1
    while j < len(text) and text[j] in " \t\r\n":
        j += 1
    if j >= len(text) or text[j] not in "[{":
        return None
    open_c, close_c = ("[", "]") if text[j] == "[" else ("{", "}")
    depth, k, in_str, esc = 0, j, False, False
    while k < len(text):
        c = text[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[j:k + 1])
                except Exception:
                    return None
        k += 1
    return None


def _text(html_frag):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_frag)).strip()


def parse_detail(page):
    """Everything we filter on, pulled out of one fetched detail page."""
    out = {"sqft_by_bed": {}, "price_by_bed": {}, "amenities": [], "lease_lengths": [],
           "in_unit_laundry": None, "specials": None, "rating": None, "review_count": None,
           "description": "", "flags": [], "units": []}

    units = _json_after(page, "available_units") or []
    for fp in units:
        try:
            bed = int(fp.get("bed"))
            sq = fp.get("sqft")
            price = fp.get("price") or 0
        except (TypeError, ValueError):
            continue
        subs = fp.get("units") or []
        for u in subs:
            ll = u.get("lease_length")
            if isinstance(ll, int) and 0 < ll <= 24:
                out["lease_lengths"].append(ll)
        # Prefer the real available unit's own numbers over the floorplan header.
        for u in subs or [None]:
            usq = (u or {}).get("sqft") or sq
            upr = (u or {}).get("price") or price
            if usq and 200 <= int(usq) <= 5000:
                prev = out["sqft_by_bed"].get(bed)
                # smallest floorplan for that bed = the one an entry-level price refers to
                out["sqft_by_bed"][bed] = int(usq) if prev is None else min(prev, int(usq))
            if upr and 300 <= int(upr) <= 9000:
                prev = out["price_by_bed"].get(bed)
                out["price_by_bed"][bed] = int(upr) if prev is None else min(prev, int(upr))
            out["units"].append({"bed": bed, "bath": fp.get("bath"),
                                 "sqft": usq, "price": upr})

    # Amenities are rendered as labelled list items, not exposed as clean JSON.
    labels = re.findall(r'al-amenity-[a-z]+"></(?:span|div)><(?:span|div) class="[^"]*'
                        r'text-caption[^"]*">([^<]+)<', page)
    labels += re.findall(r'al-amenity-[a-z]+"></div><div class="[^"]*text-center '
                         r'text-caption">([^<]+)<', page)
    out["amenities"] = sorted(set(l.strip() for l in labels))
    low = [l.lower() for l in out["amenities"]]
    if any(any(k in l for k in IN_UNIT_LABELS) for l in low):
        out["in_unit_laundry"] = True
    elif any(any(k in l for k in SHARED_LABELS) for l in low):
        out["in_unit_laundry"] = False
    # else: stays None == not published, which is NOT the same as "no"

    # Specials come as structured JSON. Do NOT regex the rendered page for them: the SVG
    # icon carries aria-label="Rent Special rent special icon" and the sidebar links to
    # "St. Petersburg Apartments with Move-in Specials (20)" -- both of which scrape as a
    # deal that doesn't exist. Only the real offer has raw_text.
    sp = _json_after(page, "specials") or []
    offers = []
    for s in sp if isinstance(sp, list) else []:
        txt = (s or {}).get("raw_text")
        if txt:
            exp = (s or {}).get("expires_at")
            offers.append(_text(txt)[:220] + (" (expires %s)" % exp if exp else ""))
    if offers:
        out["specials"] = " | ".join(offers)[:400]
    else:
        m = re.search(r"is offering the following rent.{0,6}specials?:?\s*(?:<!--\s*-->)?\s*([^<]{10,300})",
                      page)
        if m:
            out["specials"] = _text(m.group(1))[:300]

    # Ratings live in the schema.org JSON-LD aggregate. Reading the FIRST "ratingValue" on
    # the page grabs one individual review instead -- that's how Woodlawn Park showed as
    # a flat 5.0 when its actual average across 4 reviews is 4.25.
    agg = _json_after(page, "aggregateRating") or {}
    if isinstance(agg, dict) and agg.get("ratingValue") is not None:
        try:
            out["rating"] = float(agg["ratingValue"])
            out["review_count"] = int(agg.get("reviewCount") or agg.get("ratingCount") or 0)
        except (TypeError, ValueError):
            pass
    revs = _json_after(page, "reviews") or []
    out["review_quotes"] = [_text(r.get("reviewBody", ""))[:200]
                            for r in (revs if isinstance(revs, list) else [])
                            if isinstance(r, dict) and r.get("reviewBody")][:3]

    m = re.search(r'"phone":"(\+?[\d()\-. ]{10,22})"', page)
    if m:
        out["phone"] = m.group(1).strip()

    m = re.search(r'"description":"((?:[^"\\]|\\.){40,})"', page)
    if m:
        try:
            out["description"] = json.loads('"%s"' % m.group(1))[:1500]
        except Exception:
            out["description"] = m.group(1)[:1500]

    blob = (out["description"] + " " + " ".join(out["amenities"])).lower()

    # The amenity chips and the owner's own text disagree often enough to matter: 2135 8th
    # Ave N lists "On-Site Laundry" while the description says "Inside laundry". Promoting
    # that to a yes would smuggle a shared-laundry unit past a hard requirement; calling it
    # a flat no would bin a place that may well have a washer in it. So it becomes an
    # explicit "unclear" for the phone call -- never silently resolved either way.
    desc_in_unit = re.search(r"in[- ]unit (?:washer|laundry)|inside laundry|washer\s*(?:/|and|&)\s*dryer"
                             r"|washer and dryer in|own washer", out["description"], re.I)
    if desc_in_unit and out["in_unit_laundry"] is not True:
        out["in_unit_laundry"] = "unclear"
        out["laundry_note"] = ("amenity list says %s, but the listing text says '%s' — ask on the call"
                               % (next((a for a in out["amenities"] if "laundry" in a.lower()),
                                       "no laundry amenity"), desc_in_unit.group(0)))
    if re.search(r"top[- ]floor|penthouse|upper floor|second floor|2nd floor", blob):
        out["flags"].append("top_floor")
    if re.search(r"ground floor|first floor|1st floor|carriage house", blob):
        out["flags"].append("ground_floor")
    if re.search(r"renovat|updated|remodel|newly built|new construction|brand new", blob):
        out["flags"].append("updated")
    if re.search(r"high ceiling|vaulted|cathedral ceiling|\d+[- ]foot ceiling", blob):
        out["flags"].append("high_ceilings")
    return out


def detail(slug_or_url, cache=None, force=False):
    """Cached parse_detail() for an ApartmentList slug or full URL."""
    slug = slug_or_url
    if slug.startswith("http"):
        slug = re.sub(r"^https?://[^/]+/", "", slug)
    slug = slug.strip("/")
    if cache is not None and not force and slug in cache:
        d = cache[slug]
        # JSON has no integer keys: {1: 780} round-trips as {"1": 780}. Without coercing
        # them back, every cached listing misses the bed lookup and gets dropped as
        # "no size" -- which is how a scan once reported 0 qualifying minutes after
        # another reported plenty.
        for k in ("sqft_by_bed", "price_by_bed"):
            d[k] = {int(a): b for a, b in (d.get(k) or {}).items()}
        return d
    try:
        page = get("https://www.apartmentlist.com/" + slug)
        d = parse_detail(page)
    except Exception as e:
        d = {"error": str(e)[:120], "sqft_by_bed": {}, "price_by_bed": {}, "amenities": [],
             "lease_lengths": [], "in_unit_laundry": None, "specials": None, "rating": None,
             "review_count": None, "description": "", "flags": [], "units": []}
    if cache is not None:
        cache[slug] = d
    time.sleep(0.5)
    return d


FEMA = ("https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
        "?geometry=%f,%f&geometryType=esriGeometryPoint&inSR=4326&spatialRel="
        "esriSpatialRelIntersects&outFields=FLD_ZONE,ZONE_SUBTY&returnGeometry=false&f=json")


def flood_zone(lat, lng, cache=None):
    """Live FEMA National Flood Hazard Layer point query. Never estimated, never inferred
    from a neighbour -- zone AE next door does not make this address AE."""
    key = "%.5f,%.5f" % (float(lat), float(lng))
    if cache is not None and key in cache:
        return cache[key]
    # FEMA's endpoint drops requests intermittently under a burst -- a single failure
    # returning None reads identically to "no flood risk here", which is the one wrong
    # answer that matters. Retry, and never fabricate a zone.
    val = None
    for attempt in range(3):
        try:
            d = json.loads(get(FEMA % (float(lng), float(lat)), timeout=30))
            feats = d.get("features") or []
            if feats:
                at = feats[0]["attributes"]
                z = at.get("FLD_ZONE") or "?"
                sub = (at.get("ZONE_SUBTY") or "").strip()
                val = "%s%s" % (z, (" – " + sub) if sub else "")
            else:
                val = "unmapped"
            break
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    if cache is not None and val:
        cache[key] = val
    time.sleep(0.25)
    return val
