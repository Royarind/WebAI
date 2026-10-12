# WebAI — Evidence-driven browser interaction agent

WebAI is a local Playwright-based web agent. It combines accessible locators, DOM inventory, bounded recovery, task planning and outcome verification. The interaction engine is a shared execution layer, not a list of website-specific scripts.

## General interaction engine

The implementation in `src/webai/interaction_engine.py` exposes a unified observation and interaction API through `WebAI.observe()` and `WebAI.interact()`. Existing convenience methods remain available.

Supported interaction families:

- **Semantic controls:** click, fill, native/custom select, checkbox/radio/switch, slider and quantity controls.
- **Mouse and keyboard:** hover, double-click, right-click, focus, blur, Enter/Escape/Tab/arrows, supported modifier shortcuts, and screenshot-grounded coordinate click/move/drag.
- **Custom widgets:** comboboxes, listboxes, menu items, tabs, ARIA controls, date/calendar widgets, autocomplete and nested menus through the common locator/control workflow.
- **Composite pages:** forms and multi-step pages, accordions, tabs, carousels, table/grid rows, pagination, product variants and filters using observable controls.
- **Files:** upload through a native file input or custom file chooser, and downloads with optional save destination.
- **Dynamic content:** bounded waits, async-rendered options, page scroll and nested scroll containers.
- **Browser structure:** open shadow DOM inventory, accessible iframe traversal, popup/new-page tracking and JavaScript alert/confirm/prompt handling.
- **Visual fallback:** when `WEBAI_VISION_ENABLED=true` and the selected model supports images, the planner receives a current viewport screenshot. Coordinate actions are bounded to that viewport and require follow-up observation.

### Interaction contract and safety

1. Observe the current page, visible controls, overlays and frames.
2. Resolve a unique target; if a role is wrong, try evidence-backed accessible-role recovery.
3. Execute a single interaction without blindly repeating a potentially successful action.
4. Verify observable state changes where possible. A dispatched click/keypress is not by itself proof that the user's goal completed.
5. On ambiguity, report diagnostics and ask for clarification instead of choosing an arbitrary element.
6. JavaScript dialogs are dismissed by default; acceptance must be explicitly requested in the action.
7. WebAI's task safety guard continues to require approval for consequential actions such as purchases, sending messages, deletion and final submissions. It must not bypass CAPTCHA, MFA or access controls.

Not every website exposes the same semantics. Canvas-only widgets, inaccessible cross-origin frames, anti-bot challenges and browser/OS permission prompts may require visual support or user intervention. No engine can guarantee automation on every site; completion must be grounded in live evidence.

## Tests

Run the regression suite after installing the project and Chromium:

```powershell
python -m pip install -e ".[dev]"
python -m pip install -r requirements-test.txt
python -m playwright install chromium
python -m pytest -q
```

## What it does
- Inspects the DOM from root to descendants, including leaf elements and ancestor/sibling context.
- Searches open shadow roots and accessible frames.
- Ranks candidate elements against natural-language intent.
- Attempts candidates in confidence order with bounded retries.
- Validates outcomes using DOM state changes and optional task-specific validation.
- Produces diagnostics for failed attempts.
- Never clicks purchase/checkout/submit/destructive controls unless explicitly authorized.

## Install
From your existing WebAI project virtual environment:

```powershell
pip install playwright
python -m playwright install chromium
```

Copy `webai_dom_intelligence.py` into your package (for example `src/webai/`) and import it from the action layer.

## Example
```python
from webai_dom_intelligence import DOMIntelligence

engine = DOMIntelligence(page)
result = await engine.click_intent(
    "select Citrine Forest Green colour",
    authorized=True,
    validate=lambda: page.locator(
        '[aria-checked="true"], [aria-pressed="true"], .selected, .is-selected'
    ).count() > 0,
)
print(result)
```

The validation callback above is generic only; for a real product page, validate the specific swatch's selected state or the product image/label change. Do not use a generic selector as proof that the requested colour was selected.

## Safety model
`authorized=True` means the user authorized the requested interaction. It does not bypass the built-in guard for consequential actions. For actions involving purchase, payment, order placement, destructive changes, or form submission, set `allow_consequential=True` only when the user explicitly asked for that exact action.

## Optional local Ollama LLM provider

WebAI's LLM client can use Ollama's OpenAI-compatible chat-completions endpoint without an API key. The default provider remains unchanged, so existing OpenRouter configuration continues to work unless you explicitly switch providers.

1. Install Ollama from https://ollama.com/ and ensure the Ollama service is running.
2. Pull a model. For a 16 GB RAM CPU-only machine, start by testing a small model:

   ```powershell
   ollama pull qwen3:4b
   ollama list
   ```

3. Set these values in your existing `.env` file:

   ```dotenv
   WEBAI_LLM_PROVIDER=ollama
   WEBAI_OLLAMA_BASE_URL=http://localhost:11434/v1
   WEBAI_OLLAMA_MODEL=qwen3:4b
   WEBAI_LLM_TIMEOUT=60
   WEBAI_VISION_ENABLED=false
   ```

   You do not need to remove `WEBAI_LLM_API_KEY` or change your OpenRouter model/base URL settings. The Ollama-specific settings take precedence when `WEBAI_LLM_PROVIDER=ollama`.

4. Check the effective configuration:

   ```powershell
   webai doctor
   ```

   The doctor output should show provider `ollama`, base URL `http://localhost:11434/v1`, and model `qwen3:4b`. It never prints the API key.

5. Run WebAI as usual. If Ollama is not running or the model is missing, WebAI reports a provider-specific error. It does not silently switch providers or bypass existing action validation, safety handling, recovery or verification.

To return to the existing hosted setup, set `WEBAI_LLM_PROVIDER=openrouter` (or remove that variable) and keep your current hosted-provider configuration. Ollama uses the same action-planning schema, so local model output still passes through the existing validation.


## Human intervention and saved profile data

WebAI pauses with a structured `intervention` when it encounters a CAPTCHA/anti-bot challenge, sign-in or identity verification, explicitly required contact details, a blocking modal, a repeated failing action, a step limit, a missing user decision, or a consequential action awaiting approval. The dashboard keeps the visible browser open; complete the step yourself and use **Resume after intervention**. WebAI does not bypass CAPTCHA, MFA, or access controls.

Before planning, WebAI attempts local-only autofill for blank, visible and clearly labelled name, email, phone, address and password fields. Values are read from these optional environment variables:

```dotenv
WEBAI_PROFILE_NAME=
WEBAI_PROFILE_EMAIL=
WEBAI_PROFILE_PHONE=
WEBAI_PROFILE_ADDRESS=
WEBAI_PROFILE_PASSWORD=
```

Set only the fields you actually want WebAI to use. Keep these values in a local, untracked `.env` file or your operating system's secret manager; never commit them. Passwords are filled directly into the browser process and are **not** added to LLM prompts or WebAI run history. WebAI never overwrites an already-populated field, submits a form just because it autofilled it, or uses saved profile values for CAPTCHA/MFA/one-time-code/card-security fields. Existing signed-in browser sessions, site account details, and browser/password-manager autofill can also supply values when the site exposes them in the active browser session.

If no suitable saved value exists, WebAI asks for human intervention instead of inventing a name, phone number, email, address or password. The current implementation reads local profile values from environment variables; it does not yet integrate with a separate password vault or third-party wallet API.


## Interactive controls (Playwright)

The action layer supports verified control operations for common e-commerce widgets:

- **Range sliders:** `control` with `operation="set_value"` and a numeric `target`. It scrolls the control into view, uses Playwright mouse drag, then checks the resulting value.
- **Native dropdowns:** `operation="choose"` with the option's visible label or value.
- **Custom dropdowns:** opens the unique target and selects a unique accessible option/text match; it reports an error if the selection cannot be verified.
- **Quantity controls:** `operation="increment"` or `"decrement"` with an optional bounded `steps` count (1–20). For +/- buttons, target the quantity input so WebAI can identify nearby, labelled buttons. Numeric inputs are adjusted within their min/max bounds.

Example planner action for a price slider:

```json
{"action":"control","by":"css","value":"input[type=range]","operation":"set_value","target":1000,"name":"Maximum price"}
```

Example planner action for a quantity button:

```json
{"action":"control","by":"css","value":"#quantity","operation":"increment","steps":1,"name":"Quantity"}
```

Control actions require a unique visible target and verify the resulting state. If the page uses a custom canvas slider or an unlabeled +/- button that cannot be identified reliably, WebAI reports the failure rather than claiming success.
