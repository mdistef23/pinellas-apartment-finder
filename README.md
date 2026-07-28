# Pinellas Apartment Finder

A rental-search pipeline that scrapes six listing sites, verifies every number against the
source page, and regenerates a live map, a tracker and a PDF on a daily schedule.

Built to solve a real apartment hunt in Pinellas County, Florida. ~3,200 lines of Python, no
frameworks, no external dependencies beyond the standard library.

---

## What it does

```
scan.py     ApartmentList across 13 municipalities — every listing measured against its own page
zillow.py   Zillow discovery (search payload; detail pages are blocked, so its finds stay flagged)
others.py   Zumper · PadMapper · Dwellsy · Craigslist
merge.py    appends genuinely new buildings, tiered, deduped three independent ways
audit.py    re-measures and re-tiers everything already tracked
build.py    regenerates the map, the tracker and the PDF, then publishes them
daily.sh    the 8 AM chain that runs all of the above
```

Results are tiered by how well the listing is *evidenced*, not just by how good it looks:

| Tier | Meaning |
|---|---|
| **A** | Meets every hard criterion, in-unit laundry **confirmed on the listing** |
| **B** | Everything fits but a required amenity isn't published — one phone call decides it |
| **L** | Lead from a source whose detail pages are blocked: size and rent are real, amenities unknown |
| **C** | Fails a hard criterion; kept so it doesn't get re-researched |

---

## The interesting problems

**Square footage is a trap.** A listing page carries many floorplans. Taking `max()` across
them glues the largest apartment's size onto the cheapest unit's rent — a 1-bedroom was being
reported at 1,262 sq ft when the 1-bedroom is 576. Size is now always paired to the bed count
it belongs to, and only floorplans whose own price is in budget are considered.

**Feeds publish placeholders that look like data.** One source uses `2^63` as its "unknown"
square footage. Unfiltered, it renders as *"9,223,372,036,854,776,000 sq ft"* and — worse —
scores as the largest apartment ever built and sorts to rank #1. Values are bounded at the
source *and* again at render time.

**Substring matching is not amenity matching.** `"Dishwasher"` contains `"washer"`. Matching
on that marks every listing with a dishwasher as having in-unit laundry. Amenity detection
runs against explicit vocabularies, and a conflict between the amenity chips and the owner's
own description resolves to an explicit *unclear* rather than a guess in either direction.

**Deduplication needs three independent keys.** Each of these alone let a duplicate through:

- a rounded coordinate grid — two addresses 40 ft apart rounded into different cells
- the property name — *"49th Street"* vs *"49th Street Apartments"*, same listing
- distance — two sites geocoded the same building **2,195 ft apart**

So matching runs on listing slug, then a normalised street-address key, then distance.

**Scraped ratings are easy to get wrong.** Reading the first `ratingValue` on a page returns
one individual review, not the average — a property showed 5.0★ when its actual average was
4.25 across four reviews. Ratings come from the structured aggregate, and each source's scale
is stored alongside the value, because one site rates out of 10 and another out of 5.

**Zero results and a broken parser look identical.** A scraper that silently reports "0 new
listings" when its selectors have moved is indistinguishable from a quiet week. Every source
re-fetches unfiltered before reporting nothing, and exits non-zero if the markup really moved.

**Flood risk is never estimated.** Each address is a live point query against FEMA's National
Flood Hazard Layer, with retries — because a dropped request returning `None` reads exactly
like "no flood risk here", which is the one wrong answer that matters on the Gulf coast.

---

## Design notes

- **Idempotent by construction.** Running the daily chain twice adds nothing the second time.
  Lead intake is capped against the map total rather than per run, so the list can't creep
  upward day after day.
- **Fails loudly.** Anything that can't be verified is labelled unverified rather than
  presented as fact.
- **No server.** Output is self-contained HTML that opens from the filesystem.

## Running it

```bash
python3 scan.py --json cands.json      # ApartmentList sweep
python3 zillow.py --json zillow.json   # Zillow discovery
python3 others.py --json others.json   # the remaining four sources
python3 merge.py cands.json zillow.json --others others.json --write
python3 build.py                       # map + tracker + PDF
```

Python 3.9+. No pip install required.

## Not included

The generated output and the collected listing data are deliberately excluded — they contain
private landlords' phone numbers and a real person's shortlist. This repository is the pipeline
only.
