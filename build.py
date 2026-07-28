#!/usr/bin/env python3
"""Generate the map (index.html) and the tracker (tracker.html) from apartments.json.

Both files are GENERATED. Edit apartments.json and re-run; hand edits here get overwritten.

New on 2026-07-28, at Michael's request: the map carries a right-hand sidebar listing every
property with its address and a direct link to the listing, so the map is no longer the only
way in -- clicking a dot was the only route before, which made scanning the list impossible.
The sidebar and the pins are driven by the same array and the same filter state, so what you
see in the list is always exactly what you see on the map.

Tiers: A meets everything (in-unit W/D confirmed) · B one call away · C fails a hard rule,
kept for reference · L Zillow lead (real size, amenities unknown).
"""
import json, os, pathlib, re, datetime, shutil

HERE = pathlib.Path(__file__).resolve().parent
DATA = json.loads((HERE / "apartments.json").read_text())
APTS = DATA["apartments"]
CRIT = DATA.get("criteria", {})

PUBLISH = [pathlib.Path.home() / "Documents" / "Pinellas Apartment Map",
           pathlib.Path.home() / "Desktop" / "Apartment Search 2026"]

TIER_LABEL = {
    "A": "Meets everything",
    "B": "One call away",
    "C": "Fails a hard rule",
    "L": "Zillow lead",
}


def money(s):
    m = re.search(r"[\d,]+", str(s) or "")
    return int(m.group(0).replace(",", "")) if m else None


def maps_link(a):
    return ("https://www.google.com/maps/search/?api=1&query="
            + __import__("urllib.parse", fromlist=["quote"]).quote(a.get("address") or a["name"]))


def reviews_link(a):
    q = "%s %s reviews" % (a["name"], (a.get("address") or "").split(",")[-2:][0] if a.get("address") else "")
    return ("https://www.google.com/search?q="
            + __import__("urllib.parse", fromlist=["quote"]).quote(q.strip()))


def row(a):
    """One property as the compact record both views render from."""
    price = money(a.get("price"))
    # Last line of defence on size. A feed once handed us 2^63 as its "unknown" and it
    # rendered as "9,223,372,036,854,776,000 sq ft" and sorted to rank #1. Whatever the
    # source did upstream, nothing outside a livable range reaches a page from here.
    sqft = a.get("sqft")
    if not isinstance(sqft, int) or not (200 <= sqft <= 5000):
        sqft = None
    laundry = a.get("laundry")
    return {
        "num": a["num"],
        "name": a["name"],
        "price": a.get("price") or "?",
        "priceN": price or 0,
        "beds": a.get("beds") or "?",
        "sqft": sqft,
        "ppsf": round(price / sqft, 2) if price and sqft else None,
        "address": a.get("address") or a["name"],
        "lat": a["lat"], "lng": a["lng"],
        "tier": a.get("tier", "B"),
        "why": a.get("tier_why") or "",
        "status": a.get("status", "new"),
        "laundry": ("yes" if laundry is True else
                    "no" if laundry is False else
                    "unclear" if laundry == "unclear" else "unknown"),
        "laundryNote": a.get("laundry_note") or "",
        "lease": a.get("lease_months") or [],
        "specials": a.get("specials") or "",
        "rating": a.get("rating"),
        "reviews": a.get("reviews"),
        "quotes": a.get("review_quotes") or [],
        "perks": a.get("perks") or [],
        "zone": a.get("flood_zone") or "",
        "miles": a.get("miles_downtown"),
        "city": a.get("city") or "",
        "homeType": a.get("home_type") or "",
        "days": a.get("days_listed"),
        "estimate": a.get("rent_estimate"),
        "cut": a.get("price_cut") or "",
        "source": a.get("source") or "",
        "phone": a.get("phone") or "",
        "url": a.get("url") or a.get("search_url") or "",
        "hasListing": bool(a.get("url")),
        "maps": maps_link(a),
        "reviewsUrl": reviews_link(a),
        "photos": (a.get("photos") or [])[:5],
        "desc": (a.get("description") or a.get("desc") or "")[:700],
        "notes": a.get("notes") or "",
        "unverified": a.get("verified") is False,
        "added": a.get("added") or "",
        "ratingScale": a.get("rating_scale") or 5,
        "alsoKnownAs": a.get("also_known_as") or "",
        "sqftNote": a.get("sqft_note") or "",
        "amenities": (a.get("amenities") or [])[:14],
    }


ROWS = [row(a) for a in APTS]
STAMP = datetime.datetime.now().strftime("%b %d, %Y at %-I:%M %p")

# Shared by both pages so the map and the tracker can never drift apart visually.
CSS = """
:root{
  --bg:#f4f6f9; --panel:#ffffff; --ink:#16202e; --muted:#63718a; --line:#dde4ee;
  --a:#0f7b3f; --a-bg:#e4f5eb; --b:#b3720a; --b-bg:#fdf3e0;
  --c:#6b7684; --c-bg:#eef1f5; --l:#1763b8; --l-bg:#e7f0fb;
  --warn:#a32f2f; --warn-bg:#fdeaea;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
a{color:var(--l)}
.badge{display:inline-block;padding:1px 7px;border-radius:20px;font-size:10.5px;font-weight:700;
       letter-spacing:.02em;white-space:nowrap}
.tA{background:var(--a-bg);color:var(--a)} .tB{background:var(--b-bg);color:var(--b)}
.tC{background:var(--c-bg);color:var(--c)} .tL{background:var(--l-bg);color:var(--l)}
.wd-yes{background:var(--a-bg);color:var(--a)}
.wd-no{background:var(--warn-bg);color:var(--warn)}
.wd-unclear,.wd-unknown{background:var(--b-bg);color:var(--b)}
.deal{background:#fdf0d8;color:#8a5a00}
.zone-bad{background:var(--warn-bg);color:var(--warn)}
.zone-ok{background:var(--c-bg);color:var(--c)}
.perk{background:#eae7fb;color:#4b3fa0}
.btn{display:inline-block;text-decoration:none;background:var(--l);color:#fff!important;
     padding:5px 10px;border-radius:5px;font-size:11.5px;font-weight:700}
.btn.call{background:var(--a)} .btn.grey{background:#7b8698} .btn.ghost{background:#fff;
     color:var(--l)!important;border:1px solid var(--line)}
"""


# --------------------------------------------------------------------------- map
def build_map():
    js = "const APARTMENTS = " + json.dumps(ROWS, ensure_ascii=False) + ";"
    counts = {t: sum(1 for r in ROWS if r["tier"] == t) for t in "ABCL"}
    return """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta http-equiv="Cache-Control" content="no-store">
<title>Pinellas Apartment Map</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
""" + CSS + """
html,body{height:100%;overflow:hidden}
.shell{display:flex;height:100vh}
#map{flex:1 1 auto;height:100%}
.side{flex:0 0 400px;height:100%;background:var(--panel);border-left:1px solid var(--line);
      display:flex;flex-direction:column;box-shadow:-2px 0 10px rgba(20,30,50,.06)}
.side header{padding:12px 14px 10px;border-bottom:1px solid var(--line)}
.side h1{margin:0 0 2px;font-size:15px;letter-spacing:-.01em}
.side .sub{color:var(--muted);font-size:11.5px}
.tools{padding:9px 14px;border-bottom:1px solid var(--line);background:#fafbfd}
.tools input[type=search]{width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:6px;
  font-size:12.5px;background:#fff}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.chip{border:1px solid var(--line);background:#fff;border-radius:20px;padding:3px 10px;
      font-size:11px;font-weight:700;cursor:pointer;color:var(--muted)}
.chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.chip.on.cA{background:var(--a);border-color:var(--a)}
.chip.on.cB{background:var(--b);border-color:var(--b)}
.chip.on.cC{background:var(--c);border-color:var(--c)}
.chip.on.cL{background:var(--l);border-color:var(--l)}
.sortrow{display:flex;align-items:center;gap:6px;margin-top:8px;font-size:11px;color:var(--muted)}
.sortrow select{font-size:11px;padding:3px 5px;border:1px solid var(--line);border-radius:5px;background:#fff}
.count{padding:7px 14px;font-size:11.5px;color:var(--muted);background:#fafbfd;
       border-bottom:1px solid var(--line)}
.list{flex:1 1 auto;overflow-y:auto}
.card{padding:11px 14px;border-bottom:1px solid var(--line);cursor:pointer}
.card:hover{background:#f7f9fc}
.card.sel{background:#eef4fd;box-shadow:inset 3px 0 0 var(--l)}
.card .top{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.card .nm{font-weight:700;font-size:13px;line-height:1.3}
.card .nm .n{color:var(--muted);font-weight:700;margin-right:4px}
.card .pz{font-weight:700;font-size:13.5px;white-space:nowrap}
.card .specs{color:var(--muted);font-size:11.5px;margin-top:2px}
.card .addr{color:var(--muted);font-size:11.5px;margin-top:3px}
.card .tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.card .acts{display:flex;gap:5px;margin-top:8px;flex-wrap:wrap}
.card .deal-txt{font-size:11px;color:#8a5a00;background:#fdf7ea;border-left:3px solid #e8c26a;
                padding:4px 7px;border-radius:0 4px 4px 0;margin-top:6px}
.empty{padding:26px 16px;color:var(--muted);font-size:12.5px;text-align:center}
.apt-pin{background:#fff;border:2px solid #333;border-radius:50%;width:28px;height:28px;
         text-align:center;line-height:24px;font:700 12px Arial;color:#111;
         box-shadow:0 1px 4px rgba(0,0,0,.4)}
.apt-pin.pA{border-color:var(--a);background:var(--a-bg);color:var(--a)}
.apt-pin.pB{border-color:var(--b);background:var(--b-bg);color:var(--b)}
.apt-pin.pC{border-color:#9aa4b2;background:var(--c-bg);color:var(--c)}
.apt-pin.pL{border-color:var(--l);background:var(--l-bg);color:var(--l)}
.apt-pin.hi{transform:scale(1.35);z-index:9999!important;box-shadow:0 0 0 4px rgba(23,99,184,.35)}
.legend{background:rgba(255,255,255,.95);padding:8px 10px;border-radius:7px;color:#222;
        font:11px/1.5 Arial;box-shadow:0 1px 6px rgba(0,0,0,.3);max-width:210px}
.sw{display:inline-block;width:12px;height:12px;vertical-align:middle;margin-right:5px;
    border:1px solid rgba(0,0,0,.25)}
.pop{width:290px;font-size:12px}
.pop h4{margin:8px 10px 3px;font-size:13.5px}
.pop .gal{display:flex;gap:3px;overflow-x:auto;background:#111}
.pop .gal img{height:150px;width:290px;object-fit:cover;display:block}
.pop .body{padding:0 10px 10px}
.pop .desc{font-size:11px;color:var(--muted);max-height:90px;overflow-y:auto;
           border-left:3px solid var(--line);padding-left:7px;margin:6px 0}
@media (max-width:900px){.shell{flex-direction:column}.side{flex:0 0 46vh;border-left:0;
  border-top:1px solid var(--line)}}
</style></head>
<body>
<div class="shell">
  <div id="map"></div>
  <aside class="side">
    <header>
      <h1>Master Apartment Tracker</h1>
      <div class="sub">""" + "%d properties &middot; updated %s" % (len(ROWS), STAMP) + """<br>
      <a href="ranked.html">Ranked top picks</a> &middot; <a href="tracker.html">Full table</a></div>
    </header>
    <div class="tools">
      <input type="search" id="q" placeholder="Search address, name, city&hellip;">
      <div class="chips" id="chips">
        <span class="chip cA on" data-t="A">&#10003; Meets everything (""" + str(counts["A"]) + """)</span>
        <span class="chip cB on" data-t="B">&#9742; One call away (""" + str(counts["B"]) + """)</span>
        <span class="chip cL on" data-t="L">&#128142; Zillow leads (""" + str(counts["L"]) + """)</span>
        <span class="chip cC" data-t="C">Ruled out (""" + str(counts["C"]) + """)</span>
      </div>
      <div class="sortrow">
        <label for="sort">Sort</label>
        <select id="sort">
          <option value="best">Best fit</option>
          <option value="sqft">Biggest</option>
          <option value="price">Cheapest</option>
          <option value="ppsf">Best $/sq ft</option>
          <option value="miles">Closest to downtown</option>
          <option value="num">Number</option>
        </select>
      </div>
    </div>
    <div class="count" id="count"></div>
    <div class="list" id="list"></div>
  </aside>
</div>
<script>
/* GENERATED BY build.py FROM apartments.json - do not hand-edit. */
""" + js + """
const PINELLAS = L.latLngBounds([27.62,-82.92],[28.17,-82.53]);
const map = L.map('map',{center:[27.82,-82.68],zoom:12,minZoom:11,maxZoom:18,
  maxBounds:PINELLAS,maxBoundsViscosity:1.0});
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19,attribution:'&copy; OpenStreetMap'}).addTo(map);

/* Evacuation / storm-surge zones: FDEM's PRE-CACHED tile service. Kept exactly as-is --
   the earlier per-tile export method flickered on every zoom. */
const evac = L.tileLayer(
  'https://tiles.arcgis.com/tiles/3wFbqsFPLeKqOlIK/arcgis/rest/services/EvacZones20260512/MapServer/tile/{z}/{y}/{x}',
  {opacity:0.5,maxZoom:19,maxNativeZoom:16,
   attribution:'Evacuation zones: FL Div. of Emergency Management'}).addTo(map);
const Fema = L.TileLayer.extend({getTileUrl:function(c){
  const s=this.getTileSize(),nw=c.scaleBy(s),se=nw.add(s);
  const p1=L.CRS.EPSG3857.project(this._map.unproject(nw,c.z)),
        p2=L.CRS.EPSG3857.project(this._map.unproject(se,c.z));
  const bb=[Math.min(p1.x,p2.x),Math.min(p1.y,p2.y),Math.max(p1.x,p2.x),Math.max(p1.y,p2.y)].join(',');
  return "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/export?bbox="+bb+
    "&bboxSR=3857&imageSR=3857&size=256,256&dpi=96&layers=show:28&format=png32&transparent=true&f=image";
}});
const fema = new Fema("",{opacity:0.45,attribution:'Flood zones: FEMA NFHL'});
L.control.layers(null,
  {"\\u{1F300} Evacuation / surge zones (A\\u2013E)":evac,
   "\\u{1F30A} FEMA flood zones (AE/VE)":fema},
  {collapsed:false,position:'topright'}).addTo(map);

function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

/* One marker per property, kept in a map by number so the sidebar can drive them. */
const markers = {};
APARTMENTS.forEach(a=>{
  const icon=L.divIcon({className:'',
    html:'<div class="apt-pin p'+a.tier+'" data-n="'+a.num+'">'+a.num+'</div>',
    iconSize:[28,28],iconAnchor:[14,14]});
  const digits=(a.phone||'').replace(/[^0-9]/g,'');
  const gal=(a.photos&&a.photos.length)
    ? '<div class="gal">'+a.photos.map(p=>'<a href="'+(p.full||p)+'" target="_blank"><img src="'+
      (p.card||p)+'" loading="lazy" onerror="this.parentNode.remove()"></a>').join('')+'</div>' : '';
  const tags=[];
  tags.push('<span class="badge t'+a.tier+'">'+({A:'Meets everything',B:'One call away',
    C:'Ruled out',L:'Zillow lead'}[a.tier])+'</span>');
  if(a.laundry==='yes') tags.push('<span class="badge wd-yes">In-unit W/D</span>');
  else if(a.laundry==='no') tags.push('<span class="badge wd-no">No in-unit W/D</span>');
  else tags.push('<span class="badge wd-unclear">W/D — ask</span>');
  if(a.zone) tags.push('<span class="badge '+(/^(A|V)/.test(a.zone)?'zone-bad':'zone-ok')+
    '">FEMA '+esc(a.zone.split(' \\u2013 ')[0])+'</span>');
  (a.perks||[]).forEach(p=>tags.push('<span class="badge perk">'+esc(p.replace(/_/g,' '))+'</span>'));
  const pop='<div class="pop">'+gal+'<h4>#'+a.num+' '+esc(a.name)+'</h4><div class="body">'
    +'<div><b>'+esc(a.price)+'</b> · '+esc(a.beds)+(a.sqft?' · '+a.sqft+' sq ft':'')
    +(a.ppsf?' · $'+a.ppsf+'/sq ft':'')+'</div>'
    +'<div style="color:#63718a;font-size:11px;margin:3px 0">'+esc(a.address)+'</div>'
    +'<div class="tags" style="display:flex;flex-wrap:wrap;gap:4px;margin:6px 0">'+tags.join('')+'</div>'
    +(a.specials?'<div class="deal-txt" style="font-size:11px;color:#8a5a00">\\u{1F4B0} '+esc(a.specials)+'</div>':'')
    +(a.desc?'<div class="desc">'+esc(a.desc)+'</div>':'')
    +'<div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:8px">'
    +(digits?'<a class="btn call" href="tel:'+digits+'">\\u260E '+esc(a.phone)+'</a>':'')
    +(a.url?'<a class="btn" href="'+esc(a.url)+'" target="_blank">'+(a.hasListing?'Listing':'Search')+'</a>':'')
    +'<a class="btn grey" href="'+esc(a.maps)+'" target="_blank">Maps</a>'
    +'<a class="btn ghost" href="'+esc(a.reviewsUrl)+'" target="_blank">Reviews</a>'
    +'</div></div></div>';
  const m=L.marker([a.lat,a.lng],{icon}).bindPopup(pop,{maxWidth:320,minWidth:290})
    .bindTooltip('#'+a.num+' '+a.name+' \\u2014 '+a.price,{sticky:true});
  m.on('click',()=>select(a.num,false));
  markers[a.num]=m;
});
L.circleMarker([27.7709,-82.6403],{radius:6,color:'#1565c0',fillColor:'#42a5f5',
  fillOpacity:.9,weight:2}).addTo(map).bindTooltip('Downtown St. Pete');

const legend=L.control({position:'bottomleft'});
legend.onAdd=function(){const d=L.DomUtil.create('div','legend');
  const r=(c,l)=>'<span class="sw" style="background:'+c+'"></span>'+l+'<br>';
  d.innerHTML='<b>Evacuation / Surge Zone</b><br>'+r('rgb(255,0,0)','A \\u2014 highest risk')
   +r('rgb(255,170,0)','B')+r('rgb(255,255,0)','C')+r('rgb(76,230,0)','D')
   +r('rgb(169,0,230)','E \\u2014 lowest');return d;};
legend.addTo(map);

/* ---- sidebar: same data, same filter state as the pins ---- */
const listEl=document.getElementById('list'), countEl=document.getElementById('count');
const qEl=document.getElementById('q'), sortEl=document.getElementById('sort');
let tiers=new Set(['A','B','L']), selected=null;

function score(a){
  /* Tier leads the ordering. Without this a big unverified Zillow lead outranks a place
     that actually meets the hard washer/dryer rule, purely on square footage -- which
     defeats the point of having a hard rule. Size and value still order within a tier. */
  let s={A:1000,B:600,L:300,C:0}[a.tier]||0;
  if(a.sqft) s+=(a.sqft-700)/100;
  s+=(1600-a.priceN)/100;
  if(a.laundry==='yes') s+=6; else if(a.laundry==='no') s-=8;
  if(a.specials) s+=2;
  if(a.rating&&a.rating>=4) s+=2;
  if(a.miles!=null) s-=Math.max(0,a.miles-5)*0.6;
  if(/^(A|V)/.test(a.zone||'')) s-=4;
  (a.perks||[]).forEach(p=>{if(p==='top_floor')s+=2;if(p==='updated')s+=1.5;
    if(p==='high_ceilings')s+=1.5;if(p==='ground_floor')s-=1.5;});
  return s;
}
function visible(){
  const q=(qEl.value||'').toLowerCase().trim();
  let out=APARTMENTS.filter(a=>tiers.has(a.tier));
  if(q) out=out.filter(a=>(a.name+' '+a.address+' '+a.city+' '+(a.homeType||'')).toLowerCase().includes(q));
  const s=sortEl.value;
  const by={best:(x,y)=>score(y)-score(x), sqft:(x,y)=>(y.sqft||0)-(x.sqft||0),
    price:(x,y)=>x.priceN-y.priceN, ppsf:(x,y)=>(x.ppsf||99)-(y.ppsf||99),
    miles:(x,y)=>(x.miles==null?99:x.miles)-(y.miles==null?99:y.miles),
    num:(x,y)=>x.num-y.num};
  return out.sort(by[s]||by.best);
}
function card(a){
  const tags=[];
  tags.push('<span class="badge t'+a.tier+'">'+({A:'Meets everything',B:'One call away',
    C:'Ruled out',L:'Zillow lead'}[a.tier])+'</span>');
  if(a.laundry==='yes') tags.push('<span class="badge wd-yes">In-unit W/D</span>');
  else if(a.laundry==='no') tags.push('<span class="badge wd-no">No W/D</span>');
  else tags.push('<span class="badge wd-unclear">W/D — ask</span>');
  if(a.zone) tags.push('<span class="badge '+(/^(A|V)/.test(a.zone)?'zone-bad':'zone-ok')+
    '">'+esc(a.zone.split(' \\u2013 ')[0])+'</span>');
  if(a.unverified) tags.push('<span class="badge wd-no">Unverified</span>');
  if(a.unverified) tags.push('<span class="badge wd-no">Unverified</span>');
  if(a.specials) tags.push('<span class="badge deal">Deal</span>');
  if(a.rating) tags.push('<span class="badge tC">'+a.rating+'/'+(a.ratingScale||5)+'\\u2605'
    +(a.reviews?' ('+a.reviews+')':'')+'</span>');
  if(a.lease&&a.lease.length) tags.push('<span class="badge tC">'+a.lease.join('/')+' mo lease</span>');
  if(a.homeType) tags.push('<span class="badge tC">'+esc(a.homeType)+'</span>');
  (a.perks||[]).forEach(p=>tags.push('<span class="badge perk">'+esc(p.replace(/_/g,' '))+'</span>'));
  if(a.source) tags.push('<span class="badge tC">'+esc(a.source)+'</span>');
  const digits=(a.phone||'').replace(/[^0-9]/g,'');
  const specs=[a.beds,(a.sqft?a.sqft+' sq ft':'size n/a'),(a.ppsf?'$'+a.ppsf+'/sq ft':null),
    (a.miles!=null?a.miles+' mi out':null),(a.homeType||null),
    (a.days!=null?'listed '+a.days+'d ago':null)].filter(Boolean).join(' \\u00b7 ');
  return '<div class="card'+(selected===a.num?' sel':'')+'" data-n="'+a.num+'">'
    +'<div class="top"><div class="nm"><span class="n">#'+a.num+'</span>'+esc(a.name)+'</div>'
    +'<div class="pz">'+esc(a.price)+'</div></div>'
    +'<div class="specs">'+esc(specs)+'</div>'
    +'<div class="addr">'+esc(a.address)+'</div>'
    +(a.alsoKnownAs?'<div class="addr">formerly '+esc(a.alsoKnownAs)+'</div>':'')
    +'<div class="tags">'+tags.join('')+'</div>'
    +(a.specials?'<div class="deal-txt">\\u{1F4B0} '+esc(a.specials)+'</div>':'')
    +(a.cut?'<div class="addr">\\u{1F4B0} price cut: '+esc(a.cut)+'</div>':'')
    +(a.estimate&&a.estimate>a.priceN+50
       ?'<div class="addr">\\u{1F4C9} $'+(a.estimate-a.priceN).toLocaleString()
        +' under Zillow\\u2019s own rent estimate</div>':'')
    +(a.sqftNote?'<div class="addr">\\u26A0 '+esc(a.sqftNote)+'</div>':'')
    +(a.laundryNote?'<div class="addr">\\u26A0 '+esc(a.laundryNote)+'</div>':'')
    +'<div class="acts">'
    +(a.url?'<a class="btn" href="'+esc(a.url)+'" target="_blank" onclick="event.stopPropagation()">'
        +(a.hasListing?'Listing':'Search')+'</a>':'')
    +(digits?'<a class="btn call" href="tel:'+digits+'" onclick="event.stopPropagation()">\\u260E Call</a>':'')
    +'<a class="btn grey" href="'+esc(a.maps)+'" target="_blank" onclick="event.stopPropagation()">Maps</a>'
    +'<a class="btn ghost" href="'+esc(a.reviewsUrl)+'" target="_blank" onclick="event.stopPropagation()">Reviews</a>'
    +'</div></div>';
}
function render(){
  const v=visible();
  countEl.textContent=v.length+' showing of '+APARTMENTS.length
    +(tiers.has('C')?'':'  \\u00b7  ruled-out hidden');
  listEl.innerHTML=v.length?v.map(card).join(''):'<div class="empty">Nothing matches that filter.</div>';
  Object.entries(markers).forEach(([n,m])=>{
    const on=v.some(a=>a.num==n);
    if(on&&!map.hasLayer(m)) m.addTo(map);
    if(!on&&map.hasLayer(m)) map.removeLayer(m);
  });
}
function select(num,fly){
  selected=num; render();
  const el=listEl.querySelector('.card[data-n="'+num+'"]');
  if(el) el.scrollIntoView({block:'nearest',behavior:'smooth'});
  const m=markers[num];
  if(m){ if(fly) map.flyTo(m.getLatLng(),Math.max(map.getZoom(),15),{duration:.6});
         m.openPopup(); }
}
listEl.addEventListener('click',e=>{
  const c=e.target.closest('.card'); if(!c) return; select(+c.dataset.n,true);
});
document.getElementById('chips').addEventListener('click',e=>{
  const c=e.target.closest('.chip'); if(!c) return;
  const t=c.dataset.t;
  if(tiers.has(t)){tiers.delete(t);c.classList.remove('on');}
  else{tiers.add(t);c.classList.add('on');}
  render();
});
qEl.addEventListener('input',render); sortEl.addEventListener('change',render);
render();
</script></body></html>"""


# ----------------------------------------------------------------------- tracker
def build_tracker():
    order = {"A": 0, "B": 1, "L": 2, "C": 3}
    rows = sorted(ROWS, key=lambda r: (order.get(r["tier"], 9), -(r["sqft"] or 0)))
    js = "const ROWS = " + json.dumps(rows, ensure_ascii=False) + ";"
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Cache-Control" content="no-store">
<title>Apartment Tracker</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>""" + CSS + """
body{padding:0}
.wrap{max-width:100%;padding:18px 22px}
h1{margin:0 0 3px;font-size:20px}
.sub{color:var(--muted);font-size:12.5px;margin-bottom:14px}
.crit{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 13px;
      font-size:12px;color:var(--muted);margin-bottom:14px}
.crit b{color:var(--ink)}
.tools{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
.tools input[type=search]{padding:7px 10px;border:1px solid var(--line);border-radius:6px;
  font-size:13px;min-width:260px}
.chip{border:1px solid var(--line);background:#fff;border-radius:20px;padding:4px 11px;
      font-size:11.5px;font-weight:700;cursor:pointer;color:var(--muted)}
.chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.chip.on.cA{background:var(--a);border-color:var(--a)}
.chip.on.cB{background:var(--b);border-color:var(--b)}
.chip.on.cC{background:var(--c);border-color:var(--c)}
.chip.on.cL{background:var(--l);border-color:var(--l)}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);
      border-radius:8px;overflow:hidden;font-size:12.5px}
th{background:#f0f3f8;text-align:left;padding:9px 10px;font-size:11px;text-transform:uppercase;
   letter-spacing:.04em;color:var(--muted);position:sticky;top:0;cursor:pointer;white-space:nowrap}
td{padding:9px 10px;border-top:1px solid var(--line);vertical-align:top}
tr:hover td{background:#f7f9fc}
.nm{font-weight:700}
.nm a{text-decoration:none}
.sm{color:var(--muted);font-size:11px}
.tagcell{display:flex;flex-wrap:wrap;gap:3px;max-width:230px}
.acts{display:flex;gap:4px;flex-wrap:wrap}
.deal-txt{font-size:11px;color:#8a5a00;margin-top:3px;max-width:260px}
.foot{margin:16px 0 40px;background:var(--panel);border:1px solid var(--line);border-radius:8px;
      padding:13px 15px;font-size:12.5px;color:var(--ink);max-width:900px}
.foot h3{margin:0 0 7px;font-size:13.5px}
.foot li{margin-bottom:4px;color:var(--muted)}

/* Print / PDF. The screen table is wide by design; in portrait it collapses the property
   column to three words per line and runs to 24 pages. Landscape, smaller type, and no
   interactive chrome makes it a document you can actually read in the car. */
@page{size:landscape;margin:9mm}
@media print{
  body{background:#fff}
  .wrap{padding:0}
  .tools,.crit .hideprint{display:none!important}
  table{font-size:9.5px;border-radius:0}
  th{padding:5px 6px;font-size:8.5px}
  td{padding:5px 6px}
  tr{break-inside:avoid}
  .badge{font-size:8px;padding:0 5px}
  .acts{display:none}
  .sm{font-size:8.5px}
  .deal-txt{font-size:8.5px;max-width:none}
  .nm a{color:#16202e;text-decoration:none}
  td:nth-child(9){max-width:120px}
  .foot{break-before:page;max-width:none;font-size:11px}
  .printonly{display:block!important}
}
.printonly{display:none}
</style></head><body><div class="wrap">
<h1>Apartment Tracker &mdash; St. Pete / Pinellas</h1>
<div class="sub">""" + "%d properties &middot; rebuilt %s &middot; " % (len(ROWS), STAMP) + """
<a href="index.html">Open the flood map &rarr;</a></div>
<div class="crit">
  <b>Criteria:</b> """ + esc_py("$%s–$%s · 1–2BR · %s+ sq ft · in-unit washer/dryer required · 6–12 month lease · apartment / house / townhouse / condo · St. Petersburg primary, Pinellas Park, Largo edge"
        % (format(CRIT.get("price_min", 1200), ","), format(CRIT.get("price_max", 1600), ","),
           CRIT.get("sqft_min", 700))) + """<br>
  <b>Plus:</b> move-in specials, good reviews, updated units, high ceilings, top floor.
  <div class="printonly" style="margin-top:6px">
    <b>This printout shows the live shortlist</b> — everything that meets the criteria, is one
    phone call from meeting them, or is a Zillow lead. Properties already ruled out are
    excluded from the PDF but kept in the tracker so they don't get re-researched.
  </div>
</div>
<div class="tools">
  <input type="search" id="q" placeholder="Search address, name, city&hellip;">
  <span class="chip cA on" data-t="A">Meets everything</span>
  <span class="chip cB on" data-t="B">One call away</span>
  <span class="chip cL on" data-t="L">Zillow leads</span>
  <span class="chip cC" data-t="C">Ruled out</span>
  <span class="sm" id="count"></span>
</div>
<table><thead><tr>
  <th data-s="num">#</th><th data-s="name">Property</th><th data-s="price">Rent</th>
  <th data-s="sqft">Size</th><th data-s="ppsf">$/sq ft</th><th data-s="miles">Miles</th>
  <th>Flags</th><th data-s="status">Status</th><th>Contact</th>
</tr></thead><tbody id="tb"></tbody></table>

<div class="foot">
  <h3>Ask on every call</h3>
  <ol>
    <li><b>Is the washer/dryer in the unit</b> &mdash; not on-site, not a hookup. This is the hard filter and half the listings don't publish it.</li>
    <li>What's available on the <b>top floor</b>?</li>
    <li>The real price for a <b>700+ sq ft</b> unit &mdash; not the teaser rate for the smallest floorplan.</li>
    <li>Total move-in cost including fees and deposit, and whether the advertised special still applies.</li>
    <li>Can they do a <b>6&ndash;12 month</b> lease?</li>
    <li><b>Did the building take water in Helene or Milton?</b> Then check the pin against the surge overlay on the map.</li>
  </ol>
  <div class="sm">Status values: new &rarr; watching &rarr; contacted &rarr; toured &rarr; applied &rarr; passed / gone.
  Edit the <code>status</code> field in <code>apartments.json</code> and re-run <code>build.py</code>.</div>
</div>
</div>
<script>
""" + js + """
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
let tiers=new Set(['A','B','L']), sortKey='tier', dir=1;
const tb=document.getElementById('tb'), qEl=document.getElementById('q');
function tags(a){
  const t=[];
  t.push('<span class="badge t'+a.tier+'">'+({A:'Meets everything',B:'One call away',
    C:'Ruled out',L:'Zillow lead'}[a.tier])+'</span>');
  if(a.laundry==='yes') t.push('<span class="badge wd-yes">In-unit W/D</span>');
  else if(a.laundry==='no') t.push('<span class="badge wd-no">No W/D</span>');
  else t.push('<span class="badge wd-unclear">W/D — ask</span>');
  if(a.zone) t.push('<span class="badge '+(/^(A|V)/.test(a.zone)?'zone-bad':'zone-ok')+
    '">'+esc(a.zone.split(' \\u2013 ')[0])+'</span>');
  if(a.unverified) t.push('<span class="badge wd-no">Unverified</span>');
  if(a.rating) t.push('<span class="badge tC">'+a.rating.toFixed(1)+'\\u2605 ('+(a.reviews||0)+')</span>');
  if(a.lease&&a.lease.length) t.push('<span class="badge tC">'+a.lease.join('/')+' mo</span>');
  (a.perks||[]).forEach(p=>t.push('<span class="badge perk">'+esc(p.replace(/_/g,' '))+'</span>'));
  return t.join('');
}
function render(){
  const q=(qEl.value||'').toLowerCase().trim();
  let v=ROWS.filter(a=>tiers.has(a.tier));
  if(q) v=v.filter(a=>(a.name+' '+a.address+' '+a.city).toLowerCase().includes(q));
  if(sortKey!=='tier'){
    v=v.slice().sort((x,y)=>{
      const a=x[sortKey==='price'?'priceN':sortKey], b=y[sortKey==='price'?'priceN':sortKey];
      if(a==null) return 1; if(b==null) return -1;
      return (typeof a==='number'? a-b : String(a).localeCompare(String(b)))*dir;
    });
  }
  document.getElementById('count').textContent=v.length+' of '+ROWS.length+' showing';
  tb.innerHTML=v.map(a=>{
    const digits=(a.phone||'').replace(/[^0-9]/g,'');
    return '<tr><td class="sm">'+a.num+'</td>'
      +'<td><div class="nm">'+(a.url?'<a href="'+esc(a.url)+'" target="_blank">'+esc(a.name)+'</a>':esc(a.name))+'</div>'
      +'<div class="sm">'+esc(a.address)+'</div>'
      +(a.specials?'<div class="deal-txt">\\u{1F4B0} '+esc(a.specials)+'</div>':'')
      +(a.why?'<div class="sm" style="margin-top:3px">'+esc(a.why)+'</div>':'')+'</td>'
      +'<td><b>'+esc(a.price)+'</b><div class="sm">'+esc(a.beds)+'</div></td>'
      +'<td>'+(a.sqft?a.sqft+'<div class="sm">sq ft</div>':'<span class="sm">n/a</span>')+'</td>'
      +'<td>'+(a.ppsf?'$'+a.ppsf:'<span class="sm">&mdash;</span>')+'</td>'
      +'<td>'+(a.miles!=null?a.miles:'<span class="sm">&mdash;</span>')+'</td>'
      +'<td><div class="tagcell">'+tags(a)+'</div></td>'
      +'<td class="sm">'+esc(a.status)+'</td>'
      +'<td><div class="acts">'
      +(digits?'<a class="btn call" href="tel:'+digits+'">\\u260E</a>':'')
      +(a.url?'<a class="btn" href="'+esc(a.url)+'" target="_blank">Listing</a>':'')
      +'<a class="btn grey" href="'+esc(a.maps)+'" target="_blank">Map</a>'
      +'<a class="btn ghost" href="'+esc(a.reviewsUrl)+'" target="_blank">Reviews</a>'
      +'</div>'+(a.phone?'<div class="sm">'+esc(a.phone)+'</div>':'')+'</td></tr>';
  }).join('');
}
document.querySelectorAll('th[data-s]').forEach(th=>th.addEventListener('click',()=>{
  const k=th.dataset.s; dir=(sortKey===k)?-dir:1; sortKey=k; render();}));
document.querySelectorAll('.chip').forEach(c=>c.addEventListener('click',()=>{
  const t=c.dataset.t;
  if(tiers.has(t)){tiers.delete(t);c.classList.remove('on');}
  else{tiers.add(t);c.classList.add('on');}
  render();}));
qEl.addEventListener('input',render);
render();
</script></body></html>"""


def esc_py(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ------------------------------------------------------------------------ ranked list
def build_ranked():
    """A straight 1..N ranked browse page — what Michael asked to have pulled up.

    The map answers "where", the tracker answers "compare everything". Neither answers
    "just tell me what to look at first", which is what this is. Ranked hardest-criteria
    first, then value; every card carries a direct link to the listing.
    """
    js = "const ROWS = " + json.dumps(ROWS, ensure_ascii=False) + ";"
    today = datetime.date.today().isoformat()
    new_today = sum(1 for r in ROWS if r.get("added") == today)
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Cache-Control" content="no-store">
<title>Ranked Apartment List</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>""" + CSS + """
.wrap{padding:20px 26px 60px}
h1{margin:0 0 3px;font-size:22px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px;margin-bottom:14px}
.sub a{font-weight:700}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:16px;
  position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:5;border-bottom:1px solid var(--line)}
.tools input[type=search]{padding:8px 11px;border:1px solid var(--line);border-radius:6px;
  font-size:13px;min-width:250px}
.chip{border:1px solid var(--line);background:#fff;border-radius:20px;padding:5px 12px;
  font-size:12px;font-weight:700;cursor:pointer;color:var(--muted)}
.chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.chip.on.cA{background:var(--a);border-color:var(--a)}
.chip.on.cB{background:var(--b);border-color:var(--b)}
.chip.on.cC{background:var(--c);border-color:var(--c)}
.chip.on.cL{background:var(--l);border-color:var(--l)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(430px,1fr));gap:14px}
.item{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;
  display:flex;gap:14px;box-shadow:0 1px 3px rgba(20,30,50,.05)}
.rank{flex:0 0 42px;height:42px;border-radius:10px;background:var(--ink);color:#fff;
  font:800 17px/42px -apple-system,Arial;text-align:center}
.item.a1 .rank{background:var(--a)} .item.a2 .rank{background:var(--b)}
.item.a4 .rank{background:var(--l)} .item.a3 .rank{background:var(--c)}
.body{flex:1 1 auto;min-width:0}
.hd{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.ttl{font-weight:700;font-size:15px;line-height:1.3}
.rent{font-weight:800;font-size:17px;white-space:nowrap}
.spec{color:var(--muted);font-size:12.5px;margin-top:3px}
.addr{color:var(--muted);font-size:12.5px;margin-top:2px}
.tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}
.deal-txt{font-size:12px;color:#8a5a00;background:#fdf7ea;border-left:3px solid #e8c26a;
  padding:6px 9px;border-radius:0 5px 5px 0;margin-top:8px}
.why{font-size:11.5px;color:var(--muted);margin-top:6px}
.acts{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
.new{background:#e2f0ff;color:#0d5aa7}
.count{color:var(--muted);font-size:12.5px}
@media print{@page{size:portrait;margin:11mm} .tools{display:none} .grid{
  grid-template-columns:1fr 1fr;gap:8px} .item{break-inside:avoid} .acts{display:none}}
</style></head><body><div class="wrap">
<h1>Ranked shortlist &mdash; St. Pete / Pinellas</h1>
<div class="sub">""" + ("%d properties · %d added today · %s · " % (len(ROWS), new_today, STAMP)) + """
<a href="index.html">Flood map</a> &middot; <a href="tracker.html">Full tracker</a></div>
<div class="tools">
  <input type="search" id="q" placeholder="Search address, name, city&hellip;">
  <span class="chip cA on" data-t="A">Meets everything</span>
  <span class="chip cB on" data-t="B">One call away</span>
  <span class="chip cL on" data-t="L">Zillow leads</span>
  <span class="chip cC" data-t="C">Ruled out</span>
  <span class="chip" id="newonly">Added today only</span>
  <span class="count" id="count"></span>
</div>
<div class="grid" id="grid"></div>
</div>
<script>
""" + js + """
const TODAY = """ + json.dumps(today) + """;
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function score(a){
  let s={A:1000,B:600,L:300,C:0}[a.tier]||0;
  if(a.sqft) s+=(a.sqft-700)/100;
  s+=(1600-a.priceN)/100;
  if(a.specials) s+=2;
  if(a.rating){const r=a.ratingScale===10?a.rating/2:a.rating; if(r>=4) s+=2;}
  if(a.miles!=null) s-=Math.max(0,a.miles-5)*0.6;
  if(/^(A|V)/.test(a.zone||'')) s-=4;
  (a.perks||[]).forEach(p=>{if(p==='top_floor')s+=2;if(p==='updated')s+=1.5;
    if(p==='high_ceilings')s+=1.5;if(p==='ground_floor')s-=1.5;});
  return s;
}
let tiers=new Set(['A','B','L']), newOnly=false;
const grid=document.getElementById('grid'), qEl=document.getElementById('q');
function render(){
  const q=(qEl.value||'').toLowerCase().trim();
  let v=ROWS.filter(a=>tiers.has(a.tier));
  if(newOnly) v=v.filter(a=>a.added===TODAY);
  if(q) v=v.filter(a=>(a.name+' '+a.address+' '+a.city).toLowerCase().includes(q));
  v.sort((x,y)=>score(y)-score(x));
  document.getElementById('count').textContent=v.length+' of '+ROWS.length+' showing';
  grid.innerHTML=v.map((a,i)=>{
    const cls={A:'a1',B:'a2',C:'a3',L:'a4'}[a.tier]||'a2';
    const t=[];
    t.push('<span class="badge t'+a.tier+'">'+({A:'Meets everything',B:'One call away',
      C:'Ruled out',L:'Zillow lead'}[a.tier])+'</span>');
    if(a.added===TODAY) t.push('<span class="badge new">NEW today</span>');
    if(a.laundry==='yes') t.push('<span class="badge wd-yes">In-unit W/D</span>');
    else if(a.laundry==='no') t.push('<span class="badge wd-no">No W/D</span>');
    else t.push('<span class="badge wd-unclear">W/D — ask</span>');
    if(a.zone) t.push('<span class="badge '+(/^(A|V)/.test(a.zone)?'zone-bad':'zone-ok')+
      '">FEMA '+esc(a.zone.split(' \\u2013 ')[0])+'</span>');
    if(a.rating) t.push('<span class="badge tC">'+a.rating+'/'+(a.ratingScale||5)+'\\u2605</span>');
    if(a.lease&&a.lease.length) t.push('<span class="badge tC">'+a.lease.join('/')+' mo</span>');
    if(a.unverified) t.push('<span class="badge wd-no">Unverified</span>');
    (a.perks||[]).forEach(p=>t.push('<span class="badge perk">'+esc(p.replace(/_/g,' '))+'</span>'));
    if(a.source) t.push('<span class="badge tC">'+esc(a.source)+'</span>');
    const spec=[a.beds,(a.sqft?a.sqft.toLocaleString()+' sq ft':'size not published'),
      (a.ppsf?'$'+a.ppsf+'/sq ft':null),(a.miles!=null?a.miles+' mi from downtown':null),
      (a.homeType||null),(a.days!=null?'listed '+a.days+'d ago':null)].filter(Boolean).join(' \\u00b7 ');
    const digits=(a.phone||'').replace(/[^0-9]/g,'');
    return '<div class="item '+cls+'"><div class="rank">'+(i+1)+'</div><div class="body">'
      +'<div class="hd"><div class="ttl">'+esc(a.name)+'</div><div class="rent">'+esc(a.price)+'</div></div>'
      +'<div class="spec">'+esc(spec)+'</div>'
      +'<div class="addr">'+esc(a.address)+'</div>'
      +(a.alsoKnownAs?'<div class="addr">formerly '+esc(a.alsoKnownAs)+'</div>':'')
      +'<div class="tags">'+t.join('')+'</div>'
      +(a.specials?'<div class="deal-txt">\\u{1F4B0} '+esc(a.specials)+'</div>':'')
      +(a.sqftNote?'<div class="why">\\u26A0 '+esc(a.sqftNote)+'</div>':'')
      +(a.why?'<div class="why">'+esc(a.why)+'</div>':'')
      +'<div class="acts">'
      +(a.url?'<a class="btn" href="'+esc(a.url)+'" target="_blank">View the listing \\u2192</a>':'')
      +(digits?'<a class="btn call" href="tel:'+digits+'">\\u260E '+esc(a.phone)+'</a>':'')
      +'<a class="btn grey" href="'+esc(a.maps)+'" target="_blank">Maps</a>'
      +'<a class="btn ghost" href="'+esc(a.reviewsUrl)+'" target="_blank">Reviews</a>'
      +'</div></div></div>';
  }).join('') || '<div class="count">Nothing matches that filter.</div>';
}
document.querySelectorAll('.chip[data-t]').forEach(c=>c.addEventListener('click',()=>{
  const t=c.dataset.t;
  if(tiers.has(t)){tiers.delete(t);c.classList.remove('on');}
  else{tiers.add(t);c.classList.add('on');}
  render();}));
document.getElementById('newonly').addEventListener('click',function(){
  newOnly=!newOnly; this.classList.toggle('on'); render();});
qEl.addEventListener('input',render);
render();
</script></body></html>"""


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def build_pdf(src, out_name):
    """Print one of the generated pages to a PDF next to it.

    Michael's standing instruction is that every change lands in the master HTML *and* the
    PDF. Generating them here rather than by hand is the only way a PDF can't quietly go
    stale while the HTML moves on -- which is exactly how the Jul 26 PDF ended up carrying
    numbers the code had already corrected.
    """
    import subprocess
    if not pathlib.Path(CHROME).exists():
        print("  -- no Chrome found, PDF skipped")
        return False
    out = HERE / out_name
    try:
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-sandbox",
                        "--virtual-time-budget=12000", "--no-pdf-header-footer",
                        "--print-to-pdf=%s" % out, (HERE / src).as_uri()],
                       check=True, capture_output=True, timeout=180)
        return out.exists() and out.stat().st_size > 20000
    except Exception as e:
        print("  -- PDF failed for %s: %s" % (src, str(e)[:80]))
        return False


DESKTOP_MASTERS = [
    # Mirrors the job search exactly: ~/Desktop/Master Job Tracker.html is a symlink to its
    # engine, with the project folder beside it. Same shape here so the two projects behave
    # identically -- Michael's words: "2 seperate projects but very very similar".
    ("index.html", "../Master Apartment Tracker.html"),
    ("ranked.html", "1 — TOP PICKS (start here).html"),
    ("tracker.html", "2 — Full Tracker.html"),
    ("index.html", "3 — Flood Map + Side List.html"),
    ("Top-Picks-Ranked.pdf", "Top Picks.pdf"),
    ("Apartment-Tracker.pdf", "Apartment Tracker.pdf"),
    # The plain names get linked as well. Leaving them as ordinary copies would strand a
    # stale duplicate beside every live link -- the 8 AM job can't refresh a copy on the
    # Desktop, so the two would drift apart and there'd be no way to tell which is which.
    ("ranked.html", "ranked.html"),
    ("tracker.html", "tracker.html"),
    ("index.html", "index.html"),
    ("Apartment-Tracker.pdf", "Apartment-Tracker.pdf"),
    ("Top-Picks-Ranked.pdf", "Top-Picks-Ranked.pdf"),
    ("apartments.json", "apartments.json"),
]


def link_desktop():
    """Put SYMLINKS on the Desktop pointing at the engine's live files.

    This is the fix for "it's never updated". The 8 AM launchd job cannot write to ~/Desktop
    or ~/Documents -- macOS TCC blocks it, and it had failed silently 20 times. Copies there
    only refreshed when Michael happened to open a launcher first, so the Desktop was showing
    whatever the last manual sync left behind.

    A symlink has no copy step to fail: the job rewrites the engine file, and the Desktop
    entry resolves to the new bytes immediately. Double-clicking opens the current version,
    every time, with no server and nothing to remember.
    """
    made = 0
    # Documents gets the same treatment as the Desktop: launchd can't write there either,
    # so a copy would sit there going quietly stale exactly the same way.
    for base in (pathlib.Path.home() / "Desktop" / "Apartment Search 2026",
                 pathlib.Path.home() / "Documents" / "Pinellas Apartment Map"):
        try:
            base.mkdir(parents=True, exist_ok=True)
            for src, nice in DESKTOP_MASTERS:
                target = HERE / src
                link = pathlib.Path(os.path.normpath(str(base / nice)))
                if not target.exists():
                    continue
                if link.is_symlink() or link.exists():
                    if link.is_symlink() and link.resolve() == target.resolve():
                        continue
                    link.unlink()
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(target)
                made += 1
        except Exception as e:
            print("  -- links in %s: %s" % (base.name, str(e)[:60]))
    return made


def main():
    (HERE / "index.html").write_text(build_map())
    (HERE / "tracker.html").write_text(build_tracker())
    (HERE / "ranked.html").write_text(build_ranked())
    print("Built %d properties (%s) in %s"
          % (len(ROWS), " ".join("%s:%d" % (t, sum(1 for r in ROWS if r["tier"] == t))
                                 for t in "ABLC"), HERE))
    files = ["index.html", "tracker.html", "ranked.html", "apartments.json"]
    for src, out in (("tracker.html", "Apartment-Tracker.pdf"),
                     ("ranked.html", "Top-Picks-Ranked.pdf")):
        if build_pdf(src, out):
            files.append(out)
            print("  PDF: %s" % out)
    for dest in PUBLISH:
        try:
            dest.mkdir(parents=True, exist_ok=True)
            for f in files:
                dst = dest / f
                # A symlink here already points at the engine copy, so it is live by
                # construction and there is nothing to publish. Copying onto it would write
                # THROUGH the link and clobber the very file it points at.
                if dst.is_symlink():
                    continue
                shutil.copy2(HERE / f, dst)
            print("  published -> %s" % dest)
        except Exception as e:
            # launchd background jobs can't write ~/Documents or ~/Desktop (macOS TCC) --
            # it silently failed 20 times before this was noticed. The symlinks above are
            # what actually keeps the Desktop current; this copy is a bonus when it works.
            print("  -- skipped %s (%s)" % (dest, str(e)[:60]))
    n = link_desktop()
    if n:
        print("  desktop links refreshed (%d)" % n)


if __name__ == "__main__":
    main()
