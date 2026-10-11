import json, time
from urllib.parse import urlparse
from .browser import WebAI
from .config import get_settings
from .llm import LLMClient
from .memory import Memory
from .locators import overlay_inventory

import re

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
        self.settings=get_settings(); self.browser=browser; self.llm=llm or LLMClient(); self.memory=memory or Memory(self.settings.memory_path)
    def run(self, task, url=None):
        start=time.time(); perf_start=time.perf_counter(); artifacts=[]; trace=[]; status='failed'; summary=''; owns=False; pending_action=None
        timings={'browser_start_seconds':0.0,'url_discovery_seconds':0.0,'navigation_seconds':0.0,'initial_observation_seconds':0.0,'planning_seconds':[],'action_seconds':[],'post_action_observation_seconds':[],'unattributed_seconds':0.0}
        try:
            owns=self.browser is None
            if owns:
                phase=time.perf_counter()
                self.browser=WebAI(headless=self.settings.headless)
                self.browser.start()
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
            messages=[{'role':'user','content':json.dumps({'goal':task,'observation':obs},ensure_ascii=False)}]
            failed_action_signatures = {}
            for i in range(self.settings.max_steps):
                # Capturing full-page screenshots on every step is expensive and
                # wasted when vision is disabled. Keep screenshots opt-in.
                shot=None
                if self.settings.vision_enabled:
                    try:
                        shot=self.browser.screenshot(f'{self.settings.artifact_dir}/agent_step_{int(time.time())}_{i+1}.png')
                        artifacts.append(shot)
                    except Exception:
                        pass
                phase=time.perf_counter(); plan=self.llm.next_action(messages,shot)
                timings['planning_seconds'].append(round(time.perf_counter()-phase,3))
                trace.append({'step':i+1,'plan':plan})
                kind=plan['action']
                signature = json.dumps({key: plan.get(key) for key in ('action','by','value','name','text','option','checked')}, sort_keys=True, ensure_ascii=False)
                if kind=='finish':
                    status, summary = self._finish_status(plan, page=self.browser.page)
                    break
                if kind=='ask_user':
                    status='needs_input'; summary=plan.get('summary') or 'The agent needs clarification.'; break
                # Consequential actions are not permanently blocked. Pause before
                # execution and return the exact proposed action for explicit approval.
                action_description = ' '.join(str(plan.get(key, '')) for key in ('text', 'value', 'name', 'option'))
                if kind in {'click', 'fill', 'select', 'check'} and sensitive(action_description):
                    status = 'needs_approval'
                    summary = 'Approval required before this consequential action can execute.'
                    pending_action = plan
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
                messages.append({'role':'assistant','content':json.dumps(plan,ensure_ascii=False)})
                messages.append({'role':'user','content':json.dumps({'execution_result':compact_result,'updated_observation':observation,'instruction':'Verify progress and select exactly one next action. Do not repeat a successful action unnecessarily.'},ensure_ascii=False)})
                # Keep the original goal plus only the latest interaction context.
                # Unbounded DOM snapshots inflate every OpenRouter request.
                if len(messages) > 5:
                    messages = [messages[0]] + messages[-4:]
                if result.get('ok') is False:
                    if result.get('loop_guard'):
                        status='needs_input'
                        summary='Stopped a repeated failing action to prevent an automation loop. The locator needs a different evidence-based strategy.'
                        break
                    messages.append({'role':'user','content':json.dumps({'instruction':'The action failed. Do not repeat the same action or merely change locator syntax without new evidence. Use the error details and candidate metadata to select a different strategy, inspect once, or ask the user for help.','action_error':result},ensure_ascii=False)})
            else:
                status='step_limit'; summary=f'Stopped at configured limit ({self.settings.max_steps} steps).'
            timings['unattributed_seconds']=round(max(0.0,time.perf_counter()-perf_start-timings['browser_start_seconds']-timings['url_discovery_seconds']-timings['navigation_seconds']-timings['initial_observation_seconds']-sum(timings['planning_seconds'])-sum(timings['action_seconds'])-sum(timings['post_action_observation_seconds'])),3)
            report={'status':status,'summary':summary,'steps':trace,'artifacts':artifacts,'elapsed_seconds':round(time.time()-start,2),'url':self.browser.page.url if self.browser and self.browser.page else None,'timings_seconds':timings,'pending_action':pending_action}
            if status=='completed': self.memory.add_note(domain,summary,{'task':task,'steps':len(trace)})
            return report
        except Exception as e:
            summary=f'{type(e).__name__}: {e}'
            try:
                if self.browser and self.browser.page:
                    p=self.browser.screenshot(f'{self.settings.artifact_dir}/error_{int(time.time())}.png'); artifacts.append(p)
            except Exception: pass
            timings['unattributed_seconds']=round(max(0.0,time.perf_counter()-perf_start-timings['browser_start_seconds']-timings['url_discovery_seconds']-timings['navigation_seconds']-timings['initial_observation_seconds']-sum(timings['planning_seconds'])-sum(timings['action_seconds'])-sum(timings['post_action_observation_seconds'])),3)
            return {'status':'failed','summary':summary,'steps':trace,'artifacts':artifacts,'elapsed_seconds':round(time.time()-start,2),'timings_seconds':timings}
        finally:
            try: self.memory.add_run(task,status,summary,artifacts)
            except Exception: pass
            if owns and self.browser:
                try: self.browser.close()
                finally: self.browser=None
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
        if kind=='inspect': return {'ok':True,'elements':self.browser.inspect(180)}
        if kind=='status': return self.browser.status()
        if kind=='screenshot': return {'ok':True,'path':self.browser.screenshot(plan.get('path') or f'{self.settings.artifact_dir}/manual.png')}
        if kind=='navigate': return self.browser.open(plan['value'])
        if kind=='read_text': return {'ok':True,'text':self.browser.text(plan['by'],plan['value'],plan.get('name'))}
        if kind=='click': return self.browser.click(plan['by'],plan['value'],plan.get('name'))
        if kind=='fill': return self.browser.fill(plan['by'],plan['value'],plan['text'],plan.get('name'))
        if kind=='select': return self.browser.select(plan['by'],plan['value'],plan['option'],plan.get('name'))
        if kind=='check': return self.browser.check(plan['by'],plan['value'],plan.get('name'),bool(plan.get('checked',True)))
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
