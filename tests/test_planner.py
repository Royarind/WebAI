import pytest
from webai.planner import rule_plan

def test_basic_natural_language_plans():
    assert rule_plan("inspect the page")["action"] == "inspect"
    plan = rule_plan('click the link named More information')
    assert plan == {"action": "click", "by": "role", "value": "link", "name": "More information"}
    fill = rule_plan('fill Email with "qa@example.com"')
    assert fill["action"] == "fill"
    assert fill["value"] == "Email"
    assert fill["text"] == "qa@example.com"

def test_planner_rejects_high_impact_intent():
    with pytest.raises(ValueError):
        rule_plan("delete the account")
