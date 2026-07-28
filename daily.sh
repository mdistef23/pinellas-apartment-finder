#!/bin/bash
# Daily 8:00 AM chain.
#
# Rebuilt 2026-07-28 to run the criteria Michael actually set (in-unit washer/dryer required,
# $1,200-$1,600, 700+ sq ft, 13 areas, any building type) instead of the old two-city refresh.
#
# Why everything lives HERE: on 7/27 the sq-ft fix was written into the copy in ~/Documents
# and never reached this engine, so the 8 AM job kept running the broken code for six more
# days and put wrong sizes on the map. This is the only copy that runs. Don't edit the
# Documents copies and expect anything to change.
#
#   scan.py    ApartmentList across every area, each listing measured against its own page
#   zillow.py  Zillow discovery pass (search pages work again as of 7/28; detail pages 403)
#   merge.py   appends what's genuinely new, tiered, deduped against the map three ways
#   build.py   regenerates map + tracker + PDF and publishes them
set -o pipefail
cd "$HOME/.apartment-check" || exit 1
echo "===== $(date '+%Y-%m-%d %H:%M %Z') ====="

python3 scan.py --json /tmp/apt-cands.json || { echo "scan.py FAILED — not reporting a quiet day"; exit 1; }
python3 zillow.py --json /tmp/apt-zillow.json || echo "zillow.py failed (non-fatal — ApartmentList still ran)"
python3 others.py --json /tmp/apt-others.json --limit-cl 35 || echo "others.py failed (non-fatal)"

# merge never overwrites an existing property; it only appends genuinely new buildings and
# tiers them by what the listing actually publishes.
python3 merge.py /tmp/apt-cands.json /tmp/apt-zillow.json --others /tmp/apt-others.json --zillow-top 40 --write

python3 enrich.py 2>/dev/null   # phone/photos for anything just added
python3 build.py                # map + tracker + PDF, published to Documents and Desktop
