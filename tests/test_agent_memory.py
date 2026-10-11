from webai.agent import sensitive
from webai.memory import Memory
from webai.llm import SYSTEM

def test_consequential_tasks_are_flagged():
    assert sensitive('purchase this item')
    assert sensitive('send email to a customer')
    assert not sensitive('inspect the page')

def test_memory_stores_runs_and_notes(tmp_path):
    m=Memory(str(tmp_path/'memory.sqlite3'))
    m.add_run('inspect page','completed','found controls')
    assert m.recent_runs(1)[0]['task']=='inspect page'
    m.add_note('example.com','invoice table',{'locator':'#invoices'})
    assert m.notes_for('example.com')[0]['note']=='invoice table'

def test_agent_prompt_has_constrained_actions():
    assert 'Allowed actions' in SYSTEM
    assert 'Never bypass CAPTCHA' in SYSTEM


def test_agent_recovers_from_action_timeout_without_blind_retry():
    from webai.agent import Agent

    agent = Agent.__new__(Agent)
    calls = []

    def failing_action(plan):
        calls.append(plan)
        raise TimeoutError("shopping-anchor did not appear before timeout")

    agent._act = failing_action
    result = agent._execute_action_with_recovery({"action": "click", "value": "Add to Bag"})

    assert result["ok"] is False
    assert result["error_type"] == "TimeoutError"
    assert "shopping-anchor" in result["error"]
    assert "re-inspect" in result["recovery_hint"].lower()
    assert len(calls) == 1  # The failed click is not automatically repeated.


def test_finish_requires_explicit_verification():
    from webai.agent import Agent

    status, summary = Agent._finish_status({"action": "finish", "summary": "Added item to bag"})
    assert status == "completed_unverified"
    assert "unverified" in summary.lower()

    status, summary = Agent._finish_status({
        "action": "finish",
        "summary": "Requested option is visibly selected",
        "verified": True,
    })
    assert status == "completed"
    assert summary == "Requested option is visibly selected"


def test_agent_prompt_requires_observable_verification():
    assert "observable evidence" in SYSTEM
    assert "verified=true" in SYSTEM
