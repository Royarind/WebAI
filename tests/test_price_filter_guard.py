from webai.agent import _filter_price_mismatch, _requested_price_ceiling


def test_extracts_requested_price_ceiling_with_rupee_format():
    assert _requested_price_ceiling("filter for products priced below ₹1,000") == 1000


def test_rejects_lower_price_band_than_requested_ceiling():
    mismatch = _filter_price_mismatch(
        "Find wireless mice below ₹1,000",
        {"action": "click", "by": "xpath", "value": "//span[text()='Up to ₹200']"},
    )
    assert mismatch is not None
    assert mismatch["proposed_ceiling"] == 200
    assert mismatch["requested_ceiling"] == 1000


def test_allows_matching_or_higher_price_band():
    assert _filter_price_mismatch(
        "Find wireless mice below ₹1,000",
        {"action": "click", "by": "text", "value": "Under ₹1,000"},
    ) is None


def test_ignores_non_price_actions():
    assert _filter_price_mismatch(
        "Find wireless mice below ₹1,000",
        {"action": "click", "by": "role", "value": "button", "name": "Search"},
    ) is None
