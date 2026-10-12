# WebAI DOM Intelligence Engine

Drop-in Playwright module for deeper DOM traversal, candidate ranking, safe click attempts, and outcome validation.

## Important
This is an enhancement module, not a verified patch to your installed WebAI project because its exact source archive was not attached in this turn. It is designed to be integrated into the existing Playwright toolkit. Review `integration_example.py` and adapt the call site in your action layer.

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
