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
