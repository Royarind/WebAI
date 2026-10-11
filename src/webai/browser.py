from pathlib import Path
from playwright.sync_api import sync_playwright
from .locators import inventory, make_locator
from . import actions

class WebAI:
    """Stateful Playwright wrapper; use one instance for a multi-step session."""
    def __init__(self, headless=False, persistent=False, profile_dir=".browser-profile", browser_name="chromium"):
        self.headless, self.persistent = headless, persistent
        self.profile_dir, self.browser_name = profile_dir, browser_name
        self._pw = self.browser = self.context = self.page = None

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def start(self):
        if self.page:
            return self
        self._pw = sync_playwright().start()
        browser_type = getattr(self._pw, self.browser_name)
        if self.persistent:
            Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
            self.context = browser_type.launch_persistent_context(self.profile_dir, headless=self.headless)
            self.browser = self.context.browser
        else:
            self.browser = browser_type.launch(headless=self.headless)
            self.context = self.browser.new_context(accept_downloads=True)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(8000)
        self.context.on("page", self._on_new_page)
        return self

    def _on_new_page(self, page):
        self.page = page
        page.set_default_timeout(8000)

    def _ensure(self):
        if not self.page:
            self.start()

    def open(self, url):
        self._ensure()
        if not url.startswith(("http://", "https://", "file://")):
            raise ValueError("URL must start with http://, https://, or file://")
        self.page.goto(url, wait_until="domcontentloaded")
        return {"url": self.page.url, "title": self.page.title()}

    def inspect(self, limit=150):
        self._ensure()
        return inventory(self.page, limit)

    def click(self, by, value, name=None):
        self._ensure()
        return actions.click(self.page, by, value, name)

    def fill(self, by, value, text, name=None):
        self._ensure()
        return actions.fill(self.page, by, value, text, name)

    def select(self, by, value, option, name=None):
        self._ensure()
        return actions.select_option(self.page, by, value, option, name)

    def check(self, by, value, name=None, checked=True):
        self._ensure()
        return actions.check(self.page, by, value, name, checked)

    def screenshot(self, path="artifacts/page.png"):
        self._ensure()
        return actions.screenshot(self.page, path)

    def text(self, by, value, name=None, max_matches=5, max_chars=6000):
        """Read one element or bounded text from multiple matches.

        Reading is different from acting: multiple matches are useful for text
        extraction, while click/fill/select still require an unambiguous target.
        """
        self._ensure()
        loc = make_locator(self.page, by, value, name)
        count = loc.count()
        if count == 0:
            # A failed narrow selector should not prevent reading an article
            # when the page exposes a recognizable main-content container.
            # This fallback is read-only and is intentionally limited to common
            # semantic/content roots; action locators remain strict.
            for fallback_selector in ("main", "article", "#mw-content-text", "[role='main']"):
                fallback = self.page.locator(fallback_selector)
                fallback_count = fallback.count()
                if not fallback_count:
                    continue
                for index in range(min(fallback_count, 2)):
                    try:
                        fallback_text = (
                            fallback.nth(index).inner_text().strip()
                            if fallback_count > 1 else fallback.inner_text().strip()
                        )
                    except Exception:
                        continue
                    if fallback_text:
                        fallback_text = fallback_text[:max_chars]
                        if len(fallback_text) == max_chars:
                            fallback_text += "... [text truncated]"
                        return (
                            f"[Requested locator matched zero elements; using visible content "
                            f"from fallback {fallback_selector!r}.]\\n\\n{fallback_text}"
                        )
            raise LookupError(
                f"No elements matched read_text locator (by={by!r}, value={value!r}) "
                f"on page {self.page.title()!r} at {self.page.url!r}; no readable main-content "
                "fallback was found. Inspect the live page and choose a locator supported by current evidence."
            )

        limit = min(count, max(1, int(max_matches)))
        chunks = []
        for index in range(limit):
            try:
                text = loc.nth(index).inner_text().strip() if count > 1 else loc.inner_text().strip()
            except Exception as exc:
                # Preserve useful text from other matching elements when one
                # detached or became unreadable during extraction.
                chunks.append(f"[Match {index + 1}: {type(exc).__name__}: {exc}]")
                continue
            if text:
                chunks.append(text)

        if not chunks:
            raise ValueError(
                f"Locator matched {count} element(s), but none returned readable text. "
                "Inspect the current page and try a visible text container."
            )

        result = "\\n\\n".join(chunks)
        if count > limit:
            result += f"\\n\\n[Showing {limit} of {count} matching elements.]"
        if len(result) > max_chars:
            result = result[:max_chars] + "... [text truncated]"
        return result

    def status(self):
        self._ensure()
        return {"url": self.page.url, "title": self.page.title(), "frames": len(self.page.frames)}

    def close(self):
        try:
            if self.context:
                self.context.close()
            if self.browser and not self.persistent:
                self.browser.close()
        finally:
            if self._pw:
                self._pw.stop()
            self._pw = self.browser = self.context = self.page = None
