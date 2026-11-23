
"""Offline unit tests for the FamilySchedules workflow logic."""

import main


def test_find_free_slots_subtracts_busy_blocks():
    busy_blocks = {
        "Mon": [["09:00", "10:00"], ["11:00", "11:30"]]
    }

    slots = main.find_free_slots(busy_blocks, "12:00")

    monday_slots = [slot for slot in slots if slot["day"] == "Mon"]

    assert monday_slots == [
        {"day": "Mon", "start": "08:00", "end": "09:00", "minutes": 60},
        {"day": "Mon", "start": "10:00", "end": "11:00", "minutes": 60},
    ]


def test_distance_between_same_coordinates_is_zero():
    assert main.distance_km(
        40.7484, -73.9857, 40.7484, -73.9857
    ) == 0


def test_plan_writer_includes_selected_activity():
    survey = {
        "child_age": 8,
        "family_name": "Sample Family"
    }

    options = [{
        "day": "Mon",
        "slot_start": "10:00",
        "place": "Sample Playground",
        "place_type": "playground",
        "mode": "walk",
        "travel_minutes": 10,
        "activity_minutes": 30,
    }]

    plan = main.write_plan(survey, options)

    assert "Monday: Play at Sample Playground (playground)" in plan
    assert "Play from 10:10 to 10:40 (30 minutes)." in plan
    assert "Remember: always go with a grown-up you trust." in plan
