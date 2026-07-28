#!/usr/bin/env python3
"""Re-measure every tracked property against its live listing and re-tier it.

Why this exists: the 7/27 sq-ft fix was written into the Documents copy of refresh.py and
never deployed to this engine, so the daily job kept running the old max()-across-floorplans
code for six more days and auto-added properties carrying the largest floorplan's size next
to the cheapest unit's rent. Those numbers are on the map right now. This pass replaces
every one of them with a size measured against the live page, and applies the criteria
Michael set on 7/28 (in-unit washer/dryer is now a hard requirement).

  python3 audit.py            # audit only, writes a report, changes nothing
  python3 audit.py --write    # apply the corrections to apartments.json

Nothing is estimated. A property whose page can't be read keeps its old number and is
flagged unverified rather than being quietly "corrected" to a guess.
"""
import json, pathlib, re, sys, datetime
import listing

HERE = pathlib.Path(__file__).resolve().parent
APTS = HERE / "apartments.json"
DETAIL_CACHE = HERE / "listing-cache.json"
FLOOD_CACHE = HERE / "flood-cache.json"
REPORTS = HERE / "reports"

# Criteria as Michael restated them 2026-07-28.
PRICE_MIN, PRICE_MAX = 1200, 1600
SQFT_MIN = 700
LEASE_OK = range(6, 13)   # 6-12 month leases


def money(s):
    m = re.search(r"[\d,]+", str(s) or "")
    return int(m.group(0).replace(",", "")) if m else None


def bed_list(s):
    return [int(b) for b in re.findall(r"(\d+)BR", str(s) or "")] or None


def main():
    write = "--write" in sys.argv
    data = json.loads(APTS.read_text())
    apts = data["apartments"]
    dcache = json.loads(DETAIL_CACHE.read_text()) if DETAIL_CACHE.exists() else {}
    fcache = json.loads(FLOOD_CACHE.read_text()) if FLOOD_CACHE.exists() else {}

    rows, changed = [], 0
    for a in apts:
        url = a.get("url") or ""
        rec = {"num": a["num"], "name": a["name"], "old_sqft": a.get("sqft"),
               "old_tier": a.get("tier"), "price": money(a.get("price"))}

        if "apartmentlist" not in url:
            # Zillow-sourced entries are NOT unverified -- their size, beds and rent come
            # from Zillow's own listing data. What they lack is an amenity list, which is
            # exactly what tier L already means. Re-auditing them here would strip that
            # tier and demote real finds to "no live listing", which is simply false.
            if (a.get("source") or "").startswith("zillow"):
                rec.update(new_sqft=a.get("sqft"), laundry=a.get("laundry"), verdict="SKIP",
                           why="Zillow lead — sized by Zillow, amenities unknown by design")
                rows.append(rec)
                continue
            rec.update(new_sqft=a.get("sqft"), laundry=None, verdict="UNVERIFIED",
                       why="no live listing page (carried over from the original list)")
            rows.append(rec)
            continue

        d = listing.detail(url, cache=dcache)
        beds = bed_list(a.get("beds")) or sorted(d["sqft_by_bed"])
        price_by_bed = d["price_by_bed"]

        # Size the unit he could actually rent: among bed counts whose own price is in
        # budget, take the best size. Never max() across every floorplan on the page.
        ok_beds = [b for b in beds
                   if PRICE_MIN <= (price_by_bed.get(b) or rec["price"] or 0) <= PRICE_MAX]
        if not ok_beds:
            ok_beds = [b for b in beds if b in d["sqft_by_bed"]]
        sizes = [(d["sqft_by_bed"][b], b) for b in ok_beds if b in d["sqft_by_bed"]]
        new_sqft, new_bed = max(sizes) if sizes else (None, None)

        rec.update(new_sqft=new_sqft, new_bed=new_bed,
                   laundry=d.get("in_unit_laundry"),
                   laundry_note=d.get("laundry_note"),
                   leases=sorted(set(d["lease_lengths"])),
                   specials=d.get("specials"), rating=d.get("rating"),
                   reviews=d.get("review_count"), flags=d.get("flags"),
                   quotes=d.get("review_quotes") or [], phone=d.get("phone"),
                   amenities=d.get("amenities") or [], desc=d.get("description") or "",
                   price_by_bed=price_by_bed,
                   zone=listing.flood_zone(a["lat"], a["lng"], cache=fcache))

        # Verdict against the 7/28 criteria.
        live_price = min([p for p in price_by_bed.values() if p], default=rec["price"])
        fails, notes = [], []
        if new_sqft is None:
            fails.append("size not published")
        elif new_sqft < SQFT_MIN:
            fails.append("%d sq ft < %d" % (new_sqft, SQFT_MIN))
        if live_price and not (PRICE_MIN <= live_price <= PRICE_MAX):
            fails.append("$%s outside $%d-$%d" % (format(live_price, ","), PRICE_MIN, PRICE_MAX))
        if d.get("in_unit_laundry") is False:
            fails.append("no in-unit washer/dryer")
        elif d.get("in_unit_laundry") in (None, "unclear"):
            notes.append("laundry unconfirmed — ask")
        if rec["leases"] and not any(l in LEASE_OK for l in rec["leases"]):
            notes.append("lease %s mo" % "/".join(str(l) for l in rec["leases"]))

        if fails:
            rec["verdict"], rec["why"] = "C", "; ".join(fails)
        elif notes:
            rec["verdict"], rec["why"] = "B", "; ".join(notes)
        else:
            rec["verdict"], rec["why"] = "A", "meets every hard criterion"

        if new_sqft and new_sqft != a.get("sqft"):
            changed += 1
        rows.append(rec)

    DETAIL_CACHE.write_text(json.dumps(dcache, indent=1, sort_keys=True))
    FLOOD_CACHE.write_text(json.dumps(fcache, indent=1, sort_keys=True))

    # ---- report -------------------------------------------------------------
    L = ["APARTMENT AUDIT — %s" % datetime.date.today().strftime("%b %d, %Y"),
         "Criteria: $%d-$%d · 1-2BR · %d+ sq ft · IN-UNIT washer/dryer required · 6-12 mo lease"
         % (PRICE_MIN, PRICE_MAX, SQFT_MIN), ""]
    wrong = [r for r in rows if r.get("new_sqft") and r["new_sqft"] != r["old_sqft"]]
    L += ["=" * 78, "SQUARE FOOTAGE CORRECTIONS (%d of %d)" % (len(wrong), len(rows)), "=" * 78, ""]
    for r in sorted(wrong, key=lambda r: -(abs((r["new_sqft"] or 0) - (r["old_sqft"] or 0)))):
        L.append("  #%-3d %-42s %s -> %s sq ft  (%+d)"
                 % (r["num"], r["name"][:42], r["old_sqft"], r["new_sqft"],
                    (r["new_sqft"] or 0) - (r["old_sqft"] or 0)))
    for v, title in [("A", "TIER A — meets everything"),
                     ("B", "TIER B — one thing to confirm on the phone"),
                     ("C", "TIER C — fails a hard criterion"),
                     ("UNVERIFIED", "UNVERIFIED — no live page")]:
        grp = [r for r in rows if r["verdict"] == v]
        L += ["", "=" * 78, "%s  (%d)" % (title, len(grp)), "=" * 78, ""]
        for r in sorted(grp, key=lambda r: -(r.get("new_sqft") or 0)):
            extra = []
            if r.get("specials"):
                extra.append("DEAL: " + r["specials"][:60])
            if r.get("rating"):
                extra.append("%.1f★ (%s)" % (r["rating"], r.get("reviews") or "?"))
            if r.get("flags"):
                extra.append("+".join(r["flags"]))
            if r.get("zone"):
                extra.append("FEMA " + r["zone"].split(" – ")[0])
            L.append("  #%-3d %-40s %-7s %s sq ft — %s"
                     % (r["num"], r["name"][:40],
                        "$%s" % format(r["price"], ",") if r["price"] else "?",
                        r.get("new_sqft") or "?", r["why"]))
            if extra:
                L.append("        " + " · ".join(extra))

    report = "\n".join(L)
    REPORTS.mkdir(exist_ok=True)
    p = REPORTS / ("audit-%s.txt" % datetime.date.today().isoformat())
    n = 2
    while p.exists():
        p = REPORTS / ("audit-%s-run%d.txt" % (datetime.date.today().isoformat(), n))
        n += 1
    p.write_text(report)
    print(report)
    print("\nreport: %s" % p)

    if write:
        by_num = {r["num"]: r for r in rows}
        for a in apts:
            r = by_num[a["num"]]
            if r["verdict"] == "SKIP":
                continue
            if r["verdict"] == "UNVERIFIED":
                # These 8 carried over from the original 7/20 list and have no live listing
                # page. Leaving them at their old tier let them render as "Meets everything"
                # next to a "W/D — ask" badge -- a claim the data does not support. Nothing
                # about them has been checked: not the size, not the rent, not the laundry.
                a["verified"] = False
                a["tier"] = "B"
                a["tier_why"] = ("no live listing found — size, rent and laundry are all "
                                 "unverified, carried from the Jul 20 list. Confirm by phone.")
                a["laundry"] = None
                continue
            if r.get("new_sqft"):
                a["sqft"] = r["new_sqft"]
                if r.get("new_bed"):
                    a["beds"] = "%dBR" % r["new_bed"]
            a["tier"] = r["verdict"]
            a["tier_why"] = r["why"]
            a["laundry"] = r["laundry"]
            if r.get("laundry_note"):
                a["laundry_note"] = r["laundry_note"]
            a["lease_months"] = r.get("leases") or []
            a["specials"] = r.get("specials")
            a["rating"] = r.get("rating")
            a["reviews"] = r.get("reviews")
            a["review_quotes"] = r.get("quotes") or []
            a["amenities"] = r.get("amenities") or []
            if r.get("phone") and not a.get("phone"):
                a["phone"] = r["phone"]
            if r.get("desc") and not a.get("description"):
                a["description"] = r["desc"]
            a["flood_zone"] = r.get("zone")
            a["perks"] = r.get("flags") or []
            a["verified"] = True
            a["verified_on"] = datetime.date.today().isoformat()
        data["criteria"] = {
            "price_min": PRICE_MIN, "price_max": PRICE_MAX, "beds": "1-2",
            "sqft_min": SQFT_MIN,
            "laundry": "in-unit washer/dryer REQUIRED (shared/on-site does not count)",
            "lease": "6-12 months",
            "types": "apartment, house, townhouse, condo",
            "areas": "St. Petersburg (primary), Pinellas Park, Largo (edge)",
            "prefs": "specials/deals, good reviews, updated units, high ceilings a plus, top floor a plus",
        }
        APTS.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print("WROTE apartments.json — %d sq ft corrections applied" % len(wrong))


if __name__ == "__main__":
    main()
