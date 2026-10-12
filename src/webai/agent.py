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

import re

BLOCKED=('purchase','buy now','pay now','payment','delete','remove account','send','submit','checkout','place order','transfer money','publish','confirm booking','finalize order')
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
        r"(?:below|under|less than|maximum|max(?:imum)? price(?: of)?|priced? at most)\s*(?:₹|rs\.?\s*)?([\d,]+)",
        r"(?:₹|rs\.?\s*)([\d,]+)\s*(?:or less|maximum|max|and below)",
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
    match = re.search(r"(?:under|up to|upto|less than|below)\s*(?:₹|rs\.?\s*)?([\d,]+)", target, re.I)
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

class Agent:
    """Bounded observe-plan-act-verify loop using a configurable chat model."""
    def __init__(self, browser=None, llm=None, memory=None):
        self.settings=get_settings(); self.browser=browser; self._browser_owned=False; self.llm=llm or LLMClient(); self.memory=memory or Memory(self.settings.memory_path)
    def run(self, task, url=None):
        start=time.time(); perf_start=time.perf_counter(); artifacts=[]; trace=[]; status='failed'; summary=''; owns=False; pending_action=None; intervention=None
        timings={'browser_start_seconds':0.0,'url_discovery_seconds':0.0,'navigation_seconds':0.0,'initial_observation_seconds':0.0,'planning_seconds':[],'action_seconds':[],'post_action_observation_seconds':[],'unattributed_seconds':0.0}
        try:
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
            progress.record_navigation(self.browser.page.url)
            messages=[{'role':'user','content':json.dumps({'goal':task,'task_plan':task_plan.snapshot(),'evidence_store':evidence_store.snapshot(),'observation':obs},ensure_ascii=False)}]
            failed_action_signatures = {}
            if intervention:
                status='needs_input'; summary=intervention.get('reason', 'Human intervention is required.')
            for i in range(0 if intervention else self.settings.max_steps):
                # Capturing full-page screenshots on every step is expensive and
                # wasted when vision is disabled. Keep screenshots opt-in.
                shot=None
                if self.settings.vision_enabled:
                    try:
                        shot=self.browser.screenshot(f'{self.settings.artifact_dir}/agent_step_{int(time.time())}_{i+1}.png', full_page=False)
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
                action_description = ' '.join(str(plan.get(key, '')) for key in ('text', 'value', 'name', 'option', 'target', 'target_name', 'operation', 'key'))
                mutating_actions = {'click', 'fill', 'select', 'check', 'control', 'press',
                                    'double_click', 'right_click', 'click_at', 'drag_drop', 'drag_at'}
                # Text-labelled consequential actions always require approval.
                # Vision-only coordinate/keyboard actions also require approval
                # when the user's task itself requests a consequential outcome.
                needs_approval = sensitive(action_description) or (
                    kind in {'click_at', 'drag_at', 'press'} and sensitive_task(task)
                )
                if kind in mutating_actions and needs_approval:
                    status = 'needs_approval'
                    summary = 'Approval required before this consequential action can execute.'
                    pending_action = plan
                    intervention={'type':'approval_required','title':'Approval required','reason':summary,'url':self.browser.page.url,'user_action':'Review the proposed action and explicitly approve it before execution.'}
                    break
                if kind=='navigate' and not plan.get('value','').startswith(('http://','https://')): raise ValueError('Navigation must use http(s).')
                phase=time.perf_counter(); result=self._execute_action_with_recovery(plan)
                timings['action_seconds'].append(round(time.perf_counter()-phase,3))
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
        if kind=='inspect':
            observation = self.browser.observe(180)
            return {'ok': True, 'elements': observation.get('controls', []), 'observation': observation}
        if kind=='observe': return {'ok': True, 'observation': self.browser.observe(220)}
        if kind=='status': return self.browser.status()
        if kind=='screenshot': return {'ok':True,'path':self.browser.screenshot(plan.get('path') or f'{self.settings.artifact_dir}/manual.png')}
        if kind=='navigate': return self.browser.open(plan['value'])
        if kind=='scroll':
            return self.browser.interact(
                'scroll', by=plan.get('by', 'css'), value=plan.get('value', 'down'),
                text=plan.get('text', 650), target_by=plan.get('target_by'),
                target_value=plan.get('target_value'), target_name=plan.get('target_name')
            )
        if kind=='read_text': return {'ok':True,'text':self.browser.text(plan['by'],plan['value'],plan.get('name'))}
        if kind=='click': return self.browser.interact('click', by=plan['by'], value=plan['value'], name=plan.get('name'), dialog_action=plan.get('dialog_action'), prompt_text=plan.get('prompt_text'))
        if kind=='fill': return self.browser.fill(plan['by'],plan['value'],plan['text'],plan.get('name'))
        if kind=='select': return self.browser.select(plan['by'],plan['value'],plan['option'],plan.get('name'))
        if kind=='check': return self.browser.check(plan['by'],plan['value'],plan.get('name'),bool(plan.get('checked',True)))
        if kind=='control': return self.browser.control(plan['by'],plan['value'],plan['operation'],plan.get('target'),plan.get('name'),plan.get('steps',1))
        if kind in {'click_at', 'move_at', 'drag_at'}:
            if not getattr(self.settings, 'vision_enabled', False):
                raise ValueError("Coordinate actions require WEBAI_VISION_ENABLED=true so coordinates can be grounded in a current viewport screenshot.")
            return self.browser.interact(
                kind, x=plan.get('x'), y=plan.get('y'),
                to_x=plan.get('to_x'), to_y=plan.get('to_y')
            )
        if kind in {'hover', 'double_click', 'right_click', 'focus', 'blur', 'press', 'upload', 'drag_drop', 'wait_for'}:
            return self.browser.interact(
                kind, by=plan.get('by', 'role'), value=plan.get('value', ''),
                name=plan.get('name'), text=plan.get('text'), option=plan.get('option'),
                checked=plan.get('checked', True), operation=plan.get('operation'),
                target=plan.get('target'), steps=plan.get('steps', 1), path=plan.get('path'),
                target_by=plan.get('target_by'), target_value=plan.get('target_value'),
                target_name=plan.get('target_name'), key=plan.get('key'), dialog_action=plan.get('dialog_action'), prompt_text=plan.get('prompt_text')
            )
        if kind == 'download':
            return self.browser.interact(
                'download', by=plan.get('by', 'role'), value=plan.get('value', ''),
                name=plan.get('name'), path=plan.get('path')
            )
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
