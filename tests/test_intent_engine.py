from webai.intent_engine import assess_intent, next_step_guidance


def test_briefing_intent_infers_email_calendar_and_files():
    intent = assess_intent("Catch me up on work and tell me what needs my attention")
    assert intent["intent"] == "briefing"
    assert {"email", "calendar", "files"}.issubset(set(intent["likely_tool_domains"]))
    assert "summary" in intent["expected_outputs"]


def test_personalized_reply_infers_messaging_and_draft():
    intent = assess_intent("Draft a WhatsApp reply in my style")
    assert intent["intent"] == "personalized_communication"
    assert "messaging" in intent["likely_tool_domains"]
    assert "draft" in intent["expected_outputs"]


def test_multi_step_goal_is_represented_as_objectives():
    intent = assess_intent("Research three vendors and then compare pricing; prepare a report")
    assert len(intent["objectives"]) == 3
    assert all(item["status"] == "pending" for item in intent["objectives"])


def test_risky_actions_include_approval_context():
    intent = assess_intent("Send email to the team and delete the old draft")
    assert "external_communication" in intent["risk_categories"]
    assert "destructive" in intent["risk_categories"]
    assert any("explicit authorization" in rule for rule in intent["context_rules"])


def test_next_step_guidance_reacts_to_failed_action():
    intent = assess_intent("Find and summarize a project document")
    guidance = next_step_guidance(
        intent,
        observation={"url": "https://example.com"},
        last_result={"ok": False, "error": "timeout"},
    )
    assert guidance["last_action_failed"] is True
    assert "different recovery strategy" in guidance["next_step_guidance"]
