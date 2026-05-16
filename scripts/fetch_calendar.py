"""
fetch_calendar.py  (v2)
========================
Scrapes the World Athletics GraphQL API to produce meets.json.

HOW TO FIND THE CURRENT API CREDENTIALS:
  1. Open https://worldathletics.org/competition/calendar-results in Chrome
  2. Press F12 → Network tab → filter "Fetch/XHR"
  3. Refresh the page — look for a request to an AWS AppSync URL
     (*.appsync-api.*.amazonaws.com/graphql)
  4. Click that request → Headers tab
  5. Copy the full Request URL → paste as WA_API_ENDPOINT secret in GitHub
  6. Copy the x-api-key value → paste as WA_API_KEY secret in GitHub

When the scraper starts returning 0 meets, repeat steps 1–6.
"""

import json
import time
import datetime
import os
import sys
from typing import Optional

import requests


# ── CONFIG ────────────────────────────────────────────────────────────────────
API_ENDPOINT = os.getenv("WA_API_ENDPOINT", "https://PASTE_ENDPOINT_HERE.appsync-api.eu-west-1.amazonaws.com/graphql")
API_KEY      = os.getenv("WA_API_KEY",      "PASTE_API_KEY_HERE")

MONTHS_AHEAD    = 18        # how far ahead to fetch
DAYS_PAST       = 14        # include recently finished meets for context
REQUEST_DELAY   = 0.5       # seconds between detail requests
MAX_RETRIES     = 3         # retries per failed request
MIN_MEETS_VALID = 20        # if we get fewer than this, assume API key rotated

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "meets.json")
# ── END CONFIG ────────────────────────────────────────────────────────────────


# ── DISCIPLINE MAP ────────────────────────────────────────────────────────────
# World Athletics discipline name → short ID used by the filter tool.
# Extend this list when the scraper logs "Unknown discipline: …"
DISCIPLINE_MAP = {
    # Track — sprints
    "60 Metres":                    "60m",
    "100 Metres":                   "100m",
    "200 Metres":                   "200m",
    "400 Metres":                   "400m",
    # Track — middle distance
    "800 Metres":                   "800m",
    "1500 Metres":                  "1500m",
    "One Mile":                     "mile",
    "1 Mile":                       "mile",
    "1 mile":                       "mile",
    # Track — long distance
    "3000 Metres":                  "3000m",
    "5000 Metres":                  "5000m",
    "10,000 Metres":                "10000m",
    "10000 Metres":                 "10000m",
    "10 000 Metres":                "10000m",
    # Track — hurdles / barriers
    "60 Metres Hurdles":            "60mh",
    "100 Metres Hurdles":           "100mh",
    "110 Metres Hurdles":           "110mh",
    "400 Metres Hurdles":           "400mh",
    "3000 Metres Steeplechase":     "3000sc",
    "2000 Metres Steeplechase":     "2000sc",
    # Road
    "Marathon":                     "mar",
    "Half Marathon":                "hmar",
    "10 Kilometres":                "10km",
    "10km":                         "10km",
    "5 Kilometres":                 "5km",
    # Race walk
    "20 Kilometres Race Walk":      "20krw",
    "20km Race Walk":               "20krw",
    "35 Kilometres Race Walk":      "35krw",
    "35km Race Walk":               "35krw",
    "50 Kilometres Race Walk":      "50krw",
    # Field — jumps
    "High Jump":                    "hj",
    "Pole Vault":                   "pv",
    "Long Jump":                    "lj",
    "Triple Jump":                  "tj",
    # Field — throws
    "Shot Put":                     "sp",
    "Discus Throw":                 "dt",
    "Hammer Throw":                 "ht",
    "Javelin Throw":                "jt",
    "Weight Throw":                 "wt",
    # Relays
    "4x100 Metres Relay":           "4x100",
    "4 x 100 Metres Relay":         "4x100",
    "4x400 Metres Relay":           "4x400",
    "4 x 400 Metres Relay":         "4x400",
    "4x200 Metres Relay":           "4x200",
    "4 x 200 Metres Relay":         "4x200",
    "4x800 Metres Relay":           "4x800",
    "4x1500 Metres Relay":          "4x1500",
    "Sprint Medley Relay":          "smr",
    "Distance Medley Relay":        "dmr",
    # Combined events
    "Decathlon":                    "dec",
    "Heptathlon":                   "hep",
    "Pentathlon":                   "pen",
    "Triathlon":                    "tri",
    # U20 variants (WA uses same names — handled by gender/age-group tagging)
    "100 Metres U20":               "100m",
    "200 Metres U20":               "200m",
    "400 Metres U20":               "400m",
    "800 Metres U20":               "800m",
    "1500 Metres U20":              "1500m",
    "5000 Metres U20":              "5000m",
    "110 Metres Hurdles U20":       "110mh",
    "100 Metres Hurdles U20":       "100mh",
    "400 Metres Hurdles U20":       "400mh",
    "2000 Metres Steeplechase U20": "2000sc",
    "3000 Metres Steeplechase U20": "3000sc",
    "High Jump U20":                "hj",
    "Pole Vault U20":               "pv",
    "Long Jump U20":                "lj",
    "Triple Jump U20":              "tj",
    "Shot Put U20":                 "sp",
    "Discus Throw U20":             "dt",
    "Hammer Throw U20":             "ht",
    "Javelin Throw U20":            "jt",
    "Decathlon U20":                "dec",
    "Heptathlon U20":               "hep",
    "Octathlon":                    "oct",
}
# ── END DISCIPLINE MAP ────────────────────────────────────────────────────────


# ── CATEGORY MAP ──────────────────────────────────────────────────────────────
CATEGORY_MAP = {
    "Diamond League":                              "DL",
    "World Athletics Diamond League":              "DL",
    "Continental Tour Gold":                       "CTG",
    "World Athletics Continental Tour Gold":       "CTG",
    "Continental Tour Silver":                     "CTS",
    "World Athletics Continental Tour Silver":     "CTS",
    "Continental Tour Bronze":                     "CTB",
    "World Athletics Continental Tour Bronze":     "CTB",
    "Indoor Tour Gold":                            "ITG",
    "World Athletics Indoor Tour Gold":            "ITG",
    "Indoor Tour Silver":                          "ITS",
    "World Athletics Indoor Tour Silver":          "ITS",
    "Indoor Tour Bronze":                          "ITB",
    "World Athletics Indoor Tour Bronze":          "ITB",
    "World Athletics Championships":               "WCH",
    "World Indoor Championships":                  "WCH",
    "Olympic Games":                               "OLY",
    "Area Championships":                          "AREA",
    "World Cross Country Championships":           "WCH",
    "National Championships":                      "NAT",
}
# ── END CATEGORY MAP ─────────────────────────────────────────────────────────


# ── REGION MAP ────────────────────────────────────────────────────────────────
# Maps IOC 3-letter country codes to a continent/region label.
COUNTRY_REGION = {
    # Europe
    "GBR":"EUR","FRA":"EUR","GER":"EUR","ITA":"EUR","SWE":"EUR","NOR":"EUR",
    "FIN":"EUR","NED":"EUR","BEL":"EUR","SUI":"EUR","CZE":"EUR","POL":"EUR",
    "GRE":"EUR","ESP":"EUR","POR":"EUR","TUR":"EUR","UKR":"EUR","HUN":"EUR",
    "AUT":"EUR","DEN":"EUR","SVK":"EUR","SLO":"EUR","CRO":"EUR","SRB":"EUR",
    "ROM":"EUR","BUL":"EUR","LAT":"EUR","EST":"EUR","LTU":"EUR","BLR":"EUR",
    "MON":"EUR","ISR":"EUR","IRL":"EUR","CYP":"EUR","MDA":"EUR","ALB":"EUR",
    "MKD":"EUR","BIH":"EUR","MNE":"EUR","GEO":"EUR","ARM":"EUR","AZE":"EUR",
    "RUS":"EUR","SCO":"EUR","WAL":"EUR","MLT":"EUR","LUX":"EUR","LIE":"EUR",
    # Americas
    "USA":"AME","CAN":"AME","JAM":"AME","BAH":"AME","BRA":"AME","ARG":"AME",
    "MEX":"AME","CUB":"AME","TTO":"AME","COL":"AME","CHI":"AME","VEN":"AME",
    "ECU":"AME","PER":"AME","URU":"AME","BOL":"AME","PAN":"AME","DOM":"AME",
    "BAR":"AME","GRN":"AME","SKN":"AME","ANT":"AME","CAY":"AME","PUR":"AME",
    # Asia / Middle East
    "QAT":"ASI","UAE":"ASI","CHN":"ASI","JPN":"ASI","KOR":"ASI","IND":"ASI",
    "KAZ":"ASI","BRN":"ASI","IRI":"ASI","TPE":"ASI","THA":"ASI","MAS":"ASI",
    "SGP":"ASI","PHI":"ASI","SRI":"ASI","PAK":"ASI","UZB":"ASI","KGZ":"ASI",
    "TJK":"ASI","TKM":"ASI","BHR":"ASI","KUW":"ASI","OMA":"ASI","KSA":"ASI",
    # Africa
    "KEN":"AFR","ETH":"AFR","MAR":"AFR","RSA":"AFR","NGR":"AFR","ALG":"AFR",
    "TUN":"AFR","EGY":"AFR","UGA":"AFR","TAN":"AFR","BUR":"AFR","CIV":"AFR",
    "GHA":"AFR","SEN":"AFR","CMR":"AFR","ZIM":"AFR","BOT":"AFR","NAM":"AFR",
    # Oceania
    "AUS":"OCE","NZL":"OCE","PNG":"OCE","SAM":"OCE","FIJ":"OCE",
}
# ── END REGION MAP ────────────────────────────────────────────────────────────


# ── INDOOR MONTHS ─────────────────────────────────────────────────────────────
# Meets in these calendar months are classified as indoor season.
INDOOR_MONTHS = {1, 2, 3, 11, 12}
# ── END ───────────────────────────────────────────────────────────────────────


# ── GRAPHQL QUERIES ───────────────────────────────────────────────────────────
CALENDAR_QUERY = """
query GetCalendarEvents(
  $startDate: String!
  $endDate:   String!
  $offset:    Int!
  $limit:     Int!
) {
  getCalendarEvents(
    startDate: $startDate
    endDate:   $endDate
    offset:    $offset
    limit:     $limit
  ) {
    results {
      id
      name
      venue
      startDate
      endDate
      country  { name code }
      competitionType { name code }
      hasResults
    }
    total
  }
}
"""

DETAIL_QUERY = """
query GetCompetitionDetail($id: Int!) {
  getCalendarEventCompetitionDetail(id: $id) {
    website
    disciplines {
      name
      gender
    }
    contacts {
      name
      email
      phone
    }
  }
}
"""
# ── END QUERIES ───────────────────────────────────────────────────────────────


def wa_request(query: str, variables: dict, retries: int = MAX_RETRIES) -> dict:
    """POST a GraphQL query to the WA API with exponential-backoff retry."""
    headers = {
        "Content-Type":   "application/json",
        "x-api-key":      API_KEY,
        "Referer":        "https://worldathletics.org/",
        "Origin":         "https://worldathletics.org",
        "User-Agent":     "Mozilla/5.0 (compatible; Athletics-Hub/2.0)",
    }
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                API_ENDPOINT,
                headers=headers,
                json={"query": query, "variables": variables},
                timeout=20,
            )
            resp.raise_for_status()
            body = resp.json()
            if "errors" in body:
                print(f"    GraphQL errors: {body['errors']}")
            return body.get("data", {})
        except requests.RequestException as exc:
            wait = 2 ** attempt
            if attempt < retries:
                print(f"    Request failed (attempt {attempt}/{retries}): {exc} — retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"    Request failed after {retries} attempts: {exc}")
    return {}


def map_discipline(raw_name: str) -> Optional[str]:
    """Convert a WA discipline string to our short ID. Returns None if unknown."""
    clean = raw_name.strip()
    if clean in DISCIPLINE_MAP:
        return DISCIPLINE_MAP[clean]
    # Case-insensitive exact match
    for key, val in DISCIPLINE_MAP.items():
        if key.lower() == clean.lower():
            return val
    # Partial match fallback
    for key, val in DISCIPLINE_MAP.items():
        if key.lower() in clean.lower():
            return val
    return None


def map_category(raw_name: str) -> str:
    """Convert a WA competition type string to our short category code."""
    for key, val in CATEGORY_MAP.items():
        if key.lower() in raw_name.lower():
            return val
    # Check if name itself contains keywords
    name_lower = raw_name.lower()
    if "national" in name_lower:
        return "NAT"
    if "area" in name_lower or "continental" in name_lower:
        return "AREA"
    return "OTHER"


def is_indoor_meet(name: str, date_str: str) -> bool:
    """Return True if this meet is almost certainly an indoor competition."""
    if any(word in name.lower() for word in ("indoor", "hall", "halle", "salle")):
        return True
    try:
        month = int(date_str[5:7])
        return month in INDOOR_MONTHS
    except (ValueError, IndexError):
        return False


def fetch_calendar(start: str, end: str) -> list:
    """Fetch all meets in the date range, handling pagination."""
    all_results = []
    limit, offset = 100, 0
    while True:
        print(f"    Fetching calendar (offset={offset})…")
        data = wa_request(CALENDAR_QUERY, {
            "startDate": start, "endDate": end,
            "offset": offset, "limit": limit,
        })
        page    = data.get("getCalendarEvents") or {}
        results = page.get("results") or []
        total   = page.get("total") or 0
        all_results.extend(results)
        offset += limit
        if offset >= total or not results:
            break
        time.sleep(REQUEST_DELAY)
    print(f"    Found {len(all_results)} meets in this window")
    return all_results


def fetch_detail(meet_id) -> dict:
    """Fetch gender-specific events, website, and contact for one meet."""
    data = wa_request(DETAIL_QUERY, {"id": int(meet_id)})
    return (data.get("getCalendarEventCompetitionDetail") or {})


def parse_detail(detail: dict) -> dict:
    out = {"website": "", "contact": {}, "events": {"men": [], "women": []}}
    if not detail:
        return out

    out["website"] = (detail.get("website") or "").strip()

    contacts = detail.get("contacts") or []
    if contacts:
        c = contacts[0]
        out["contact"] = {
            "name":  (c.get("name")  or "").strip(),
            "email": (c.get("email") or "").strip(),
            "phone": (c.get("phone") or "").strip(),
        }

    unknown = []
    for d in (detail.get("disciplines") or []):
        raw_name = (d.get("name") or "").strip()
        gender   = (d.get("gender") or "").upper()
        mapped   = map_discipline(raw_name)
        if not mapped:
            if raw_name:
                unknown.append(raw_name)
            continue
        if gender == "M":
            if mapped not in out["events"]["men"]:
                out["events"]["men"].append(mapped)
        elif gender == "W":
            if mapped not in out["events"]["women"]:
                out["events"]["women"].append(mapped)
        else:
            # No gender tag — add to both
            for lst in (out["events"]["men"], out["events"]["women"]):
                if mapped not in lst:
                    lst.append(mapped)

    if unknown:
        print(f"      Unknown disciplines (add to DISCIPLINE_MAP): {unknown}")

    return out


def build_meet_record(raw: dict, detail: dict) -> dict:
    country   = raw.get("country") or {}
    comp_type = raw.get("competitionType") or {}
    cat_raw   = comp_type.get("name") or "Other"
    code      = country.get("code") or ""
    start     = (raw.get("startDate") or "")[:10]
    end       = (raw.get("endDate")   or "")[:10]

    return {
        "id":          str(raw.get("id") or ""),
        "name":        (raw.get("name") or "").strip(),
        "dateStart":   start,
        "dateEnd":     end if end and end != start else start,
        "city":        (raw.get("venue") or "").strip(),
        "countryCode": code,
        "countryName": country.get("name") or "",
        "region":      COUNTRY_REGION.get(code, "OTHER"),
        "category":    map_category(cat_raw),
        "categoryRaw": cat_raw,
        "isIndoor":    is_indoor_meet(raw.get("name") or "", start),
        "website":     detail.get("website") or "",
        "contact":     detail.get("contact") or {},
        "events":      detail.get("events") or {"men": [], "women": []},
        "hasResults":  bool(raw.get("hasResults")),
    }


def load_existing() -> dict:
    """Load the current meets.json if it exists, for safe rollback."""
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    today = datetime.date.today()
    end   = today + datetime.timedelta(days=MONTHS_AHEAD * 30)
    past  = today - datetime.timedelta(days=DAYS_PAST)

    print(f"\nAthletics Hub — fetch_calendar.py v2")
    print(f"Range: {past} → {end}  |  Endpoint: {API_ENDPOINT[:55]}…\n")

    existing = load_existing()

    # Fetch
    raw_all = fetch_calendar(str(past), str(end))

    # Safety check — if we got almost nothing, the API key has likely rotated.
    if len(raw_all) < MIN_MEETS_VALID:
        print(f"\nERROR: Only {len(raw_all)} meets returned (expected ≥{MIN_MEETS_VALID}).")
        print("This almost certainly means the API key has rotated.")
        print("Update WA_API_KEY in your GitHub Secrets and re-run.\n")
        if existing:
            print("Keeping the existing meets.json unchanged.")
        sys.exit(1)

    # Fetch detail for each meet
    meets = []
    total = len(raw_all)
    for i, raw in enumerate(raw_all, 1):
        meet_id = raw.get("id")
        name    = raw.get("name") or "?"
        print(f"  [{i:>3}/{total}] {name}")
        try:
            detail = parse_detail(fetch_detail(meet_id))
        except Exception as exc:
            print(f"    Warning: detail fetch failed for {name}: {exc}")
            detail = {"website": "", "contact": {}, "events": {"men": [], "women": []}}
        meets.append(build_meet_record(raw, detail))
        time.sleep(REQUEST_DELAY)

    # Write output
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    output = {
        "updated":  datetime.datetime.utcnow().isoformat() + "Z",
        "count":    len(meets),
        "meets":    meets,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nDone — {len(meets)} meets written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
