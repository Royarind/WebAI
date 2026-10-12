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


## Cross-application retrieval (initial connectors)

WebAI can run read-only local-file and Outlook retrieval tasks without opening an unrelated website. The LLM/browser workflow can also select these tools during a broader browser task.

### Local files

Set `WEBAI_FILE_ROOTS` to folders WebAI is allowed to search. Only these roots are accessible; file access is read-only.

PowerShell example:

```powershell
$env:WEBAI_FILE_ROOTS = "D:\\Work;D:\\Documents"
python -m webai
```

Supported text formats: TXT, Markdown, RST, LOG, JSON, CSV, YAML, XML and HTML. Hidden/system folders such as `.git`, virtual environments, `node_modules`, Windows and Program Files are skipped. Large files are skipped or truncated. File paths outside the configured roots are rejected.

Example tasks:
- `Search my local files for the Leon release plan`
- `Find documents on my computer about delivery governance`
- `Read file "D:\\Work\\notes.md"`

### Outlook email retrieval

The Outlook connector uses Microsoft Graph and is read-only. Configure `WEBAI_OUTLOOK_ACCESS_TOKEN` with a valid Microsoft Graph access token that has delegated `Mail.Read` permission and appropriate consent. WebAI does not ask for or store your Microsoft password and does not send messages.

PowerShell example:

```powershell
$env:WEBAI_OUTLOOK_ACCESS_TOKEN = "<short-lived Microsoft Graph access token>"
python -m webai
```

Example tasks:
- `Summarize my Outlook inbox` (returns the latest message subjects, senders, timestamps and previews for review)
- `Find Outlook emails about the Leon release`
- `Find unread Outlook emails about budget`

Tokens expire; refresh the token through your approved Microsoft identity flow when Graph returns 401. Do not paste tokens into chat, commit them, or place them in source files. For a durable deployment, use MSAL interactive/device-code authentication and an OS credential store rather than manually setting a token.

### Current integration boundaries

- Local files: read/search supported text formats within explicit roots; no writes or deletion.
- Outlook: recent-message listing and message search via Microsoft Graph; no sending, moving, deleting, or calendar writes.
- WhatsApp: can be approached through the existing visible browser workflow when WhatsApp Web is already authorized, but there is not yet a dedicated WhatsApp API connector.
- Native Windows desktop control and Office document creation are not yet implemented as dedicated connectors.


## Separate computer-use toolkit (Windows/macOS/Linux)

The computer-use layer lives in `src/webai/computer_use.py` and is deliberately separate from the Playwright browser adapter. It combines native filesystem operations with optional PyAutoGUI visual control. The agent action schema exposes these computer tools separately from browser actions.

Install the optional visual-control dependency in the project virtual environment:

```powershell
pip install -e ".[computer-use]"
```

Configure `WEBAI_FILE_ROOTS` to the specific folders the agent is permitted to access. File search/read, copy, move, directory creation and text-file creation are confined to these roots. Copy/move will not overwrite an existing destination. Delete requests create an approval token and do **not** delete anything until the caller explicitly approves that exact request. Keep the configured roots narrow; do not grant the whole system drive by default.

The optional visual-control layer currently provides screenshot, click, pointer move, key press, hotkey and type primitives through PyAutoGUI. It is coordinate-based, so the agent must inspect a screenshot and verify the result; it is not equivalent to native accessibility-tree support. macOS may require Accessibility and Screen Recording permissions. Linux desktop sessions may require a supported graphical session and display backend.

**Implementation boundary:** this is the initial computer-use toolkit and action-layer integration, not yet a complete OS-control product. The dashboard does not yet stream computer-use events live, provide an approval dialog for deletion, or guarantee that every pure desktop task bypasses browser initialization. Office document formats, clipboard APIs, native app discovery/accessibility, calendar integration, and end-to-end approval UX remain future work. Do not assume those capabilities are active merely because the tool primitives exist.
