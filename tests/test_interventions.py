from types import SimpleNamespace

from webai.interventions import detect_intervention, intervention_for_status


class FakeLocator:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout=None):
        return self.text


class FakePage:
    def __init__(self, url, title, text):
        self.url = url
        self._title = title
        self._text = text

    def title(self):
        return self._title

    def locator(self, selector):
        return FakeLocator(self._text)


def test_detects_google_automated_traffic_challenge():
    page = FakePage("https://www.google.com/sorry/index", "Google", "Our systems have detected unusual traffic from your computer network.")
    result = detect_intervention(page)
    assert result["type"] == "captcha_challenge"
    assert "yourself" in result["user_action"]


def test_detects_explicit_authentication_required():
    page = FakePage("https://example.com/verify", "Verify", "Sign in to continue. Enter the verification code.")
    assert detect_intervention(page)["type"] == "authentication_required"


def test_contact_input_requires_explicit_page_prompt():
    page = FakePage("https://example.com/profile", "Profile", "Phone number is required to continue.")
    assert detect_intervention(page)["type"] == "contact_input_required"


def test_regular_phone_field_alone_does_not_pause():
    page = FakePage("https://example.com/contact", "Contact", "Contact us by phone or email.")
    assert detect_intervention(page) is None


def test_repeated_action_maps_to_agent_stuck():
    page = FakePage("https://example.com", "Example", "Welcome")
    result = detect_intervention(page, reason="Action failed", repeat_count=2)
    assert result["type"] == "agent_stuck"


def test_approval_status_has_structured_intervention():
    result = intervention_for_status("needs_approval", page=SimpleNamespace(url="https://example.com"), summary="Confirm booking")
    assert result["type"] == "approval_required"
