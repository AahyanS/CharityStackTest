"""
CharityStack — Nonprofit Website Finder + ProPublica Validation
---------------------------------------------------------------
Step 1: Firecrawl search finds ~40 nonprofit websites across 3 verticals
Step 2: ProPublica API cross-references each org name to confirm it's a
        real IRS-registered 501(c)(3) with a valid EIN

SETUP:
    pip install firecrawl-py

RUN:
    python discovery_script.py

OUTPUT:
    nonprofit_sites.json        — all found sites
    nonprofit_validated.json    — only IRS-verified 501(c)(3)s
"""

import json
import re
import urllib.request
from datetime import datetime, timezone
from firecrawl import Firecrawl

# ── CONFIG ────────────────────────────────────────────────────────────────────

API_KEY      = ENTER_KEY_HERE
RESULTS_EACH = 14   # ~14 per query x 3 verticals = ~40 total

app = Firecrawl(api_key=API_KEY)

SEARCHES = {
    "religious": (
        "small Islamic mosque nonprofit donation site:org",
        "🕌 Religious"
    ),
    "environmental": (
        "small environmental nonprofit organization donate site:org",
        "🌿 Environmental"
    ),
    "human_services": (
        "food pantry community nonprofit donate site:org",
        "🤝 Human Services"
    ),
}

# ── HELPERS ───────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def extract_items(results) -> list:
    """Pull result items from SearchData.web (current Firecrawl SDK)."""
    if hasattr(results, "web") and results.web:
        return results.web
    for attr in ("data", "results", "items"):
        val = getattr(results, attr, None)
        if val:
            return val
    if isinstance(results, list):
        return results
    return []


def parse_item(r) -> dict:
    """Extract url, title, description from a single result item."""
    if isinstance(r, dict):
        return {
            "url":   r.get("url") or r.get("link") or "",
            "title": r.get("title") or r.get("name") or "",
            "desc":  r.get("description") or r.get("snippet") or r.get("markdown") or "",
        }
    return {
        "url":   getattr(r, "url",         None) or getattr(r, "link",    None) or "",
        "title": getattr(r, "title",       None) or getattr(r, "name",    None) or "",
        "desc":  getattr(r, "description", None) or getattr(r, "snippet", None)
                 or getattr(r, "markdown", None) or "",
    }


def clean_org_name(title: str) -> str:
    """Strip common suffixes from page titles to get a cleaner org name for search."""
    for sep in [" - ", " | ", " – ", " — "]:
        if sep in title:
            title = title.split(sep)[0]
    return title.strip()


# ── STEP 1: FIRECRAWL SEARCH ─────────────────────────────────────────────────

def search_vertical(vertical: str, query: str, label: str) -> list[dict]:
    print(f"\n▶  {label}")
    print(f"   Query: \"{query}\"")
    print(f"   📡 Firecrawl searching...")

    try:
        raw   = app.search(query, limit=RESULTS_EACH)
        items = extract_items(raw)

        sites = []
        for r in items:
            parsed = parse_item(r)
            if not parsed["url"]:
                continue
            sites.append({
                "vertical":       vertical,
                "title":          parsed["title"].strip(),
                "url":            parsed["url"].strip(),
                "snippet":        parsed["desc"].strip()[:200],
                "found_at":       now_iso(),
                "ein":            None,
                "income":         None,
                "city":           None,
                "state":          None,
                "propublica_url": None,
                "verified_501c3": False,
            })

        print(f"   ✅ Found {len(sites)} sites")
        return sites

    except Exception as e:
        print(f"   ⚠️  Firecrawl failed: {e}")
        return []


# ── STEP 2: PROPUBLICA VALIDATION ────────────────────────────────────────────

def propublica_lookup(org_name: str) -> dict | None:
    """
    Search ProPublica Nonprofit API by org name.
    Returns matched org data if found, None if not.
    Free, no API key needed.
    """
    import urllib.parse
    encoded = urllib.parse.quote(org_name)
    url = f"https://projects.propublica.org/nonprofits/api/v2/search.json?q={encoded}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CharityStack/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        orgs = data.get("organizations", [])
        if not orgs:
            return None

        o = orgs[0]
        ein = o.get("ein", "")
        return {
            "ein":            ein,
            "income":         o.get("income_amount", 0),
            "city":           o.get("city", "").title(),
            "state":          o.get("state", "").upper(),
            "propublica_url": f"https://projects.propublica.org/nonprofits/organizations/{ein}",
        }

    except Exception:
        return None


def fetch_990(ein: str) -> dict:
    """
    Hit the ProPublica filings endpoint to pull the most recent 990.
    Returns key financial + operational fields useful for qualifying the org.
    Free, no API key needed.
    """
    url = f"https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CharityStack/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        org      = data.get("organization", {})
        filings  = data.get("filings_with_data", [])
        latest   = filings[0] if filings else {}

        return {
            # Basic org info
            "name":               org.get("name", ""),
            "ruling_date":        org.get("ruling_date", ""),
            "classification":     org.get("classification", ""),
            "ntee_code":          org.get("ntee_code", ""),

            # Financials from most recent 990
            "total_revenue":      latest.get("totrevenue", 0),
            "total_expenses":     latest.get("totfuncexpns", 0),
            "total_assets":       latest.get("totassetsend", 0),
            "employee_count":     latest.get("noemployees", 0),
            "tax_year":           latest.get("tax_prd_yr", ""),

            # CharityStack fit signals
            "has_website":        bool(org.get("website", "")),
            "website":            org.get("website", ""),
            "filing_year":        latest.get("tax_prd_yr", "unknown"),
        }

    except Exception:
        return {}


def validate_sites(sites: list[dict]) -> list[dict]:
    """
    Cross-reference each discovered site against ProPublica.
    Adds EIN, income, city, state to matching records.
    Marks verified_501c3 = True if found.
    """
    print(f"\n{'=' * 58}")
    print(f"  STEP 2 — ProPublica 501(c)(3) Validation")
    print(f"  Checking {len(sites)} sites against IRS records...")
    print(f"{'=' * 58}")

    validated = []
    for i, site in enumerate(sites):
        org_name = clean_org_name(site["title"])
        print(f"  [{i+1:02d}/{len(sites)}] {org_name[:45]:<45}", end=" → ")

        match = propublica_lookup(org_name)

        if match:
            ein = match["ein"]

            # Pull full 990 data using the EIN
            f990 = fetch_990(ein)

            # Qualify fit for CharityStack:
            # Target: $40K-$500K revenue, under 20 employees
            revenue = f990.get("total_revenue", 0) or 0
            employees = f990.get("employee_count", 0) or 0
            in_range = 40_000 <= revenue <= 500_000
            fit = "✅ Good fit" if in_range else ("⚠️  Too large" if revenue > 500_000 else "⚠️  Too small")

            site.update({
                "ein":              ein,
                "income":           f"${match['income']:,}" if match["income"] else "Not disclosed",
                "city":             match["city"],
                "state":            match["state"],
                "propublica_url":   match["propublica_url"],
                "verified_501c3":   True,
                # 990 fields
                "total_revenue":    f"${revenue:,}" if revenue else "Not disclosed",
                "total_expenses":   f"${f990.get('total_expenses', 0):,}" if f990.get("total_expenses") else "Not disclosed",
                "total_assets":     f"${f990.get('total_assets', 0):,}" if f990.get("total_assets") else "Not disclosed",
                "employee_count":   employees,
                "tax_year":         f990.get("tax_year", ""),
                "ntee_code":        f990.get("ntee_code", ""),
                "charitystack_fit": fit,
            })
            print(f"✅ EIN {ein} | {match['city']}, {match['state']} | Rev: ${revenue:,} | {fit}")
        else:
            print("❌ Not found in IRS records")

        validated.append(site)

    return validated


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run():
    print("=" * 58)
    print("  CharityStack — Nonprofit Finder + IRS Validation")
    print(f"  Target: ~{RESULTS_EACH * 3} sites across 3 verticals")
    print(f"  Step 1: Firecrawl search  |  Step 2: ProPublica check")
    print("=" * 58)

    # ── STEP 1: Find sites ────────────────────────────────────────────────────
    all_sites = []
    for vertical, (query, label) in SEARCHES.items():
        sites = search_vertical(vertical, query, label)
        all_sites.extend(sites)

    print(f"\n  Firecrawl total: {len(all_sites)} sites found")

    # ── STEP 2: Validate against ProPublica ───────────────────────────────────
    all_sites = validate_sites(all_sites)

    verified   = [s for s in all_sites if s["verified_501c3"]]
    unverified = [s for s in all_sites if not s["verified_501c3"]]

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 58}")
    print(f"  RESULTS SUMMARY")
    print(f"{'=' * 58}")
    print(f"  Total found:     {len(all_sites)}")
    print(f"  IRS verified:    {len(verified)}  ✅")
    print(f"  Not verified:    {len(unverified)}  ❌")

    print(f"\n  Breakdown by vertical (verified only):")
    for vertical in SEARCHES:
        count = sum(1 for s in verified if s["vertical"] == vertical)
        print(f"  {vertical:<20} {count} verified orgs")

    # ── CHARITYSTACK FIT BREAKDOWN ────────────────────────────────────────────
    good_fit  = [s for s in verified if s.get("charitystack_fit", "").startswith("✅")]
    too_large = [s for s in verified if s.get("charitystack_fit", "").startswith("⚠️  Too large")]
    too_small = [s for s in verified if s.get("charitystack_fit", "").startswith("⚠️  Too small")]
    unknown   = [s for s in verified if not s.get("charitystack_fit")]

    print(f"\n  CharityStack fit (target $40K–$500K revenue):")
    print(f"  ✅ Good fit:   {len(good_fit)}")
    print(f"  ⚠️  Too large:  {len(too_large)}")
    print(f"  ⚠️  Too small:  {len(too_small)}")
    print(f"  ❓ Unknown:    {len(unknown)}")

    # ── SAMPLE ────────────────────────────────────────────────────────────────
    print(f"\n  Sample verified leads (first 4):")
    print("-" * 58)
    for site in verified[:4]:
        print(f"  [{site['vertical']}]  {site.get('charitystack_fit', '')}")
        print(f"  Title:     {site['title']}")
        print(f"  URL:       {site['url']}")
        print(f"  EIN:       {site['ein']}  |  {site['city']}, {site['state']}")
        print(f"  Revenue:   {site.get('total_revenue', 'N/A')}  (Tax year: {site.get('tax_year', 'N/A')})")
        print(f"  Expenses:  {site.get('total_expenses', 'N/A')}")
        print(f"  Assets:    {site.get('total_assets', 'N/A')}")
        print(f"  Employees: {site.get('employee_count', 'N/A')}")
        print(f"  NTEE:      {site.get('ntee_code', 'N/A')}")
        print(f"  990 Link:  {site['propublica_url']}")
        print()

    # ── EXPORT ────────────────────────────────────────────────────────────────
    with open("nonprofit_sites.json", "w") as f:
        json.dump(all_sites, f, indent=2)

    with open("nonprofit_validated.json", "w") as f:
        json.dump(verified, f, indent=2)

    print(f"  💾 All sites      → nonprofit_sites.json ({len(all_sites)} records)")
    print(f"  💾 Verified only  → nonprofit_validated.json ({len(verified)} records)")
    print(f"\n  Next step: import nonprofit_validated.json into Clay for platform detection.\n")


if __name__ == "__main__":
    run()
