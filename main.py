"""
Rough draft of the workflow: "Fitting Physical Activities into Family Schedules".

Run it with one command:
    python main.py

It follows the wire diagram, one numbered step per box, using ONE made-up
family (family_survey.json). Do not put a real family's information in here.
Everything is in one file on purpose: this is a rough draft.
"""

import argparse
import json
import math
import os

import requests

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
USER_AGENT = "FamilySchedulesCourseProject/0.1 (student project)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Several free public Overpass servers; the program tries them in order.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
REQUEST_TIMEOUT = 30

SEARCH_RADIUS_M = 1500      # how far from home to look for places
DAY_START = "08:00"         # earliest time of day to plan activities
MIN_SLOT_MINUTES = 45       # ignore free gaps shorter than this
MIN_ACTIVITY_MINUTES = 20   # skip options with less than this much play time
MAX_ACTIVITY_MINUTES = 60   # do not plan more than this per outing
MAX_OPTIONS = 5             # how many outings go in the weekly plan

SPEEDS_KMH = {"walk": 4.8, "bike": 14.0, "transit": 20.0, "car": 30.0}
DETOUR_FACTOR = 1.3         # streets are longer than a straight line

DAY_NAMES = {
    "Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday",
    "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday",
}
DAY_ORDER = list(DAY_NAMES.keys())

# Backup places, used ONLY if the online place search fails. They are real
# parks near the sample address, so the rest of the workflow can still run.
BACKUP_PLACES = [
    {"name": "Bryant Park", "type": "park", "lat": 40.7536, "lon": -73.9832},
    {"name": "Madison Square Park", "type": "park", "lat": 40.7421, "lon": -73.9879},
    {"name": "Greeley Square", "type": "park", "lat": 40.7490, "lon": -73.9881},
]


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def to_minutes(hhmm):
    """'15:30' -> 930 (minutes since midnight)."""
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def to_hhmm(total_minutes):
    """930 -> '15:30'."""
    return "%02d:%02d" % (total_minutes // 60, total_minutes % 60)


def distance_km(lat1, lon1, lat2, lon2):
    """Straight-line distance between two points on Earth (haversine)."""
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


# ----------------------------------------------------------------------------
# Step 1: Family Survey Form (input)
# ----------------------------------------------------------------------------
def load_family_survey(path):
    with open(path, "r", encoding="utf-8") as f:
        survey = json.load(f)
    needed = ["address", "child_age", "travel_modes", "latest_home_time", "busy_blocks"]
    missing = [key for key in needed if key not in survey]
    if missing:
        raise ValueError("Survey file is missing: " + ", ".join(missing))
    for mode in survey["travel_modes"]:
        if mode not in SPEEDS_KMH:
            raise ValueError("Unknown travel mode: %s" % mode)
    return survey


# ----------------------------------------------------------------------------
# Step 2: Address Geocoder (atomic protocol: OpenStreetMap Nominatim)
# ----------------------------------------------------------------------------
def geocode_address(address):
    response = requests.get(
        NOMINATIM_URL,
        params={
            "q": address,
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": "us",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        raise ValueError("The address was not found: " + address)
    return float(results[0]["lat"]), float(results[0]["lon"])


# ----------------------------------------------------------------------------
# Step 3: Nearby Places Lookup (atomic protocol: OpenStreetMap Overpass)
# ----------------------------------------------------------------------------
def find_nearby_places(lat, lon):
    query = (
        "[out:json][timeout:25];"
        'nwr["leisure"~"^(park|playground|pitch)$"]["name"]'
        "(around:%d,%f,%f);"
        "out center 40;" % (SEARCH_RADIUS_M, lat, lon)
    )
    elements = None
    for url in OVERPASS_URLS:
        try:
            response = requests.post(
                url,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            elements = response.json().get("elements", [])
            print("   Got places from %s" % url.split("/")[2])
            break
        except (requests.RequestException, ValueError) as error:
            print("   Could not use %s (%s)" % (url.split("/")[2], type(error).__name__))
    if elements is None:
        print("   WARNING: every place-search server failed.")
        print("   Using BACKUP sample places instead.")
        return [dict(place) for place in BACKUP_PLACES]

    places = []
    seen = set()
    for item in elements:
        tags = item.get("tags", {})
        name = tags.get("name")
        center = item if "lat" in item else item.get("center")
        if not name or not center or name in seen:
            continue
        seen.add(name)
        places.append({
            "name": name,
            "type": tags.get("leisure", "park"),
            "lat": center["lat"],
            "lon": center["lon"],
        })
    if not places:
        print("   WARNING: no places returned. Using BACKUP sample places instead.")
        return [dict(place) for place in BACKUP_PLACES]
    return places[:15]


# ----------------------------------------------------------------------------
# Step 4: Free-Time Finder (disposable component)
# ----------------------------------------------------------------------------
def find_free_slots(busy_blocks, latest_home_time):
    """Subtract busy blocks from each day to leave free time slots."""
    slots = []
    day_end = to_minutes(latest_home_time)
    for day in DAY_ORDER:
        cursor = to_minutes(DAY_START)
        blocks = sorted(
            (to_minutes(start), to_minutes(end))
            for start, end in busy_blocks.get(day, [])
        )
        gaps = []
        for start, end in blocks:
            if start > cursor:
                gaps.append((cursor, min(start, day_end)))
            cursor = max(cursor, end)
        if cursor < day_end:
            gaps.append((cursor, day_end))
        for start, end in gaps:
            minutes = end - start
            if minutes >= MIN_SLOT_MINUTES:
                slots.append({"day": day, "start": to_hhmm(start),
                              "end": to_hhmm(end), "minutes": minutes})
    return slots


# ----------------------------------------------------------------------------
# Step 5: Travel-Time Calculator (atomic protocol, simplified for the draft)
# ----------------------------------------------------------------------------
def add_travel_times(home_lat, home_lon, places, travel_modes):
    """Estimate one-way minutes by each allowed mode and keep the fastest."""
    for place in places:
        km = distance_km(home_lat, home_lon, place["lat"], place["lon"]) * DETOUR_FACTOR
        by_mode = {}
        for mode in travel_modes:
            by_mode[mode] = max(1, int(round(km / SPEEDS_KMH[mode] * 60)))
        best_mode = min(by_mode, key=by_mode.get)
        place["travel_minutes"] = by_mode
        place["best_mode"] = best_mode
        place["best_minutes"] = by_mode[best_mode]
    return places


# ----------------------------------------------------------------------------
# Step 6: Option Ranker (disposable component)
# ----------------------------------------------------------------------------
def rank_options(slots, places):
    """Keep outings that fit in a free slot; rank by play time, then travel."""
    options = []
    for slot in slots:
        for place in places:
            round_trip = 2 * place["best_minutes"]
            activity = min(slot["minutes"] - round_trip, MAX_ACTIVITY_MINUTES)
            if activity < MIN_ACTIVITY_MINUTES:
                continue
            options.append({
                "day": slot["day"],
                "slot_start": slot["start"],
                "place": place["name"],
                "place_type": place["type"],
                "mode": place["best_mode"],
                "travel_minutes": place["best_minutes"],
                "activity_minutes": activity,
            })
    options.sort(key=lambda o: (-o["activity_minutes"], o["travel_minutes"]))

    # Pick the best option for each day. Try not to repeat the same place so
    # the week has some variety; fall back to repeats if there are too few places.
    chosen, used_days, used_places = [], set(), set()
    for option in options:
        if option["day"] not in used_days and option["place"] not in used_places:
            chosen.append(option)
            used_days.add(option["day"])
            used_places.add(option["place"])
    for option in options:
        if option["day"] not in used_days:
            chosen.append(option)
            used_days.add(option["day"])
    chosen.sort(key=lambda o: DAY_ORDER.index(o["day"]))
    return chosen[:MAX_OPTIONS]


# ----------------------------------------------------------------------------
# Step 7: Plan Writer (disposable component; plain template for the draft,
#         the language model can replace this later)
# ----------------------------------------------------------------------------
def write_plan(survey, options):
    age = survey["child_age"]
    lines = ["WEEKLY ACTIVITY PLAN", "For: %s" % survey.get("family_name", "Family"), ""]
    if not options:
        lines.append("We could not find an outing that fits this week's free time.")
        return "\n".join(lines)

    lines.append("Hi! Here are some fun ways to get moving this week.")
    lines.append("")
    for option in options:
        start = to_minutes(option["slot_start"]) + option["travel_minutes"]
        end = start + option["activity_minutes"]
        verb = {"walk": "Walk", "bike": "Bike", "transit": "Take the bus or train",
                "car": "Drive"}.get(option["mode"], "Go")
        lines.append("%s: Play at %s (%s)" % (
            DAY_NAMES[option["day"]], option["place"], option["place_type"]))
        unit = "minute" if option["travel_minutes"] == 1 else "minutes"
        lines.append("  %s there (about %d %s)." % (verb, option["travel_minutes"], unit))
        lines.append("  Play from %s to %s (%d minutes)." % (
            to_hhmm(start), to_hhmm(end), option["activity_minutes"]))
        lines.append("")
    if age <= 10:
        lines.append("Remember: always go with a grown-up you trust.")
    lines.append("Have fun and drink water!")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Step 8: Human Review (human step)
# ----------------------------------------------------------------------------
def human_review(plan_text, auto_approve):
    print("")
    print("=" * 60)
    print(plan_text)
    print("=" * 60)
    if auto_approve:
        print("(--auto-approve was used, so no person reviewed this plan.)")
        return True
    answer = input("Approve this plan? Type y for yes or n for no: ").strip().lower()
    return answer in ("y", "yes")


# ----------------------------------------------------------------------------
# Step 9: Final Output (human step: family receives the approved plan)
# ----------------------------------------------------------------------------
def save_final_plan(plan_text, path):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(plan_text + "\n")


# ----------------------------------------------------------------------------
# Main: run every step in order
# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Family activity planner (rough draft).")
    parser.add_argument("--survey", default="family_survey.json", help="survey JSON file")
    parser.add_argument("--out", default="output/approved_plan.txt", help="where to save the plan")
    parser.add_argument("--auto-approve", action="store_true",
                        help="skip the question and approve (for testing only)")
    args = parser.parse_args()

    print("1. Reading the family survey...")
    survey = load_family_survey(args.survey)

    print("2. Finding the home location (Address Geocoder)...")
    home_lat, home_lon = geocode_address(survey["address"])
    print("   Home is at %.5f, %.5f" % (home_lat, home_lon))

    print("3. Looking for parks and playgrounds nearby (Nearby Places Lookup)...")
    places = find_nearby_places(home_lat, home_lon)
    print("   Found %d places" % len(places))

    print("4. Finding free time (Free-Time Finder)...")
    slots = find_free_slots(survey["busy_blocks"], survey["latest_home_time"])
    print("   Found %d free slots" % len(slots))

    print("5. Estimating travel time (Travel-Time Calculator)...")
    places = add_travel_times(home_lat, home_lon, places, survey["travel_modes"])

    print("6. Ranking options (Option Ranker)...")
    options = rank_options(slots, places)
    print("   Kept %d options" % len(options))

    print("7. Writing the plan (Plan Writer)...")
    plan_text = write_plan(survey, options)

    print("8. Human review...")
    approved = human_review(plan_text, args.auto_approve)

    if approved:
        print("9. Saving the approved plan (Final Output)...")
        save_final_plan(plan_text, args.out)
        print("Done. Plan saved to %s" % args.out)
    else:
        print("Plan not approved, so nothing was saved.")


if __name__ == "__main__":
    main()
