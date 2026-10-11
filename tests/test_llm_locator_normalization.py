from webai.llm import LLMClient


def test_parse_action_normalizes_locator_strategy_whitespace_and_case():
    action = LLMClient._parse_action(
        '{"action":" FILL ","by":" Placeholder ","value":"Search Amazon.in","text":"wireless computer mouse"}'
    )
    assert action["action"] == "fill"
    assert action["by"] == "placeholder"


def test_parse_action_normalizes_common_locator_aliases():
    action = LLMClient._parse_action(
        '{"action":"click","by":"CSS Selector","value":"button[type=submit]"}'
    )
    assert action["by"] == "css"


def test_parse_action_normalizes_trailing_punctuation_in_locator():
    action = LLMClient._parse_action(
        '{"action":"click","by":"xpath,","value":"//button[@type=submit]"}'
    )
    assert action["by"] == "xpath"


def test_fill_maps_misused_value_locator_to_placeholder():
    action = LLMClient._parse_action(
        '{"action":"fill","by":"value","value":"Search Amazon.in","text":"wireless computer mouse"}'
    )
    assert action["by"] == "placeholder"
