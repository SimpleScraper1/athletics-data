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

MONTHS_AHEAD       = 18
DAYS_PAST          = 14
REQUEST_DELAY      = 0.3   # seconds between detail requests
MAX_RETRIES        = 3
MIN_MEETS_VALID    = 20
CACHE_REFRESH_DAYS = 7     # always re-fetch detail for meets within this many days

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "meets.json"
)
# ── END CONFIG ────────────────────────────────────────────────────────────────


# ── DISCIPLINE MAP ────────────────────────────────────────────────────────────
# The WA API returns discipline names in a mix of formats:
#   - Short form:  "60m", "800m", "110mH", "High Jump"
#   - Long form:   "60 Metres", "800 Metres", "110 Metres Hurdles"
#   - Short track: "800m sh", "Mile sh", "Mile sh U20"
#   - Short relay: "4x100m", "4x400m"
#   - Historic:    "100y" (100 yards)
# Both short and long forms are included below.
# The normalize_discipline() function strips "sh" and "U20" suffixes
# before lookup, so variants are handled automatically.
DISCIPLINE_MAP = {
    # ── Short forms (as returned by WA API) ──────────────────────────────
    "60m": "60m",
    "100m": "100m", "100y": "100m",         # 100 yards → 100m approximation
    "200m": "200m",
    "300m": "300m",
    "400m": "400m",
    "500m": "500m",
    "600m": "600m",
    "800m": "800m",
    "1000m": "1000m",
    "1500m": "1500m",
    "Mile": "mile", "mile": "mile",
    "2000m": "2000m",
    "3000m": "3000m",
    "5000m": "5000m",
    "10000m": "10000m", "10,000m": "10000m",
    # Hurdles — short forms
    "60mH": "60mh", "60mh": "60mh",
    "80mH": "80mh", "80mh": "80mh",
    "100mH": "100mh", "100mh": "100mh",
    "110mH": "110mh", "110mh": "110mh",
    "400mH": "400mh", "400mh": "400mh",
    "3000mSC": "3000sc", "3000msc": "3000sc",
    "2000mSC": "2000sc", "2000msc": "2000sc",
    # Field — short forms
    "High Jump": "hj",   "HJ": "hj",
    "Pole Vault": "pv",  "PV": "pv",
    "Long Jump": "lj",   "LJ": "lj",
    "Triple Jump": "tj", "TJ": "tj",
    "Shot Put": "sp",    "SP": "sp",
    "Discus Throw": "dt","DT": "dt",
    "Hammer Throw": "ht","HT": "ht",
    "Javelin Throw": "jt","JT": "jt",
    "Weight Throw": "wt","WT": "wt",
    # Relays — short forms
    "4x100m": "4x100", "4x100": "4x100",
    "4x200m": "4x200", "4x200": "4x200",
    "4x400m": "4x400", "4x400": "4x400",
    "4x800m": "4x800", "4x800": "4x800",
    "4x1500m": "4x1500",
    "SMR": "smr", "DMR": "dmr",
    # Combined — short forms
    "Dec": "dec", "Hep": "hep", "Pen": "pen", "Oct": "oct",
    # Road — short forms
    "Mar": "mar", "HMar": "hmar",
    "10km": "10km", "10Km": "10km",
    "5km": "5km",
    # Race walk — short forms
    "20kmW": "20krw", "20KmW": "20krw",
    "35kmW": "35krw", "50kmW": "50krw",

    # ── Long forms ───────────────────────────────────────────────────────
    "60 Metres": "60m",
    "100 Metres": "100m", "200 Metres": "200m",
    "400 Metres": "400m", "800 Metres": "800m",
    "1500 Metres": "1500m", "One Mile": "mile", "1 Mile": "mile",
    "3000 Metres": "3000m", "5000 Metres": "5000m",
    "10,000 Metres": "10000m", "10000 Metres": "10000m",
    "10 000 Metres": "10000m",
    "60 Metres Hurdles": "60mh",
    "100 Metres Hurdles": "100mh",
    "110 Metres Hurdles": "110mh",
    "400 Metres Hurdles": "400mh",
    "3000 Metres Steeplechase": "3000sc",
    "2000 Metres Steeplechase": "2000sc",
    "Marathon": "mar", "Half Marathon": "hmar",
    "10 Kilometres": "10km", "5 Kilometres": "5km",
    "20 Kilometres Race Walk": "20krw",
    "20km Race Walk": "20krw",
    "35 Kilometres Race Walk": "35krw",
    "35km Race Walk": "35krw",
    "50 Kilometres Race Walk": "50krw",
    "4x100 Metres Relay": "4x100",
    "4 x 100 Metres Relay": "4x100",
    "4x400 Metres Relay": "4x400",
    "4 x 400 Metres Relay": "4x400",
    "4x200 Metres Relay": "4x200",
    "4 x 200 Metres Relay": "4x200",
    "4x800 Metres Relay": "4x800",
    "4x1500 Metres Relay": "4x1500",
    "Sprint Medley Relay": "smr",
    "Distance Medley Relay": "dmr",
    "Decathlon": "dec", "Heptathlon": "hep",
    "Pentathlon": "pen", "Triathlon": "tri", "Octathlon": "oct",
}
# ── END DISCIPLINE MAP ────────────────────────────────────────────────────────


def normalize_discipline(raw: str) -> str:
    """
    Strip indoor/age-group suffixes so variants resolve automatically.
    Examples:
      "Mile sh U20" → "Mile"
      "800m sh"     → "800m"
      "1500m U20"   → "1500m"
      "60mH"        → "60mH"   (no suffix to strip)
    """
    s = raw.strip()
    # Order matters — strip the longest matching suffix first
    for suffix in (" sh U20", " sh u20", " Sh U20",
                   " U20", " u20",
                   " sh", " Sh"):
        if s.lower().endswith(suffix.lower()):
            s = s[: -len(suffix)].strip()
            break   # only strip one layer per call
    return s


def map_competition_category(competition_group: str, competition_subgroup: str, ranking_category: str) -> str:
    """
    Derive the Meet Map category from the three fields available in the
    calendar API response. The API sometimes includes the subgroup (Gold/Silver/Bronze)
    inside the competitionGroup string rather than as a separate field,
    so we check the full combined string rather than subgroup alone.
    """
    group    = (competition_group    or "").lower()
    subgroup = (competition_subgroup or "").lower()
    rank     = (ranking_category     or "").upper()
    # Combine group + subgroup so we catch either pattern
    combined = group + " " + subgroup

    if "diamond league" in group:
        return "DL"
    if "continental tour" in group:
        if "gold"   in combined: return "CTG"
        if "silver" in combined: return "CTS"
        if "bronze" in combined: return "CTB"
        return "CT"
    if "indoor tour" in group:
        if "gold"   in combined: return "ITG"
        if "silver" in combined: return "ITS"
        if "bronze" in combined: return "ITB"
        return "IT"
    if any(x in group for x in ("world athletics championship", "world championship",
                                 "world indoor championship", "world cross country")):
        return "WCH"
    if "olympic" in group:
        return "OLY"
    if any(x in group for x in ("area championship", "european athletics championship",
                                 "african championship", "asian championship",
                                 "pan american", "oceanian championship")):
        return "AREA"
    if "national championship" in group or "national champ" in group:
        return "NAT"

    # Fallback: use the ranking category letter code
    if rank == "DF":             return "DL"
    if rank in ("GW", "GL"):     return "CTG"
    if rank == "OW":             return "WCH"

    return "OTHER"


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
query getCalendarEvents(
  $startDate: String
  $endDate:   String
  $offset:    Int
  $limit:     Int
) {
  getCalendarEvents(
    startDate: $startDate
    endDate:   $endDate
    offset:    $offset
    limit:     $limit
  ) {
    hits
    results {
      id
      hasResults
      hasCompetitionInformation
      name
      venue
      area
      country
      rankingCategory
      competitionGroup
      competitionSubgroup
      startDate
      endDate
      season
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
    """
    Convert a WA discipline string to our short ID.
    Tries in order: exact match → suffix-stripped match →
    case-insensitive match → partial match.
    Returns None if nothing matches (caller logs the unknown name).
    """
    clean = raw_name.strip()
    if not clean:
        return None

    # 1. Exact match
    if clean in DISCIPLINE_MAP:
        return DISCIPLINE_MAP[clean]

    # 2. After stripping indoor/age-group suffixes
    normalized = normalize_discipline(clean)
    if normalized in DISCIPLINE_MAP:
        return DISCIPLINE_MAP[normalized]

    # 3. Case-insensitive exact match on original and normalized
    for candidate in (clean, normalized):
        for key, val in DISCIPLINE_MAP.items():
            if key.lower() == candidate.lower():
                return val

    # 4. Partial match (last resort)
    for candidate in (clean, normalized):
        for key, val in DISCIPLINE_MAP.items():
            if key.lower() in candidate.lower():
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
    """Fetch all meets in the date range using the hits field for accurate pagination."""
    all_results = []
    limit, offset = 100, 0
    total = None

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

        if total is None:
            total = page.get("hits") or 0
            print(f"    Total meets available: {total}")

        all_results.extend(results)
        print(f"    Got {len(results)} meets (running total: {len(all_results)}/{total})")

        if not results or len(all_results) >= total:
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
    Category, indoor flag, and country now come directly from the API
    rather than being inferred from the meet name.
    """
    name       = (raw.get("name")               or "").strip()
    # 'country' returns the 3-letter code (e.g. "BEL"); 'area' returns region label ("Europe")
    country    = (raw.get("country")            or raw.get("area") or "").strip()
    start      = (raw.get("startDate")          or "")[:10]
    end_date   = (raw.get("endDate")            or "")[:10]
    comp_group = (raw.get("competitionGroup")   or "").strip()
    subgroup   = (raw.get("competitionSubgroup") or "").strip()
    rank_cat   = (raw.get("rankingCategory")    or "").strip()
    season     = (raw.get("season")             or "").lower()

    return {
        "id":          str(raw.get("id") or ""),
        "name":        name,
        "dateStart":   start,
        "dateEnd":     end_date if end_date and end_date != start else start,
        "city":        (raw.get("venue") or "").strip(),
        "countryCode": country,
        "countryName": country,
        "region":      COUNTRY_REGION.get(country, "OTHER"),
        "category":    map_competition_category(comp_group, subgroup, rank_cat),
        "categoryRaw": (comp_group + (" — " + subgroup if subgroup else "")).strip(),
        "isIndoor":    season == "indoor",
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

    # Load previous meets.json for smart caching
    existing_data  = load_existing()
    existing_meets = {str(m["id"]): m for m in existing_data.get("meets", [])}
    print(f"  Loaded {len(existing_meets)} existing meet records from cache\n")

    raw_all = fetch_calendar(str(past), str(end))

    if len(raw_all) < MIN_MEETS_VALID:
        print(f"\nERROR: Only {len(raw_all)} meets returned (expected ≥ {MIN_MEETS_VALID}).")
        print("Check that WA_API_ENDPOINT and WA_API_KEY secrets are set correctly.")
        if existing_data:
            print("Keeping existing meets.json unchanged.")
        sys.exit(1)

    meets = []
    total    = len(raw_all)
    fetched  = 0
    cached   = 0
    no_info  = 0

    for i, raw in enumerate(raw_all, 1):
        meet_id  = str(raw.get("id") or "")
        name     = raw.get("name") or "?"
        has_info = bool(raw.get("hasCompetitionInformation"))

        # Days until meet starts (for deciding whether to refresh cache)
        try:
            start_date = datetime.date.fromisoformat((raw.get("startDate") or "")[:10])
            days_until = (start_date - today).days
        except ValueError:
            days_until = 999

        print(f"  [{i:>3}/{total}] {name}", end="")

        if not has_info:
            # No competition information registered — skip detail fetch entirely
            print(" [no info]")
            no_info += 1
            detail = {"website": "", "contact": {}, "events": {"men": [], "women": []}}

        elif meet_id in existing_meets and days_until > CACHE_REFRESH_DAYS:
            # Meet exists in cache and is not imminent — check if events are populated
            ex        = existing_meets[meet_id]
            ex_events = ex.get("events", {})
            has_evs   = bool(ex_events.get("men") or ex_events.get("women"))
            has_web   = bool(ex.get("website") or (ex.get("contact") or {}).get("email"))

            if has_evs and has_web:
                # Fully cached — reuse existing detail data
                print(" [cached]")
                cached += 1
                detail = {
                    "website": ex.get("website") or "",
                    "contact": ex.get("contact") or {},
                    "events":  ex_events,
                }
            else:
                # In cache but missing events or website — re-fetch
                print(" [refresh — incomplete]")
                try:
                    detail = parse_detail(fetch_detail(meet_id))
                except Exception as exc:
                    print(f"\n    Warning: {exc}")
                    detail = {"website": "", "contact": {}, "events": {"men": [], "women": []}}
                fetched += 1
                time.sleep(REQUEST_DELAY)

        else:
            # New meet, or within CACHE_REFRESH_DAYS of start — always fetch fresh
            tag = "[new]" if meet_id not in existing_meets else "[imminent — refresh]"
            print(f" {tag}")
            try:
                detail = parse_detail(fetch_detail(meet_id))
            except Exception as exc:
                print(f"\n    Warning: {exc}")
                detail = {"website": "", "contact": {}, "events": {"men": [], "women": []}}
            fetched += 1
            time.sleep(REQUEST_DELAY)

        meets.append(build_meet_record(raw, detail))

    print(f"\n  Detail queries — fetched: {fetched}  cached: {cached}  no info: {no_info}")

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
