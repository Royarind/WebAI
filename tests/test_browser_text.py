from webai.browser import WebAI


class FakeLocator:
    def __init__(self, values):
        self.values = values

    def count(self):
        return len(self.values)

    def nth(self, index):
        return FakeLocator([self.values[index]])

    def inner_text(self):
        if not self.values:
            raise AssertionError("inner_text called on empty locator")
        return self.values[0]


class FakePage:
    title = lambda self: "Test page"
    url = "https://example.test/"

    def __init__(self, values):
        self.values = values

    def locator(self, selector):
        return FakeLocator(self.values)


def make_browser(values):
    browser = WebAI.__new__(WebAI)
    browser.page = FakePage(values)
    return browser


def test_text_reads_multiple_matches_instead_of_failing():
    browser = make_browser(["First paragraph", "Second paragraph", "Third paragraph"])

    result = browser.text("css", "article p")

    assert "First paragraph" in result
    assert "Second paragraph" in result
    assert "Third paragraph" in result


def test_text_bounds_number_of_matches_and_output_size():
    browser = make_browser([f"Paragraph {i}" for i in range(10)])

    result = browser.text("css", "article p", max_matches=3)

    assert "Paragraph 0" in result
    assert "Paragraph 2" in result
    assert "Paragraph 3" not in result
    assert "Showing 3 of 10 matching elements" in result


def test_text_reports_zero_matches_with_locator_and_page_context():
    browser = make_browser([])

    try:
        browser.text("css", "#missing")
    except LookupError as exc:
        message = str(exc)
        assert "#missing" in message
        assert "https://example.test/" in message
        assert "Inspect the live page" in message
    else:
        raise AssertionError("Expected a useful LookupError for zero matches")


def test_text_truncates_long_extracted_content():
    browser = make_browser(["x" * 100])

    result = browser.text("css", "article p", max_chars=20)

    assert len(result) < 60
    assert result.endswith("... [text truncated]")
