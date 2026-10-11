from webai.verification import verify_finish_evidence


class FakePage:
    def __init__(self, state):
        self.state = state

    def evaluate(self, script):
        return self.state


def test_verification_accepts_evidence_present_in_live_state():
    result = verify_finish_evidence(
        FakePage("Product: Citrine Forest Green. Size M. Bag contains 1 item."),
        "Citrine Forest Green Size M",
    )
    assert result["verified"] is True


def test_verification_rejects_evidence_absent_from_live_state():
    result = verify_finish_evidence(
        FakePage("Product: Black. Size S. Bag is empty."),
        "Citrine Forest Green Size M",
    )
    assert result["verified"] is False
    assert result["missing_terms"]


def test_verification_rejects_empty_evidence():
    result = verify_finish_evidence(FakePage("Some page text"), "")
    assert result["verified"] is False
