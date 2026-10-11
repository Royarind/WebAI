from webai.agent import _compact_elements, _compact_overlays, _compact_result


def test_compact_elements_limits_count_and_long_fields():
    items = [
        {
            "index": i,
            "tag": "button",
            "name": "x" * 300,
            "frame_url": "https://example.test/" + ("large" * 100),
            "disabled": False,
        }
        for i in range(40)
    ]

    compact = _compact_elements(items, 12)

    assert len(compact) == 12
    assert all(len(item["name"]) <= 180 for item in compact)
    assert all("frame_url" not in item for item in compact)


def test_compact_overlays_limits_overlay_and_button_count():
    overlays = [
        {
            "category": "marketing",
            "text": "x" * 1000,
            "buttons": [{"text": f"button-{i}"} for i in range(15)],
        }
        for _ in range(5)
    ]

    compact = _compact_overlays(overlays, 2)

    assert len(compact) == 2
    assert len(compact[0]["text"]) == 350
    assert len(compact[0]["buttons"]) == 6


def test_compact_result_bounds_extracted_text_and_elements():
    result = {"ok": True, "text": "x" * 3000, "elements": [{"index": i, "tag": "a"} for i in range(80)]}

    compact = _compact_result(result)

    assert len(compact["text"]) < 1900
    assert len(compact["elements"]) == 24
    assert len(result["text"]) == 3000
