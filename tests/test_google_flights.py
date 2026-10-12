from webai.agent import _enforce_google_flights_trip_type


def test_one_way_task_rewrites_round_trip_click_to_choose_operation():
    plan = {
        "action": "click",
        "by": "role",
        "value": "combobox",
        "name": "Round trip",
        "reason": "Choose trip type",
    }
    result = _enforce_google_flights_trip_type(
        "Find a one-way flight from Goa to Bangalore",
        "https://www.google.com/travel/flights",
        plan,
    )
    assert result["action"] == "control"
    assert result["operation"] == "choose"
    assert result["target"] == "One way"
    assert result["name"] == "Round trip"
    assert plan["action"] == "click"  # input plan is not mutated


def test_trip_type_enforcement_does_not_change_unrelated_clicks():
    plan = {"action": "click", "by": "role", "value": "button", "name": "Search"}
    result = _enforce_google_flights_trip_type(
        "Find a one-way flight from Goa to Bangalore",
        "https://www.google.com/travel/flights",
        plan,
    )
    assert result == plan


def test_trip_type_enforcement_does_not_apply_to_round_trip_tasks():
    plan = {"action": "click", "by": "role", "value": "button", "name": "Round trip"}
    result = _enforce_google_flights_trip_type(
        "Find a round trip flight from Goa to Bangalore",
        "https://www.google.com/travel/flights",
        plan,
    )
    assert result == plan
