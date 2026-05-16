"""
fetch_calendar.py  (v3 — fixed for actual WA API schema)
=========================================================
Scrapes the World Athletics GraphQL API to produce meets.json.

HOW TO FIND THE CURRENT API CREDENTIALS:
  1. Open https://worldathletics.org/competition/calendar-results in Chrome
  2. Press F12 → Network tab → filter "Fetch/XHR"
  3. Refresh the page — look for requests named "graphql"
  4. Click one → Headers tab
  5. Copy the full Request URL → paste as WA_API_ENDPOINT secret in GitHub
  6. Scroll to Request Headers → copy x-api-key value → paste as WA_API_KEY secret

When the scraper starts returning 0 meets, repeat steps 1-6.
"""

import json
import time
import datetime
import os
import sys
from typing import Optional

import requests


# ── CONFIG ────────────────────────────────────────────────────────────────────
API_ENDPOINT = os.getenv("WA_API_ENDPOINT", "https://PASTE_ENDPOINT_HERE")
API_KEY      = os.getenv("WA_API_KEY",      "PASTE_API_KEY_HERE")

MONTHS_AHEAD    = 18
DAYS_PAST       = 14
REQUEST_DELAY   = 0.5
MAX_RETRIES     = 3
MIN_MEETS_VALID = 20

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "meets.json"
)
# ── END CONFIG ────────────────────────────────────────────────────────────────


# ── DISCIPLINE MAP ────────────────────────────────────────────────────────────
DISCIPLINE_MAP = {
    "60 Metres": "60m", "100 Metres": "100m", "200 Metres": "200m",
    "400 Metres": "400m", "800 Metres": "800m", "1500 Metres": "1500m",
    "One Mile": "mile", "1 Mile": "mile", "1 mile": "mile",
    "3000 Metres": "3000m", "5000 Metres": "5000m",
    "10,000 Metres": "10000m", "10000 Metres": "10000m", "10 000 Metres": "10000m",
    "60 Metres Hurdles": "60mh", "100 Metres Hurdles": "100mh",
    "110 Metres Hurdles": "110mh", "400 Metres Hurdles": "400mh",
    "3000 Metres Steeplechase": "3000sc", "2000 Metres Steeplechase": "2000sc",
    "Marathon": "mar", "Half Marathon": "hmar",
    "10 Kilometres": "10km", "10km": "10km", "5 Kilometres": "5km",
    "20 Kilometres Race Walk": "20krw", "20km Race Walk": "20krw",
    "35 Kilometres Race Walk": "35krw", "35km Race Walk": "35krw",
    "50 Kilometres Race Walk": "50krw",
    "High Jump": "hj", "Pole Vault": "pv", "Long Jump": "lj", "Triple Jump": "tj",
    "Shot Put": "sp", "Discus Throw": "dt", "Hammer Throw": "ht", "Javelin Throw": "jt",
    "Weight Throw": "wt",
    "4x100 Metres Relay": "4x100", "4 x 100 Metres Relay": "4x100",
    "4x400 Metres Relay": "4x400", "4 x 400 Metres Relay": "4x400",
    "4x200 Metres Relay": "4x200", "4 x 200 Metres Relay": "4x200",
    "4x800 Metres Relay": "4x800", "4x1500 Metres Relay": "4x1500",
    "Sprint Medley Relay": "smr", "Distance Medley Relay": "dmr",
    "Decathlon": "dec", "Heptathlon": "hep", "Pentathlon": "pen",
    "Triathlon": "tri", "Octathlon": "oct",
    "100 Metres U20": "100m", "200 Metres U20": "200m", "400 Metres U20": "400m",
    "800 Metres U20": "800m", "1500 Metres U20": "1500m", "5000 Metres U20": "5000m",
    "110 Metres Hurdles U20": "110mh", "100 Metres Hurdles U20": "100mh",
    "400 Metres Hurdles U20": "400mh",
    "2000 Metres Steeplechase U20": "2000sc", "3000 Metres Steeplechase U20": "3000sc",
    "High Jump U20": "hj", "Pole Vault U20": "pv",
    "Long Jump U20": "lj", "Triple Jump U20": "tj",
    "Shot Put U20": "sp", "Discus Throw U20": "dt",
    "Hammer Throw U20": "ht", "Javelin Throw U20": "jt",
    "Decathlon U20": "dec", "Heptathlon U20": "hep",
}
# ── END DISCIPLINE MAP ────────────────────────────────────────────────────────


# ── CATEGORY DETECTION FROM NAME ──────────────────────────────────────────────
# Since competitionType is not available in the API schema, we detect
# the category from the meet name and any available fields.
def detect_category(name: str) -> str:
    name_lower = name.lower()
    if "diamond league" in name_lower:
        return "DL"
    if "continental tour gold" in name_lower or "ct gold" in name_lower:
        return "CTG"
    if "continental tour silver" in name_lower or "ct silver" in name_lower:
        return "CTS"
    if "continental tour bronze" in name_lower or "ct bronze" in name_lower:
        return "CTB"
    if "indoor tour gold" in name_lower:
        return "ITG"
    if "indoor tour silver" in name_lower:
        return "ITS"
    if "world championship" in name_lower or "world indoor" in name_lower:
        return "WCH"
    if "olympic" in name_lower:
        return "OLY"
    if "national championship" in name_lower or "national champ" in name_lower:
        return "NAT"
    if "area championship" in name_lower or "european championship" in name_lower \
       or "african championship" in name_lower or "asian championship" in name_lower:
        return "AREA"
    return "OTHER"
# ── END CATEGORY DETECTION ────────────────────────────────────────────────────


# ── REGION MAP ────────────────────────────────────────────────────────────────
COUNTRY_REGION = {
    "GBR": "EUR", "FRA": "EUR", "GER": "EUR", "ITA": "EUR", "SWE": "EUR",
    "NOR": "EUR", "FIN": "EUR", "NED": "EUR", "BEL": "EUR", "SUI": "EUR",
    "CZE": "EUR", "POL": "EUR", "GRE": "EUR", "ESP": "EUR", "POR": "EUR",
    "TUR": "EUR", "UKR": "EUR", "HUN": "EUR", "AUT": "EUR", "DEN": "EUR",
    "SVK": "EUR", "SLO": "EUR", "CRO": "EUR", "SRB": "EUR", "ROM": "EUR",
    "BUL": "EUR", "LAT": "EUR", "EST": "EUR", "LTU": "EUR", "BLR": "EUR",
    "MON": "EUR", "ISR": "EUR", "IRL": "EUR", "CYP": "EUR", "MDA": "EUR",
    "ALB": "EUR", "MKD": "EUR", "BIH": "EUR", "MNE": "EUR", "GEO": "EUR",
    "ARM": "EUR", "AZE": "EUR", "RUS": "EUR", "SCO": "EUR", "WAL": "EUR",
    "MLT": "EUR", "LUX": "EUR", "LIE": "EUR",
    "USA": "AME", "CAN": "AME", "JAM": "AME", "BAH": "AME", "BRA": "AME",
    "ARG": "AME", "MEX": "AME", "CUB": "AME", "TTO": "AME", "COL": "AME",
    "CHI": "AME", "VEN": "AME", "ECU": "AME", "PER": "AME", "URU": "AME",
    "BOL": "AME", "PAN": "AME", "DOM": "AME", "BAR": "AME", "GRN": "AME",
    "QAT": "ASI", "UAE": "ASI", "CHN": "ASI", "JPN": "ASI", "KOR": "ASI",
    "IND": "ASI", "KAZ": "ASI", "BRN": "ASI", "IRI": "ASI", "TPE": "ASI",
    "THA": "ASI", "MAS": "ASI", "SGP": "ASI", "PHI": "ASI", "SRI": "ASI",
    "UZB": "ASI", "BHR": "ASI", "KUW": "ASI", "OMA": "ASI", "KSA": "ASI",
    "KEN": "AFR", "ETH": "AFR", "MAR": "AFR", "RSA": "AFR", "NGR": "AFR",
    "ALG": "AFR", "TUN": "AFR", "EGY": "AFR", "UGA": "AFR", "TAN": "AFR",
    "BUR": "AFR", "CIV": "AFR", "GHA": "AFR", "SEN": "AFR", "ZIM": "AFR",
    "AUS": "OCE", "NZL": "OCE", "PNG": "OCE", "SAM": "OCE", "FIJ": "OCE",
}
# ── END REGION MAP ────────────────────────────────────────────────────────────

INDOOR_MONTHS = {1, 2, 3, 11, 12}


# ── GRAPHQL QUERIES ───────────────────────────────────────────────────────────
# NOTE: These fields have been verified against the actual WA API schema.
# country is a String (not an object), competitionType does not exist,
# and total does not exist on CalendarEvents.

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
      country
      hasResults
    }
  }
}
"""

DETAIL_QUERY = """
query GetCompetitionOrganiserInfo($competitionId: Int!) {
  getCompetitionOrganiserInfo(competitionId: $competitionId) {
    websiteUrl
    units {
      events
      gender
    }
    contactPersons {
      name
      email
      phoneNumber
      title
    }
  }
}
"""
# ── END QUERIES ───────────────────────────────────────────────────────────────


def wa_request(query: str, variables: dict, retries: int = MAX_RETRIES) -> dict:
    """POST a GraphQL query. Returns the data dict or {} on any failure."""
    headers = {
        "Content-Type": "application/json",
        "x-api-key":    API_KEY,
        "Referer":      "https://worldathletics.org/",
        "Origin":       "https://worldathletics.org",
        "User-Agent":   "Mozilla/5.0 (compatible; Athletics-Hub/3.0)",
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
            # Use 'or {}' to handle both missing data AND null data
            return body.get("data") or {}
        except requests.RequestException as exc:
            wait = 2 ** attempt
            if attempt < retries:
                print(f"    Request failed (attempt {attempt}/{retries}): {exc} — retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"    Request failed after {retries} attempts: {exc}")
    return {}


def map_discipline(raw_name: str) -> Optional[str]:
    """Convert a WA discipline string to our short ID."""
    clean = raw_name.strip()
    if clean in DISCIPLINE_MAP:
        return DISCIPLINE_MAP[clean]
    for key, val in DISCIPLINE_MAP.items():
        if key.lower() == clean.lower():
            return val
    for key, val in DISCIPLINE_MAP.items():
        if key.lower() in clean.lower():
            return val
    return None


def is_indoor_meet(name: str, date_str: str) -> bool:
    if any(w in name.lower() for w in ("indoor", "hall", "halle", "salle")):
        return True
    try:
        return int(date_str[5:7]) in INDOOR_MONTHS
    except (ValueError, IndexError):
        return False


def fetch_calendar(start: str, end: str) -> list:
    """
    Fetch all meets in the date range.
    Pagination: keep fetching until a page returns fewer results than the limit,
    which means we have reached the end. (The 'total' field does not exist
    in the current WA API schema.)
    """
    all_results = []
    limit, offset = 100, 0
    while True:
        print(f"    Fetching calendar (offset={offset})…")
        data = wa_request(CALENDAR_QUERY, {
            "startDate": start,
            "endDate":   end,
            "offset":    offset,
            "limit":     limit,
        })
        page    = data.get("getCalendarEvents") or {}
        results = page.get("results") or []
        all_results.extend(results)
        print(f"    Got {len(results)} meets (running total: {len(all_results)})")
        # Stop when we get fewer results than the page size — end of data
        if len(results) < limit:
            break
        offset += limit
        time.sleep(REQUEST_DELAY)
    print(f"    Calendar fetch complete: {len(all_results)} meets")
    return all_results


def fetch_detail(meet_id) -> dict:
    data = wa_request(DETAIL_QUERY, {"competitionId": int(meet_id)})
    return data.get("getCompetitionOrganiserInfo") or {}


def parse_detail(detail: dict) -> dict:
    out = {"website": "", "contact": {}, "events": {"men": [], "women": []}}
    if not detail:
        return out

    # Field is websiteUrl in the actual API
    out["website"] = (detail.get("websiteUrl") or "").strip()

    # contactPersons with phoneNumber (not contacts/phone)
    contacts = detail.get("contactPersons") or []
    if contacts:
        c = contacts[0]
        out["contact"] = {
            "name":  (c.get("name")        or "").strip(),
            "email": (c.get("email")       or "").strip(),
            "phone": (c.get("phoneNumber") or "").strip(),
        }

    # units is a list of {gender, events} where events is a list of
    # discipline name strings — e.g. {"gender": "Men", "events": ["100m", "800m"]}
    unknown = []
    for unit in (detail.get("units") or []):
        gender_raw = (unit.get("gender") or "").strip().upper()
        # Normalise: "MEN" → "M", "WOMEN" → "W", "MIXED" → ""
        if gender_raw in ("M", "MEN", "MALE"):
            gender = "M"
        elif gender_raw in ("W", "WOMEN", "FEMALE"):
            gender = "W"
        else:
            gender = ""   # will add to both

        for raw_name in (unit.get("events") or []):
            raw_name = (raw_name or "").strip()
            mapped = map_discipline(raw_name)
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
                for lst in (out["events"]["men"], out["events"]["women"]):
                    if mapped not in lst:
                        lst.append(mapped)

    if unknown:
        print(f"      Unknown disciplines (add to DISCIPLINE_MAP): {unknown}")

    return out


def build_meet_record(raw: dict, detail: dict) -> dict:
    """
    Build a clean meet record.
    NOTE: 'country' is returned as a plain string (country code) by the WA API,
    not as an object. 'competitionType' is not available — category is inferred
    from the meet name instead.
    """
    name      = (raw.get("name") or "").strip()
    country   = (raw.get("country") or "").strip()  # Plain string e.g. "GBR"
    start     = (raw.get("startDate") or "")[:10]
    end_date  = (raw.get("endDate")   or "")[:10]

    return {
        "id":          str(raw.get("id") or ""),
        "name":        name,
        "dateStart":   start,
        "dateEnd":     end_date if end_date and end_date != start else start,
        "city":        (raw.get("venue") or "").strip(),
        "countryCode": country,
        "countryName": country,   # Name not available separately — use code for now
        "region":      COUNTRY_REGION.get(country, "OTHER"),
        "category":    detect_category(name),
        "categoryRaw": "",
        "isIndoor":    is_indoor_meet(name, start),
        "website":     detail.get("website") or "",
        "contact":     detail.get("contact") or {},
        "events":      detail.get("events") or {"men": [], "women": []},
        "hasResults":  bool(raw.get("hasResults")),
    }


def load_existing() -> dict:
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    today = datetime.date.today()
    end   = today + datetime.timedelta(days=MONTHS_AHEAD * 30)
    past  = today - datetime.timedelta(days=DAYS_PAST)

    print(f"\nAthletics Hub — fetch_calendar.py v3")
    print(f"Range: {past} → {end}")
    print(f"Endpoint: {API_ENDPOINT[:60]}…\n")

    existing = load_existing()

    raw_all = fetch_calendar(str(past), str(end))

    if len(raw_all) < MIN_MEETS_VALID:
        print(f"\nERROR: Only {len(raw_all)} meets returned (expected ≥ {MIN_MEETS_VALID}).")
        print("Check that WA_API_ENDPOINT and WA_API_KEY secrets are set correctly.")
        if existing:
            print("Keeping existing meets.json unchanged.")
        sys.exit(1)

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

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    output = {
        "updated": datetime.datetime.utcnow().isoformat() + "Z",
        "count":   len(meets),
        "meets":   meets,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nDone — {len(meets)} meets written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
