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
