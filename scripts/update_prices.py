#!/usr/bin/env python3
"""
Daily AGMARKNET price updater for the Mandi Rates app.

Runs on GitHub Actions (see .github/workflows/update-prices.yml). It reads the
data.gov.in API key from the DATA_GOV_API_KEY secret, fetches new Karnataka
mandi prices for each crop and saves small JSON files the app reads:

  data/meta.json                          list of crops and mandis, plus each mandi's latest rate
  data/p/<crop-slug>/<market-slug>.json   daily rows: [date, variety, min, max, modal]
  state/progress.json                     how far each crop has been fetched (so runs are incremental)

The first run back-fills history (it can take a few hours; if it hits the time
limit it saves progress and the next run continues). Later runs only fetch new rows.
Uses only the Python standard library.
"""
import json, os, re, sys, time, statistics, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_BASE = os.environ.get("API_BASE", "https://api.data.gov.in/resource/")
RESOURCE = os.environ.get("RESOURCE", "35985678-0d79-46b4-9ed6-6f13308a1d24")  # Variety-wise Daily Market Prices
STATE = os.environ.get("STATE", "Karnataka")
KEY = os.environ.get("DATA_GOV_API_KEY", "").strip()
YEARS = int(os.environ.get("YEARS", "6"))             # keep this many years of history
PAGE = int(os.environ.get("PAGE", "1000"))            # records per request
MAX_BACKFILL = int(os.environ.get("MAX_BACKFILL", "400000"))  # per crop, on first run
TIME_LIMIT_MIN = float(os.environ.get("TIME_LIMIT_MIN", "300"))
ONLY = [s.strip() for s in os.environ.get("ONLY_CROPS", "").split(",") if s.strip()]

# AGMARKNET commodity names to try for each crop (first match with data wins), plus fallback keywords.
CROPS = [
    (["Onion"], ["onion"]),
    (["Dry Chillies"], ["dry chilli"]),
    (["Cotton"], ["cotton"]),
    (["Groundnut"], ["groundnut"]),
    (["Jowar(Sorghum)", "Jowar (Sorghum)"], ["jowar"]),
    (["Bengal Gram(Gram)(Whole)"], ["bengal gram"]),
    (["Arhar (Tur/Red Gram)(Whole)"], ["arhar", "tur"]),
    (["Green Gram (Moong)(Whole)"], ["green gram", "moong"]),
    (["Maize"], ["maize"]),
    (["Wheat"], ["wheat"]),
    (["Sunflower"], ["sunflower"]),
    (["Soyabean"], ["soya"]),
    (["Safflower"], ["safflower"]),
    (["Tomato"], ["tomato"]),
    (["Potato"], ["potato"]),
    (["Paddy(Dhan)(Common)"], ["paddy"]),
    (["Ragi (Finger Millet)"], ["ragi"]),
    (["Arecanut(Betelnut/Supari)"], ["arecanut"]),
    (["Copra"], ["copra"]),
    (["Turmeric"], ["turmeric"]),
]

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PROGRESS = ROOT / "state" / "progress.json"
T0 = time.time()


def log(*a):
    print(*a, flush=True)


def out_of_time():
    return (time.time() - T0) / 60 > TIME_LIMIT_MIN


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


def nk(k):
    return re.sub(r"\s+", "_", str(k).lower().replace("_x0020_", "_"))


def parse_date(s):
    s = str(s or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}"
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", s)
    if m:
        return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
    return None


def num(v):
    try:
        x = float(str(v).replace(",", ""))
        return round(x) if x > 0 else None
    except (TypeError, ValueError):
        return None


class Api:
    def __init__(self):
        self.fields = {}
        self.suffix = ""

    def get(self, limit=1, offset=0, filters=None):
        q = {"api-key": KEY, "format": "json", "limit": limit, "offset": offset}
        for k, v in (filters or {}).items():
            q[f"filters[{self.fields.get(k, k)}{self.suffix}]"] = v
        url = API_BASE + RESOURCE + "?" + urllib.parse.urlencode(q)
        delay = 3
        for attempt in range(7):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "mandi-rates-bot"}), timeout=90) as r:
                    j = json.loads(r.read().decode("utf-8"))
                if j.get("status") not in (None, "ok") and "records" not in j:
                    raise RuntimeError(j.get("message") or j.get("status"))
                return j
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    sys.exit(f"API key rejected (HTTP {e.code}). Check the DATA_GOV_API_KEY secret.")
                err = f"HTTP {e.code}"
            except Exception as e:  # network / JSON / server message
                err = repr(e)
            log(f"  retry {attempt + 1} after error: {err}")
            time.sleep(delay)
            delay = min(delay * 2, 120)
        raise RuntimeError("data.gov.in did not respond after several retries")

    def setup(self):
        j = self.get(limit=1)
        ids = [f["id"] for f in j.get("field", [])] or list((j.get("records") or [{}])[0].keys())
        self.fields = {nk(i): i for i in ids}
        log("Fields:", ", ".join(ids))
        total_all = int(j.get("total") or 0)
        for suf in ("", ".keyword"):
            self.suffix = suf
            f = self.get(limit=1, filters={"state": STATE})
            recs = f.get("records") or []
            st = norm(recs[0])["state"] if recs else ""
            if int(f.get("total") or 0) > 0 and int(f.get("total")) < total_all and str(st).lower() == STATE.lower():
                log(f"Filter style: filters[Field{suf}]  ({STATE}: {f['total']} records)")
                return
        sys.exit("Could not filter by state — the dataset's field names may have changed.")

    def total(self, filters):
        return int(self.get(limit=1, filters=filters).get("total") or 0)


def norm(r):
    o = {nk(k): v for k, v in r.items()}
    return {
        "state": o.get("state"), "district": o.get("district") or "", "market": o.get("market") or "",
        "commodity": o.get("commodity") or "", "variety": o.get("variety") or "-", "grade": o.get("grade") or "",
        "date": parse_date(o.get("arrival_date")),
        "min": num(o.get("min_price")), "max": num(o.get("max_price")), "modal": num(o.get("modal_price")),
    }


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text("utf-8"))
    except Exception:
        return default


def save_json(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), "utf-8")
    tmp.replace(p)


def flush(commodity, buf, cutoff):
    """Merge buffered rows {market: [rec,...]} into each market's file."""
    for market, recs in buf.items():
        p = DATA / "p" / slug(commodity) / (slug(market) + ".json")
        cur = load_json(p, {"commodity": commodity, "market": market, "district": "", "rows": []})
        rows = {(r[0], r[1], r[5] if len(r) > 5 else ""): r for r in cur["rows"]}
        for r in recs:
            rows[(r["date"], r["variety"], r["grade"])] = [r["date"], r["variety"], r["min"] or r["modal"], r["max"] or r["modal"], r["modal"], r["grade"]]
            cur["district"] = r["district"] or cur["district"]
        cur["rows"] = sorted((v for v in rows.values() if v[0] >= cutoff), key=lambda v: (v[0], v[1]))
        save_json(p, cur)
    buf.clear()


def resolve(api, names, kws, known):
    for n in names:
        if api.total({"state": STATE, "commodity": n}) > 0:
            return n
    for n in known:
        if any(k in n.lower() for k in kws):
            return n
    return None


def build_meta(names_by_slug):
    crops = {}
    for f in sorted((DATA / "p").glob("*/*.json")):
        d = load_json(f, None)
        if not d or not d.get("rows"):
            continue
        last = d["rows"][-1][0]
        modal = statistics.median([r[4] for r in d["rows"] if r[0] == last])
        c = crops.setdefault(d["commodity"], {"commodity": d["commodity"], "slug": f.parent.name, "markets": []})
        c["markets"].append({"market": d["market"], "district": d["district"], "file": f"p/{f.parent.name}/{f.name}",
                             "first": d["rows"][0][0], "last": last, "modal": modal, "rows": len(d["rows"])})
    meta = {"state": STATE, "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "source": "AGMARKNET via data.gov.in (resource " + RESOURCE + ")",
            "crops": sorted(crops.values(), key=lambda c: c["commodity"])}
    save_json(DATA / "meta.json", meta)
    log(f"meta.json: {len(meta['crops'])} crops, {sum(len(c['markets']) for c in meta['crops'])} crop-mandi files")


def main():
    if not KEY:
        sys.exit("DATA_GOV_API_KEY is not set. Add it under Settings → Secrets and variables → Actions.")
    api = Api()
    api.setup()
    progress = load_json(PROGRESS, {})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=365 * YEARS)).strftime("%Y-%m-%d")
    known = [c["commodity"] for c in load_json(DATA / "meta.json", {}).get("crops", [])]
    finished = True

    for names, kws in CROPS:
        if ONLY and not any(o.lower() in n.lower() for n in names for o in ONLY):
            continue
        if out_of_time():
            finished = False
            break
        name = resolve(api, names, kws, known)
        if not name:
            log(f"- {names[0]}: no Karnataka records found, skipped")
            continue
        flt = {"state": STATE, "commodity": name}
        total = api.total(flt)
        seen = int(progress.get(name, {}).get("seen", 0))
        if total < seen:                       # dataset was rebuilt — start again
            log(f"- {name}: total dropped {seen} → {total}, re-reading")
            seen = 0
        start = seen if seen else max(0, total - MAX_BACKFILL)
        log(f"- {name}: total {total}, fetching {total - start} new records")
        buf, pages, off, added = {}, 0, start, 0
        while off < total:
            j = api.get(limit=min(PAGE, total - off), offset=off, filters=flt)
            recs = j.get("records") or []
            if not recs:
                break
            for r in map(norm, recs):
                if r["date"] and r["modal"] and r["date"] >= cutoff and r["market"]:
                    buf.setdefault(r["market"], []).append(r)
                    added += 1
            off += len(recs)
            pages += 1
            if pages % 50 == 0 or out_of_time():
                flush(name, buf, cutoff)
                progress[name] = {"seen": off, "updated": datetime.now(timezone.utc).isoformat()}
                save_json(PROGRESS, progress)
                log(f"    {off}/{total}")
                if out_of_time():
                    finished = False
                    break
            time.sleep(0.2)
        flush(name, buf, cutoff)
        progress[name] = {"seen": off, "updated": datetime.now(timezone.utc).isoformat()}
        save_json(PROGRESS, progress)
        log(f"    saved {added} rows")
        if not finished:
            break

    build_meta(None)
    log("Done." if finished else "Stopped at the time limit — the next run continues from here.")


if __name__ == "__main__":
    main()