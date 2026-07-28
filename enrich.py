#!/usr/bin/env python3
"""
Fills in the stuff that makes a listing actually actionable: phone number, real
photos, the owner's description, and a direct link to the listing page.

  python3 enrich.py           # fill in anything missing
  python3 enrich.py --force   # re-fetch everything, even already-enriched entries

Matches entries in apartments.json to live listings by coordinate (and name as a
fallback), then scrapes each listing page. Results are cached in detail-cache.json.

Also flags "top floor" when the owner's own description says so -- that's a stated
preference and it's otherwise buried in paragraph text nobody reads.
"""
import json, re, sys, time, pathlib, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from refresh import parse, fetch, CITIES, UA, norm_name, coord_key  # noqa: E402

APTS_FILE = HERE / "apartments.json"
CACHE_FILE = HERE / "detail-cache.json"

# Real listing photos are stored under a 32-char hex asset id. Everything else on
# the page is stock art for neighbourhood/amenity widgets -- never the apartment.
PHOTO_RE = re.compile(
    r'https://cdn\.apartmentlist\.com/image/upload/[^"\\ ]*?/([0-9a-f]{32})\.(?:jpg|jpeg|png|webp)')
PHONE_RE = re.compile(r'\\?"(?:phone|contact_phone|phone_number|display_phone)\\?":\s*\\?"([^"\\]{7,25})')
TEL_RE = re.compile(r'tel:\+?1?([0-9]{10})\b')
DESC_RE = re.compile(r'\\?"description\\?":\s*\\?"((?:[^"\\]|\\.){60,1200})')

TOP_FLOOR_RE = re.compile(r'\btop[- ]floor\b|\bpenthouse\b|\bupper[- ]floor\b|\bupper level\b', re.I)
GROUND_FLOOR_RE = re.compile(r'\bground[- ]floor\b|\bground[- ]level\b|\bfirst[- ]floor\b|\b1st[- ]floor\b', re.I)
NO_STAIRS_RE = re.compile(r'\belevator\b', re.I)


# The CDN only serves a fixed set of registered transformations -- an invented
# size like 'h_420,w_640' 404s. These three are verified working, with sizes:
#   thumb 100x100 ~4.6KB | card 640x415 ~46KB | full original ~142KB
# Using the right one per context keeps the 60-row tracker from loading ~9MB.
_T = {
    "thumb": "c_fill,dpr_auto,f_auto,g_center,h_100,q_auto,w_100/",
    "card": "c_fill,dpr_auto,f_auto,g_center,h_415,q_auto,w_640/",
    "full": "",
}


def photo_url(asset_id, size="card"):
    return "https://cdn.apartmentlist.com/image/upload/%s%s.jpg" % (_T[size], asset_id)


def scrape(slug):
    req = urllib.request.Request("https://www.apartmentlist.com/" + slug.lstrip("/"),
                                 headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=45) as r:
        page = r.read().decode("utf-8", "replace")

    phone = ""
    m = PHONE_RE.search(page)
    if m:
        phone = m.group(1).strip()
    else:
        m = TEL_RE.search(page)
        if m:
            d = m.group(1)
            phone = "(%s) %s-%s" % (d[:3], d[3:6], d[6:])

    seen, photos = set(), []
    for m in PHOTO_RE.finditer(page):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            photos.append({"thumb": photo_url(m.group(1), "thumb"),
                           "card": photo_url(m.group(1), "card"),
                           "full": photo_url(m.group(1), "full")})

    desc = ""
    for m in DESC_RE.finditer(page):
        d = m.group(1)
        # Skip the boilerplate city blurb that appears on every page.
        if "Sunshine City boasts" in d or "cost of living" in d[:80]:
            continue
        desc = re.sub(r'\\[nrt]', ' ', d)
        desc = re.sub(r'\s+', ' ', desc).strip()
        break

    return {"phone": phone, "photos": photos[:6], "desc": desc,
            "url": "https://www.apartmentlist.com/" + slug.lstrip("/"),
            "top_floor": bool(TOP_FLOOR_RE.search(desc)),
            # Worth surfacing as a negative: top floor is a stated preference, so a
            # unit the owner describes as ground floor is a known miss, not unknown.
            "ground_floor": bool(GROUND_FLOOR_RE.search(desc)) and not TOP_FLOOR_RE.search(desc),
            "elevator": bool(NO_STAIRS_RE.search(desc))}


def main():
    force = "--force" in sys.argv
    d = json.loads(APTS_FILE.read_text())
    apts = d["apartments"]
    cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}

    # Build a lookup of every live listing so entries can be matched to a slug.
    live = {}
    for city, url in CITIES:
        try:
            live.update(parse(fetch(url)))
        except Exception as e:
            print("WARNING: could not load %s (%s)" % (city, e))
    if not live:
        print("No live listings retrieved -- nothing to match against. Aborting.")
        sys.exit(1)

    by_coord = {coord_key(L["lat"], L["lng"]): L for L in live.values()}
    by_name = {norm_name(L["name"]): L for L in live.values()}

    filled = matched = 0
    for a in apts:
        if a.get("phone") and a.get("photos") and not force:
            continue
        L = by_coord.get(coord_key(a["lat"], a["lng"])) or by_name.get(norm_name(a["name"]))
        if not L:
            continue
        matched += 1
        slug = L["slug"]
        if slug not in cache or force:
            try:
                cache[slug] = scrape(slug)
            except Exception as e:
                print("  ! %s: %s" % (a["name"], e))
                continue
            time.sleep(0.6)
        info = cache[slug]

        if info.get("phone") and not a.get("phone"):
            a["phone"] = info["phone"]
        if info.get("photos"):
            a["photos"] = info["photos"]
        if info.get("url"):
            a["url"] = info["url"]
        if info.get("desc") and not a.get("desc"):
            a["desc"] = info["desc"]
        if info.get("top_floor"):
            a["top_floor"] = True
            a.pop("ground_floor", None)
            if "TOP FLOOR" not in a["notes"]:
                a["notes"] = "⭐ TOP FLOOR (owner's own words) • " + a["notes"]
        elif info.get("ground_floor"):
            a["ground_floor"] = True
            if "GROUND FLOOR" not in a["notes"]:
                a["notes"] = "⚠️ GROUND FLOOR per the listing • " + a["notes"]
        if info.get("elevator"):
            a["elevator"] = True
        filled += 1

    CACHE_FILE.write_text(json.dumps(cache, indent=1, sort_keys=True))
    APTS_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    print("Matched %d, enriched %d of %d listings." % (matched, filled, len(apts)))
    print("  with phone:  %d" % sum(1 for a in apts if a.get("phone")))
    print("  with photos: %d" % sum(1 for a in apts if a.get("photos")))
    print("  top floor:   %d" % sum(1 for a in apts if a.get("top_floor")))


if __name__ == "__main__":
    main()
