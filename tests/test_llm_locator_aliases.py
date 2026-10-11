from webai.llm import LLMClient


def test_parse_action_normalizes_playwright_locator_aliases():
    cases = {
        "get_by_role": "role",
        "get_by_label": "label",
        "get_by_placeholder": "placeholder",
        "visible_text": "text",
        "css_path": "css",
        "xpath_expression": "xpath",
        "data-testid": "test_id",
    }
    for raw, expected in cases.items():
        action = LLMClient._parse_action(
            '{"action":"click","by":' + __import__("json").dumps(raw) + ',"value":"target"}'
        )
        assert action["by"] == expected
