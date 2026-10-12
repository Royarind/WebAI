import json, time
from urllib.parse import urlparse
from .browser import WebAI
from .config import get_settings
from .llm import LLMClient
from .memory import Memory
from .locators import overlay_inventory
from .interventions import detect_intervention, intervention_for_status
from .profile import autofill_known_profile
from .task_planning import TaskPlan, EvidenceStore, verify_deliverable
from .intent_engine import assess_intent, next_step_guidance
from .orchestration import CapabilityRegistry, ObjectiveLedger, Capability
from .connectors import LocalFileConnector, OutlookGraphConnector

import re
from .computer_use import ComputerUse

BLOCKED=('purchase','buy now','pay now','payment','delete','remove account','send email','send message','submit order','place order','transfer money','publish','confirm booking','finalize order')
NEGATION = re.compile(r"\b(?:do not|don't|dont|never|avoid|without|no need to|not to|not)\b", re.I)

def sensitive(text):
    low=text.lower()
    return any(x in low for x in BLOCKED)

def sensitive_task(text):
    """Block requested consequential actions, but allow them when explicitly prohibited.

    Split at common clause boundaries so a negation in one clause does not
    accidentally authorize a separate consequential action in another.
    """
    for clause in re.split(r"[.!?;,\n]+", text, flags=re.M):
        low = clause.lower()
        for phrase in BLOCKED:
            start = 0
            while True:
                index = low.find(phrase, start)
                if index < 0:
                    break
                # Treat a blocked phrase as prohibited only when the clause
                # does not explicitly negate it before the phrase.
                if not NEGATION.search(low[:index]):
                    return True
                start = index + len(phrase)
    return False


def _requested_price_ceiling(task):
    """Extract a simple requested price ceiling so the agent cannot silently choose a lower band."""
    text = str(task or "")
    patterns = [
        r"(?:below|under|less than|maximum|max(?:imum)? price(?: of)?|priced? at most)\s*(?:₹|rs\\.?\s*)?([\\d,]+)",
        r"(?:₹|rs\\.?\s*)([\\d,]+)\s*(?:or less|maximum|max|and below)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def _filter_price_mismatch(task, plan):
    """Reject a proposed explicit price band that is stricter than the user's ceiling."""
    ceiling = _requested_price_ceiling(task)
    if ceiling is None or plan.get("action") not in {"click", "select"}:
        return None
    target = " ".join(str(plan.get(key, "")) for key in ("value", "name", "text", "option"))
    match = re.search(r"(?:under|up to|upto|less than|below)\s*(?:₹|rs\\.?\s*)?([\\d,]+)", target, re.I)
    if not match:
        return None
    try:
        band = int(match.group(1).replace(",", ""))
    except ValueError:
        return None
    if band < ceiling:
        return {
            "requested_ceiling": ceiling,
            "proposed_ceiling": band,
            "reason": f"The proposed price filter is ₹{band}, but the user requested products below ₹{ceiling}. Do not apply this narrower filter. Find a matching price band or use the custom price range.",
        }
    return None


def _compact_elements(items, limit=24):
    """Keep actionable locator evidence while avoiding oversized DOM prompts."""
    fields = ("index", "tag", "type", "role", "name", "id", "testId",
              "placeholder", "href", "value", "checked", "disabled", "inShadowRoot", "page_index", "frame_index")
    compact = []
    for item in (items or [])[:limit]:
        if not isinstance(item, dict):
            continue
        entry = {key: item[key] for key in fields if key in item and item[key] not in ("", None)}
        for key in ("name", "id", "testId", "placeholder", "href", "value"):
            if isinstance(entry.get(key), str) and len(entry[key]) > 180:
                entry[key] = entry[key][:177] + "..."
        compact.append(entry)
    return compact


def _compact_overlays(overlays, limit=3):
    """Keep only short overlay summaries and a few actionable buttons."""
    compact = []
    for overlay in (overlays or [])[-limit:]:
        if not isinstance(overlay, dict):
            continue
        entry = {"category": overlay.get("category", "unknown")}
        if overlay.get("text"):
            entry["text"] = str(overlay["text"])[:350]
        if overlay.get("meta"):
            entry["meta"] = str(overlay["meta"])[:160]
        buttons = []
        for button in (overlay.get("buttons") or [])[:6]:
            if isinstance(button, dict):
                buttons.append({
                    key: str(button[key])[:100] if isinstance(button.get(key), str) else button[key]
                    for key in ("text", "ariaLabel", "title", "testId", "disabled")
                    if key in button and button[key] not in ("", None)
                })
        if buttons:
            entry["buttons"] = buttons
        compact.append(entry)
    return compact


class TaskProgress:
    """Small deterministic progress ledger for multi-step browser tasks."""
    def __init__(self, goal):
        self.goal = str(goal or "").strip()
        self.visited_urls = []
        self.evidence = []
        self.successful_actions = []
        self.completed_objectives = []
        self._seen_reads = set()
        self._seen_actions = set()

    def record_navigation(self, url):
        url = str(url or "")
        if url and (not self.visited_urls or self.visited_urls[-1] != url):
            self.visited_urls.append(url)
            self.visited_urls = self.visited_urls[-12:]

    def record_action(self, plan, result, url):
        signature = json.dumps({
            key: plan.get(key) for key in
            ("action", "by", "value", "name", "text", "option", "checked", "operation", "target")
        }, sort_keys=True, ensure_ascii=False)
        repeated = signature in self._seen_actions
        if result.get("ok") is not False:
            self._seen_actions.add(signature)
            self.successful_actions.append(signature)
            self.successful_actions = self.successful_actions[-16:]
            self.record_navigation(url)
            if plan.get("action") == "read_text" and str(result.get("text", "")).strip():
                read_key = (str(url), str(plan.get("by")), str(plan.get("value")))
                if read_key not in self._seen_reads:
                    self._seen_reads.add(read_key)
                    self.evidence.append({
                        "url": str(url),
                        "locator": {"by": plan.get("by"), "value": plan.get("value")},
                        "text": str(result["text"])[:2200],
                    })
                    self.evidence = self.evidence[-8:]
        return repeated

    def snapshot(self):
        return {
            "original_goal": self.goal,
            "visited_pages": list(self.visited_urls),
            "evidence_ledger": list(self.evidence),
            "successful_action_signatures": list(self.successful_actions),
            "completed_objectives": list(self.completed_objectives),
        }

    def repeated_read(self, plan, url):
        if plan.get("action") != "read_text":
            return False
        key = (str(url), str(plan.get("by")), str(plan.get("value")))
        return key in self._seen_reads


def _normalize_navigation_url(value):
    """Strip common Markdown link wrappers from model-generated navigation URLs."""
    raw = str(value or "").strip()
    markdown = re.fullmatch(r"\[([^\]]+)\]\((https?://[^)]+)\)", raw)
    if markdown:
        raw = markdown.group(2).strip()
    # Remove a single pair of surrounding angle brackets or quotes only.
    if len(raw) > 2 and raw[0] == "<" and raw[-1] == ">":
        raw = raw[1:-1].strip()
    if raw.startswith(("'", '"')) and raw[-1:] == raw[:1]:
        raw = raw[1:-1].strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Navigation URL is not a valid http(s) URL: {value!r}")
    return raw


def _compact_result(result):
    """Bound action feedback so a long extracted page text cannot flood history."""
    if not isinstance(result, dict):
        return result
    compact = dict(result)
    if isinstance(compact.get("text"), str) and len(compact["text"]) > 1800:
        compact["text"] = compact["text"][:1800] + "... [text truncated]"
    if isinstance(compact.get("elements"), list):
        compact["elements"] = _compact_elements(compact["elements"], 24)
    return compact

def _enforce_google_flights_trip_type(task, current_url, plan):
    """Deterministically convert repeated 'Round trip' clicks into a verified selection."""
    if not isinstance(plan, dict):
        return plan
    if "google.com/travel/flights" not in str(current_url or "").lower():
        return plan
    if not re.search(r"\bone[ -]way\b", str(task or ""), re.I):
        return plan
    if plan.get("action") != "click":
        return plan
    target = " ".join(str(plan.get(key) or "") for key in ("value", "name", "text", "option"))
    if not re.search(r"\bround\s*trip\b", target, re.I):
        return plan
    corrected = dict(plan)
    corrected.update({
        "action": "control",
        "by": "role",
        "value": "combobox",
        "name": "Round trip",
        "operation": "choose",
        "target": "One way",
        "reason": "Deterministic Google Flights recovery: select the requested trip type instead of clicking the trigger repeatedly.",
    })
    return corrected

class Agent:
    """Bounded observe-plan-act-verify loop using a configurable chat model."""
    def __init__(self, browser=None, llm=None, memory=None):
        self.settings=get_settings(); self.browser=browser; self._browser_owned=False; self.llm=llm or LLMClient(); self.memory=memory or Memory(self.settings.memory_path)
        self.computer = ComputerUse()

    def _run_computer_only(self, task, url=None):
        """Handle basic computer retrieval requests without launching a browser."""
        if url:
            return None
        text = str(task or "").strip()
        low = text.lower()
        has_absolute_windows_path = bool(re.search(r"[A-Za-z]:\\", text))
        is_file_read_request = any(word in low for word in ("read ", "open ", "summarize ", "summarise ", "inspect "))
        if not has_absolute_windows_path and not any(word in low for word in ("computer", "local file", "local folder", "my files", "my computer", "filesystem", "drive", "desktop")):
            return None
        try:
            if "capabilities" in low or "which drives" in low or "available drives" in low:
                data = self.computer.capabilities()
                summary = "Computer-use capabilities retrieved; access follows OS permissions."
            elif has_absolute_windows_path and is_file_read_request:
                path_match = re.search(r"""([A-Za-z]:\\[^"\r\n]*?\.[A-Za-z0-9]{1,10})""", text)
                if not path_match:
                    return {"status": "needs_input", "summary": "I detected a local file request but could not safely extract the full path. Quote the full path and retry.", "steps": [], "data": {}, "artifacts": [], "elapsed_seconds": 0, "url": None, "intervention": None}
                target_path = path_match.group(1).strip().rstrip(" .!?,;")
                self.computer._event("computer_step", message=f"Reading local file: {target_path}", action="file_read_started", path=target_path)
                data = self.computer.read(target_path)
                self.computer._event("computer_step", message=f"Read completed: {target_path}", action="file_read_complete", path=target_path)
                content = data.get("text", "")
                low_content = content.lower()
                if "pip install" in low_content or "installation" in low_content or "install" in low_content:
                    relevant = [line.strip() for line in content.splitlines() if any(term in line.lower() for term in ("install", "pip ", "python ", "requirements", "setup", "venv", "clone", "uvicorn"))]
                    data["summary"] = "Installation-related lines found in the file:\\n" + "\\n".join(relevant[:30])
                else:
                    data["summary"] = content[:3000]
                summary = f"Read local file successfully: {target_path}. The content and extracted summary are included in the result."
            elif "search" in low or "find" in low or "look for" in low:
                named_match = re.search(r'\b(?:named|called)\s+["\']?([^\s,;]+)', text, re.I)
                match = named_match or re.search(r'\b(?:for|about|containing)\s+([^.!?,;\n]+)', text, re.I)
                query = match.group(1).strip(" \"'") .rstrip(".!?") if match else ""
                if not query:
                    return None
                self.computer._event("computer_step", message="Starting live computer-use search", action="search_start", query=query)
                try:
                    live_ui = self.computer.live_search_in_explorer(query)
                except Exception as desktop_error:
                    live_ui = {"ok": False, "available": False, "reason": f"{type(desktop_error).__name__}: {desktop_error}"}
                    self.computer._event("computer_step", message=f"Live desktop interaction unavailable: {desktop_error}", action="desktop_unavailable")
                data = self.computer.search(query)
                data["live_desktop"] = live_ui
                summary = f"Filesystem search completed: {data.get('count', 0)} result(s). Live Explorer interaction: {'initiated' if live_ui.get('ok') else 'unavailable'}."
            else:
                return None
            return {"status": "completed", "summary": summary, "steps": [{"step": 1, "plan": {"action": "computer_use"}, "result": data}], "data": {"computer": data}, "artifacts": [], "elapsed_seconds": 0, "url": None, "intervention": None}
        except Exception as exc:
            return {"status": "failed", "summary": f"Computer-use operation failed: {type(exc).__name__}: {exc}", "steps": [], "data": {}, "artifacts": [], "elapsed_seconds": 0, "url": None, "intervention": None}

    def run(self, task, url=None):
        start=time.time(); perf_start=time.perf_counter(); artifacts=[]; trace=[]; status='failed'; summary=''; owns=False; pending_action=None; intervention=None
        timings={'browser_start_seconds':0.0,'url_discovery_seconds':0.0,'navigation_seconds':0.0,'initial_observation_seconds':0.0,'planning_seconds':[],'action_seconds':[],'post_action_observation_seconds':[],'unattributed_seconds':0.0}
        try:
            # Route dedicated computer-use tasks before browser/connector setup.
            computer_result = self._run_computer_only(task, url=url)
            if computer_result is not None:
                return computer_result
            # Route pure local-file and Outlook retrieval tasks directly to their
            # read-only connectors instead of opening an unrelated website first.
            connector_result = self._run_connector_only(task, url=url)
            if connector_result is not None:
                status = connector_result["status"]
                summary = connector_result["summary"]
                return connector_result
            owns=self.browser is None
            if owns:
                phase=time.perf_counter()
                self.browser=WebAI(headless=self.settings.headless)
                self.browser.start()
                self._browser_owned=True
                timings['browser_start_seconds']=round(time.perf_counter()-phase,3)
            if url:
                phase=time.perf_counter(); opened=self.browser.open(url)
                timings['navigation_seconds']=round(time.perf_counter()-phase,3)
            elif not owns and self.browser.page:
                phase=time.perf_counter(); opened=self.browser.status()
                timings['navigation_seconds']=round(time.perf_counter()-phase,3)
            else:
                # Resolve the starting site only when no URL or open page exists.
                phase=time.perf_counter(); url=self.llm.resolve_start_url(task)
                timings['url_discovery_seconds']=round(time.perf_counter()-phase,3)
                parsed=urlparse(url)
                if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                    raise ValueError('Automatic website discovery did not return a valid http(s) URL. Provide a URL or clarify the intended website.')
                phase=time.perf_counter(); opened=self.browser.open(url)
                timings['navigation_seconds']=round(time.perf_counter()-phase,3)
            domain=urlparse(self.browser.page.url).netloc
            # Use locally configured profile data and existing browser autofill before asking the model.
            # Secrets are filled in the browser process and are never placed in the LLM prompt or run history.
            profile_filled=autofill_known_profile(self.browser.page)
            phase=time.perf_counter()
            # The first planner call must fit small local-model context windows.
            # History and domain notes are useful later, but not worth bloating the
            # initial prompt; the current goal and visible controls are sufficient.
            obs={
                'task':task,
                'page':opened,
                'elements':_compact_elements(self.browser.inspect(24), 24),
                'overlays':_compact_overlays(overlay_inventory(self.browser.page), 3),
            }
            timings['initial_observation_seconds']=round(time.perf_counter()-phase,3)
            intervention=detect_intervention(self.browser.page, task=task, overlays=obs.get('overlays'))
            if intervention and intervention.get('type') == 'contact_input_required' and {'phone','email'}.intersection(profile_filled):
                intervention=None
            # Initialize deterministic planning and evidence state before building
            # the initial model prompt; the prompt includes both snapshots.
            progress = TaskProgress(task)
            task_plan = TaskPlan(task)
            evidence_store = EvidenceStore()
            capability_registry = CapabilityRegistry()
            self.local_files = LocalFileConnector()
            self.outlook = OutlookGraphConnector(timeout=self.settings.timeout)
            # Keep the ComputerUse instance created in __init__. The dashboard
            # attaches its event_sink there; replacing it here silently disables
            # live computer/browser activity streaming.
            if self.local_files.available:
                capability_registry.register(Capability("local_files", ("files", "office"), True, "read_only_search", "Search and read text files under configured roots."))
            if self.outlook.available:
                capability_registry.register(Capability("outlook", ("email",), True, "microsoft_graph_read_only", "Search Outlook messages via Microsoft Graph.", requires_approval=False))
            available_domains = sorted({domain for item in capability_registry.snapshot()["available"] for domain in item["domains"]})
            intent_model = assess_intent(task, available_capabilities=available_domains)
            objective_ledger = ObjectiveLedger(intent_model.get("objectives", []))
            progress.record_navigation(self.browser.page.url)
            messages=[{'role':'user','content':json.dumps({'goal':task,'intent_model':intent_model,'capabilities':capability_registry.for_domains(intent_model.get('likely_tool_domains', [])),'objective_ledger':objective_ledger.snapshot(),'next_step_guidance':next_step_guidance(intent_model, observation={'url':self.browser.page.url, 'title':self.browser.page.title()}),'task_plan':task_plan.snapshot(),'evidence_store':evidence_store.snapshot(),'observation':obs},ensure_ascii=False)}]
            failed_action_signatures = {}
            if intervention:
                status='needs_input'; summary=intervention.get('reason', 'Human intervention is required.')
            for i in range(0 if intervention else self.settings.max_steps):
                # Capturing full-page screenshots on every step is expensive and
                # wasted when vision is disabled. Keep screenshots opt-in.
                shot=None
                if self.settings.vision_enabled:
                    try:
                        shot=self.browser.screenshot(f'{self.settings.artifact_dir}/agent_step_{int(time.time())}_{i+1}.png')
                        artifacts.append(shot)
                    except Exception:
                        pass
                phase=time.perf_counter()
                try:
                    plan=self.llm.next_action(messages,shot)
                except RuntimeError as planning_error:
                    timings['planning_seconds'].append(round(time.perf_counter()-phase,3))
                    detail = str(planning_error)
                    if 'in-flight request budget exhausted' in detail.lower() or 'in_flight_budget_exhausted' in detail.lower():
                        summary = (
                            'OpenRouter temporarily refused the request because its in-flight request budget is exhausted. '
                            'No duplicate retry was started. Wait for the provider Retry-After interval (120 seconds in this report), '
                            'then resume the existing browser session; check OpenRouter credits if this keeps happening.'
                        )
                        status = 'needs_input'
                        intervention = {
                            'type': 'provider_budget_exhausted',
                            'title': 'OpenRouter request budget temporarily exhausted',
                            'reason': summary,
                            'url': self.browser.page.url,
                            'user_action': 'Wait at least the Retry-After interval, then resume this task once. Do not launch duplicate runs.',
                        }
                        break
                    raise
                except (ValueError, json.JSONDecodeError) as planning_error:
                    timings['planning_seconds'].append(round(time.perf_counter()-phase,3))
                    summary=f'WebAI could not produce a valid next action after correction attempts: {planning_error}'
                    status='needs_input'
                    intervention={'type':'agent_stuck','title':'Agent needs help choosing its next action','reason':summary[:300],'url':self.browser.page.url,'user_action':'The browser is still open. You can complete the visible step manually, then click Resume, or simplify the task.'}
                    break
                timings['planning_seconds'].append(round(time.perf_counter()-phase,3))
                trace.append({'step':i+1,'plan':plan})
                # Apply only evidence-referenced objective updates proposed by the planner.
                # The ledger rejects unsupported completions and unmet dependencies.
                for update in plan.get('objective_updates', []) if isinstance(plan.get('objective_updates'), list) else []:
                    if not isinstance(update, dict):
                        continue
                    try:
                        objective_ledger.update(
                            str(update.get('id', '')),
                            str(update.get('status', '')),
                            evidence_ids=update.get('evidence_ids'),
                            blocker=update.get('blocker'),
                        )
                    except (KeyError, ValueError):
                        continue
                # Do not trust the model to obey the one-way dropdown rule.
                # Normalize a repeated click on "Round trip" into a verified
                # choose operation before computing loop signatures or execution.
                plan = _enforce_google_flights_trip_type(task, self.browser.page.url, plan)
                trace[-1]['plan'] = plan
                kind=plan['action']
                if kind == 'navigate':
                    try:
                        plan['value'] = _normalize_navigation_url(plan.get('value', ''))
                    except ValueError as invalid_url:
                        messages.append({'role':'user','content':json.dumps({
                            'instruction':'The proposed navigation URL was invalid. Do not repeat it. Choose a clean, absolute http(s) URL grounded in the task or current page evidence, or ask the user.',
                            'invalid_url':str(invalid_url),
                            'visited_pages':progress.visited_urls[-8:],
                        },ensure_ascii=False)})
                        continue
                signature = json.dumps({key: plan.get(key) for key in ('action','by','value','name','text','option','checked')}, sort_keys=True, ensure_ascii=False)
                # Guard against the observed failure mode: repeatedly reading the same
                # page or navigating back and forth without collecting new evidence.
                if kind == 'read_text' and progress.repeated_read(plan, self.browser.page.url):
                    messages.append({'role':'user','content':json.dumps({
                        'instruction':'LOOP GUARD: this exact read_text locator has already produced evidence on this URL. Do not execute it again. Use the existing evidence_ledger, choose a different official source or a different locator that answers a missing objective, or finish if the requirements are already satisfied.',
                        'task_plan':task_plan.snapshot(),
                        'evidence_store':evidence_store.snapshot()[-8:],
                        'task_progress':progress.snapshot(),
                        'blocked_action':plan,
                    },ensure_ascii=False)})
                    continue
                if kind == 'navigate':
                    target_url = str(plan.get('value', ''))
                    current_url = str(self.browser.page.url)
                    if target_url.rstrip('/') == current_url.rstrip('/'):
                        messages.append({'role':'user','content':json.dumps({
                            'instruction':'LOOP GUARD: this navigation targets the current URL and will not advance the task. Do not repeat it; use current-page evidence or choose another source.',
                            'task_progress':progress.snapshot(),
                            'blocked_action':plan,
                        },ensure_ascii=False)})
                        continue
                if kind=='finish':
                    deliverable_check = verify_deliverable(task_plan, evidence_store, plan)
                    if not deliverable_check.get('verified'):
                        messages.append({'role':'user','content':json.dumps({
                            'instruction':'Do not finish yet: the independent deliverable verifier found missing research evidence. Continue with a different official source or collect the missing deliverable. Do not fabricate evidence.',
                            'deliverable_verification':deliverable_check,
                            'task_plan':task_plan.snapshot(),
                            'evidence_store':evidence_store.snapshot()[-8:],
                        },ensure_ascii=False)})
                        continue
                    status, summary = self._finish_status(plan, page=self.browser.page)
                    if status == 'completed':
                        summary += ' Deliverable checks passed: ' + ', '.join(
                            item['check'] for item in deliverable_check.get('checks',[]) if item.get('passed')
                        ) + '.'
                    break
                if kind=='ask_user':
                    status='needs_input'; summary=plan.get('summary') or plan.get('reason') or 'The agent needs clarification.'
                    intervention=detect_intervention(self.browser.page, task=task, overlays=overlay_inventory(self.browser.page), reason=summary) or {'type':'user_input_required','title':'WebAI needs your input','reason':summary[:300],'url':self.browser.page.url,'user_action':'Provide the missing information in the browser or clarify the task, then resume.'}
                    break
                mismatch = _filter_price_mismatch(task, plan)
                if mismatch:
                    messages.append({'role':'assistant','content':json.dumps(plan,ensure_ascii=False)})
                    messages.append({'role':'user','content':json.dumps({'instruction':mismatch['reason'],'price_filter_guard':mismatch,'updated_observation':{'url':self.browser.page.url,'title':self.browser.page.title(),'elements':_compact_elements(self.browser.inspect(30),30),'overlays':_compact_overlays(overlay_inventory(self.browser.page),3)}} ,ensure_ascii=False)})
                    if len(messages) > 5:
                        messages = [messages[0]] + messages[-4:]
                    continue
                # Consequential actions are not permanently blocked. Pause before
                # execution and return the exact proposed action for explicit approval.
                action_description = ' '.join(str(plan.get(key, '')) for key in ('text', 'value', 'name', 'option'))
                if kind in {'click', 'fill', 'select', 'check'} and sensitive(action_description):
                    status = 'needs_approval'
                    summary = 'Approval required before this consequential action can execute.'
                    pending_action = plan
                    intervention={'type':'approval_required','title':'Approval required','reason':summary,'url':self.browser.page.url,'user_action':'Review the proposed action and explicitly approve it before execution.'}
                    break
                if kind=='navigate' and not plan.get('value','').startswith(('http://','https://')): raise ValueError('Navigation must use http(s).')
                self.computer._event("browser_action_started", message=f"Browser action: {kind} — {str(plan.get('name') or plan.get('value') or plan.get('text') or '')[:100]}", action=kind, url=self.browser.page.url, plan={k: plan.get(k) for k in ("action", "by", "value", "name", "option", "operation") if k in plan})
                phase=time.perf_counter(); result=self._execute_action_with_recovery(plan)
                timings['action_seconds'].append(round(time.perf_counter()-phase,3))
                self.computer._event("browser_action_result", message=f"Browser action {'succeeded' if result.get('ok') is not False else 'failed'}: {kind}", action=kind, ok=result.get("ok") is not False, result_summary=str(result.get("error") or result.get("text") or "verified")[:220], url=self.browser.page.url)
                if result.get('ok') is False:
                    failed_action_signatures[signature] = failed_action_signatures.get(signature, 0) + 1
                    if failed_action_signatures[signature] >= 2:
                        result['loop_guard'] = True
                        result['recovery_hint'] = 'This exact action has failed repeatedly. Stop retrying it. Inspect candidate counts and visible/enabled state, choose a genuinely different evidence-based strategy, or ask the user for help.'
                else:
                    failed_action_signatures.pop(signature, None)
                if kind=='screenshot' and result.get('path'): artifacts.append(result['path'])
                if result.get('ok') is not False:
                    progress.record_action(plan, result, self.browser.page.url)
                    if kind == 'read_text' and isinstance(result.get('text'), str):
                        evidence_store.add(
                            url=self.browser.page.url,
                            locator={'by':plan.get('by'),'value':plan.get('value')},
                            text=result.get('text',''),
                        )
                    if kind in {'read_text', 'local_search', 'local_read', 'outlook_search'} and result.get('ok') is not False:
                        registered = objective_ledger.snapshot().get('evidence', {})
                        evidence_id = f"evidence_{len(registered) + 1}"
                        evidence_record = {
                            'action': kind,
                            'url': self.browser.page.url if kind == 'read_text' else None,
                            'query': plan.get('query') or plan.get('text') or plan.get('value'),
                            'path': result.get('path'),
                            'result': _compact_result(result),
                        }
                        objective_ledger.add_evidence(evidence_id, evidence_record)
                post_profile_filled=autofill_known_profile(self.browser.page)
                phase=time.perf_counter()
                compact_result=_compact_result(result)
                observation={
                    'url':self.browser.page.url,
                    'title':self.browser.page.title(),
                    'result':compact_result,
                    'elements':_compact_elements(self.browser.inspect(30), 30),
                    'overlays':_compact_overlays(overlay_inventory(self.browser.page), 3),
                }
                timings['post_action_observation_seconds'].append(round(time.perf_counter()-phase,3))
                detected=detect_intervention(self.browser.page, task=task, overlays=observation.get('overlays'))
                if detected and detected.get('type') == 'contact_input_required':
                    if {'phone','email'}.intersection(post_profile_filled): detected=None
                if detected:
                    intervention=detected; status='needs_input'; summary=detected.get('reason','Human intervention is required.')
                    break
                messages.append({'role':'assistant','content':json.dumps(plan,ensure_ascii=False)})
                messages.append({'role':'user','content':json.dumps({
                    'execution_result':compact_result,
                    'updated_observation':observation,
                    'task_progress':progress.snapshot(),
                    'intent_model':intent_model,
                    'capabilities':capability_registry.for_domains(intent_model.get('likely_tool_domains', [])),
                    'objective_ledger':objective_ledger.snapshot(),
                    'planner_contract':(
                        'Return objective_updates as a list when progress changes. Each update must use a real objective id from objective_ledger. '
                        'Statuses are pending, in_progress, blocked, completed. For completed, provide evidence_ids already present in objective_ledger.evidence. '
                        'Never invent evidence IDs. Do not mark an objective complete merely because an action ran; require evidence that its outcome was achieved.'
                    ),
                    'next_step_guidance':next_step_guidance(
                        intent_model,
                        observation={'url':self.browser.page.url, 'title':self.browser.page.title(), 'elements':observation.get('elements', [])},
                        progress=progress.snapshot(),
                        last_result=compact_result,
                    ),
                    'instruction':(
                        'Update the task plan mentally against the original goal. Preserve extracted facts in the evidence ledger. '
                        'Do not revisit a URL or repeat a successful action unless you state a specific missing fact that requires it. '
                        'Choose the next action that advances an incomplete objective. When all requested fields have evidence, produce the final comparison with source URLs and explicitly mark anything unverified. '
                        'If the current step did not add evidence or complete an objective, change strategy instead of repeating it.'
                    )
                },ensure_ascii=False)})
                # Keep the original goal plus only the latest interaction context.
                # Unbounded DOM snapshots inflate every OpenRouter request.
                if len(messages) > 5:
                    messages = [messages[0]] + messages[-4:]
                if result.get('ok') is False:
                    if result.get('loop_guard'):
                        status='needs_input'
                        summary='Stopped a repeated failing action to prevent an automation loop. The locator needs a different evidence-based strategy.'
                        intervention=detect_intervention(self.browser.page, task=task, overlays=observation.get('overlays'), reason=summary, repeat_count=2)
                        break
                    messages.append({'role':'user','content':json.dumps({'instruction':'The action failed. Do not repeat the same action or merely change locator syntax without new evidence. Use the error details and candidate metadata to select a different strategy, inspect once, or ask the user for help.','action_error':result},ensure_ascii=False)})
            else:
                if not intervention:
                    status='step_limit'; summary=f'Stopped at configured limit ({self.settings.max_steps} steps).'
                    intervention=intervention_for_status(status, page=self.browser.page, summary=summary, overlays=obs.get('overlays'))
            timings['unattributed_seconds']=round(max(0.0,time.perf_counter()-perf_start-timings['browser_start_seconds']-timings['url_discovery_seconds']-timings['navigation_seconds']-timings['initial_observation_seconds']-sum(timings['planning_seconds'])-sum(timings['action_seconds'])-sum(timings['post_action_observation_seconds'])),3)
            report={'status':status,'summary':summary,'steps':trace,'artifacts':artifacts,'elapsed_seconds':round(time.time()-start,2),'url':self.browser.page.url if self.browser and self.browser.page else None,'timings_seconds':timings,'pending_action':pending_action,'intervention':intervention}
            if status=='completed': self.memory.add_note(domain,summary,{'task':task,'steps':len(trace)})
            return report
        except Exception as e:
            summary=f'{type(e).__name__}: {e}'
            try:
                if self.browser and self.browser.page:
                    p=self.browser.screenshot(f'{self.settings.artifact_dir}/error_{int(time.time())}.png'); artifacts.append(p)
            except Exception: pass
            timings['unattributed_seconds']=round(max(0.0,time.perf_counter()-perf_start-timings['browser_start_seconds']-timings['url_discovery_seconds']-timings['navigation_seconds']-timings['initial_observation_seconds']-sum(timings['planning_seconds'])-sum(timings['action_seconds'])-sum(timings['post_action_observation_seconds'])),3)
            return {'status':'failed','summary':summary,'steps':trace,'artifacts':artifacts,'elapsed_seconds':round(time.time()-start,2),'timings_seconds':timings,'intervention':({'type':'browser_blocked','title':'Browser or agent error','reason':summary[:300],'user_action':'Check the browser and error details before retrying.'} if self.browser is None or self.browser.page is None else None)}
        finally:
            try: self.memory.add_run(task,status,summary,artifacts)
            except Exception: pass
            if self._browser_owned and self.browser and status not in {'needs_input', 'needs_approval', 'step_limit'}:
                try: self.browser.close()
                finally:
                    self.browser=None
                    self._browser_owned=False
    @staticmethod
    def _finish_status(plan, page=None):
        """Ground a finish claim against the live page before reporting completion."""
        from .verification import verify_finish_evidence

        summary = plan.get('summary') or 'Task finished.'
        evidence = str(plan.get('verification_evidence') or '').strip()
        verifier = str(plan.get('verification_type') or '').strip()
        target = str(plan.get('verification_target') or '').strip()
        if verifier and target:
            if page is None:
                return (
                    'completed_unverified',
                    f'{summary} Task-specific verification was requested, but no live page was available.'
                )
            from .task_verifiers import verify_task_outcome
            result = verify_task_outcome(page, verifier, target)
            if result.get('verified'):
                return 'completed', summary
            reason = result.get('reason') or 'The task-specific verifier did not find the requested state.'
            return ('completed_unverified', f'{summary} Task-specific verification was inconclusive: {reason}')
        if plan.get('verified') is not True or not evidence:
            return (
                'completed_unverified',
                f'{summary} The agent did not provide explicit verification evidence, so completion remains unverified.'
            )
        if page is None:
            return (
                'completed_unverified',
                f'{summary} Completion was not verified because no live page was available.'
            )
        result = verify_finish_evidence(page, evidence)
        if result.get('verified'):
            return 'completed', summary
        reason = result.get('reason', 'Evidence did not match the live page state.')
        return (
            'completed_unverified',
            f'{summary} Live-page verification was inconclusive: {reason}'
        )

    def _run_connector_only(self, task, *, url=None):
        """Execute clearly app-specific retrieval tasks without launching a browser."""
        if url or (self.browser is not None and self.browser.page is not None):
            return None
        low = task.lower()
        browser_requested = any(term in low for term in ("website", "web page", "webpage", "browser", "online search", "open the site"))
        if browser_requested:
            return None

        local_requested = any(term in low for term in ("local file", "local files", "my files", "my documents", "local documents", "desktop files", "my desktop", "search my computer", "folder", "file on my computer", "documents on my computer"))
        outlook_requested = any(term in low for term in ("outlook", "inbox", "my emails", "my email", "email messages", "mailbox"))
        if not local_requested and not outlook_requested:
            return None

        self.local_files = LocalFileConnector()
        self.outlook = OutlookGraphConnector(timeout=self.settings.timeout)
        results = {}
        if local_requested:
            path_match = re.search(r"""([A-Za-z]:\\[^"\r\n]*?\.[A-Za-z0-9]{1,10})""", task)
            if not self.local_files.available:
                results["local_files"] = {"ok": False, "error": "Local file search is not configured. Set WEBAI_FILE_ROOTS to permitted folders, separated by semicolons on Windows."}
            elif path_match:
                results["local_files"] = self.local_files.read(path_match.group(1).strip())
            else:
                query_match = re.search(r"\b(?:for|about|containing|related to|regarding|named|called)\s+(.+)$", task, re.I)
                query = query_match.group(1).strip(" .!?\\\"'") if query_match else re.sub(
                    r"\b(search|find|locate|look for|in|my|local|files?|folders?|documents?|on my computer|on my desktop|please)\b",
                    " ", task, flags=re.I)
                query = re.sub(r"\s+", " ", query).strip(" .!?")
                results["local_files"] = self.local_files.search(query or task, limit=10)

        if outlook_requested:
            unread_only = any(term in low for term in ("unread", "not read"))
            broad_briefing = any(term in low for term in ("summarize", "summary", "catch me up", "all relevant", "recent emails", "latest emails", "inbox"))
            if not self.outlook.available:
                results["outlook"] = {"ok": False, "error": "Outlook is not configured. Set WEBAI_OUTLOOK_ACCESS_TOKEN to a Microsoft Graph access token with Mail.Read permission."}
            elif broad_briefing:
                results["outlook"] = self.outlook.list_recent_messages(limit=15, unread_only=unread_only)
            else:
                query_match = re.search(r"\b(?:for|about|containing|related to|regarding)\s+(.+)$", task, re.I)
                query = query_match.group(1).strip(" .!?\\\"'") if query_match else ""
                if query:
                    results["outlook"] = self.outlook.search_messages(query, limit=15, unread_only=unread_only)
                else:
                    results["outlook"] = self.outlook.list_recent_messages(limit=15, unread_only=unread_only)

        failures = [name for name, result in results.items() if result.get("ok") is not True]
        counts = {name: result.get("count", len(result.get("results", [])) if isinstance(result.get("results"), list) else 0)
                  for name, result in results.items()}
        if failures:
            status = "needs_input"
            summary = "Connector setup or access is needed: " + "; ".join(
                f"{name}: {results[name].get('error', 'connector unavailable')}" for name in failures
            )
        else:
            status = "completed"
            summary = "Read-only retrieval completed. " + "; ".join(
                f"{name}: {counts[name]} result(s)" for name in results
            ) + ". Review the returned data before taking any consequential action."
        return {
            "status": status,
            "summary": summary,
            "steps": [{"step": i + 1, "plan": {"action": name}, "result": result}
                      for i, (name, result) in enumerate(results.items())],
            "data": results,
            "artifacts": [],
            "elapsed_seconds": 0,
            "url": None,
            "intervention": ({"type": "connector_configuration", "title": "Connector setup required",
                              "reason": summary, "user_action": "Configure the connector and rerun the request."}
                             if failures else None),
        }

    def _execute_action_with_recovery(self, plan):
        """Convert an individual browser-action exception into planner feedback.

        This lets the bounded agent loop re-observe the page instead of aborting the
        entire task on a transient locator timeout. It does not retry the action.
        """
        try:
            return self._act(plan)
        except Exception as action_error:
            return {
                'ok': False,
                'action': plan.get('action'),
                'error_type': type(action_error).__name__,
                'error': str(action_error),
                'recovery_hint': (
                    'Re-inspect the current page and verify the intended outcome using '
                    'alternative observable evidence. Do not repeat a consequential '
                    'action blindly.'
                ),
            }

    def _act(self, plan):
        kind=plan['action']; page=self.browser.page
        if kind == 'local_search':
            return self.local_files.search(plan.get('query') or plan.get('text') or plan.get('value', ''),
                                           limit=plan.get('limit', 10), extensions=plan.get('extensions'))
        if kind == 'local_read':
            return self.local_files.read(plan.get('path') or plan.get('value', ''),
                                         max_chars=plan.get('max_chars', 12000))
        if kind == 'outlook_search':
            return self.outlook.search_messages(plan.get('query') or plan.get('text') or plan.get('value', ''),
                                                limit=plan.get('limit', 10),
                                                unread_only=bool(plan.get('unread_only', False)))
        if kind == 'computer_search': return self.computer.search(plan.get('query') or plan.get('text') or plan.get('value', ''), limit=plan.get('limit', 30))
        if kind == 'computer_read': return self.computer.read(plan.get('path') or plan.get('value', ''), max_chars=plan.get('max_chars', 20000))
        if kind == 'computer_copy': return self.computer.copy(plan['source'], plan['destination'])
        if kind == 'computer_move': return self.computer.move(plan['source'], plan['destination'])
        if kind == 'computer_create_directory': return self.computer.create_directory(plan.get('path') or plan.get('value', ''))
        if kind == 'computer_create_text_file': return self.computer.create_text_file(plan.get('path', ''), plan.get('text', ''), overwrite=bool(plan.get('overwrite', False)))
        if kind == 'computer_delete': return self.computer.request_delete(plan.get('path') or plan.get('value', ''))
        if kind == 'desktop_screenshot': return self.computer.screenshot(plan.get('path'))
        if kind == 'desktop_action': return self.computer.desktop_action(plan.get('operation', ''), **(plan.get('arguments') or {}))
        if kind=='inspect': return {'ok':True,'elements':self.browser.inspect(180)}
        if kind=='status': return self.browser.status()
        if kind=='screenshot': return {'ok':True,'path':self.browser.screenshot(plan.get('path') or f'{self.settings.artifact_dir}/manual.png')}
        if kind=='navigate': return self.browser.open(plan['value'])
        if kind=='scroll': return self.browser.scroll(plan.get('value','down'), plan.get('text',650))
        if kind=='read_text': return {'ok':True,'text':self.browser.text(plan['by'],plan['value'],plan.get('name'))}
        if kind=='click': return self.browser.click(plan['by'],plan['value'],plan.get('name'))
        if kind=='fill': return self.browser.fill(plan['by'],plan['value'],plan['text'],plan.get('name'))
        if kind=='select': return self.browser.select(plan['by'],plan['value'],plan['option'],plan.get('name'))
        if kind=='check': return self.browser.check(plan['by'],plan['value'],plan.get('name'),bool(plan.get('checked',True)))
        if kind=='control': return self.browser.control(plan['by'],plan['value'],plan['operation'],plan.get('target'),plan.get('name'),plan.get('steps',1))
        raise ValueError('Unsupported action: '+kind)
    def chat(self,url=None,persistent=True):
        # Keep the same browser across user prompts; each request gets a fresh bounded agent loop.
        with WebAI(headless=self.settings.headless,persistent=persistent) as browser:
            self.browser=browser
            if url: browser.open(url)
            print('WebAI chat ready. Commands: help, status, exit. Each task is sent to the configured LLM.')
            while True:
                try: task=input('webai> ').strip()
                except (EOFError,KeyboardInterrupt): break
                if task.lower() in {'exit','quit','q'}: break
                if not task: continue
                if task.lower()=='help':
                    print('Examples: inspect the page; click the button named Click me; fill Email with "test@example.com"; take a screenshot.')
                    continue
                if task.lower()=='status': print(json.dumps(browser.status(),indent=2)); continue
                result=self.run(task)
                print(json.dumps(result,indent=2,ensure_ascii=False))
            self.browser=None
