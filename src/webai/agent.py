import json, time
from urllib.parse import urlparse
from .browser import WebAI
from .config import get_settings
from .llm import LLMClient
from .memory import Memory

BLOCKED=('purchase','buy now','pay now','payment','delete','remove account','send email','send message','submit order','place order','transfer money','publish','confirm booking','finalize order')
def sensitive(text):
    low=text.lower()
    return any(x in low for x in BLOCKED)

class Agent:
    """Bounded observe-plan-act-verify loop using a configurable chat model."""
    def __init__(self, browser=None, llm=None, memory=None):
        self.settings=get_settings(); self.browser=browser; self.llm=llm or LLMClient(); self.memory=memory or Memory(self.settings.memory_path)
    def run(self, task, url=None):
        start=time.time(); artifacts=[]; trace=[]; status='failed'; summary=''; owns=False
        try:
            if sensitive(task): raise PermissionError('Blocked by default: the task appears to involve a consequential action. Use an explicitly reviewed workflow for this action.')
            owns=self.browser is None
            if owns:
                self.browser=WebAI(headless=self.settings.headless)
                self.browser.start()
            if url: opened=self.browser.open(url)
            elif self.browser.page: opened=self.browser.status()
            else: raise ValueError('Provide a URL or an existing browser session.')
            domain=urlparse(self.browser.page.url).netloc
            obs={'task':task,'page':opened,'elements':self.browser.inspect(100),'recent_runs':self.memory.recent_runs(4),'domain_notes':self.memory.notes_for(domain,4)}
            messages=[{'role':'user','content':json.dumps({'goal':task,'observation':obs},ensure_ascii=False)}]
            for i in range(self.settings.max_steps):
                shot=None
                try:
                    shot=self.browser.screenshot(f'{self.settings.artifact_dir}/agent_step_{int(time.time())}_{i+1}.png'); artifacts.append(shot)
                except Exception: pass
                plan=self.llm.next_action(messages,shot)
                trace.append({'step':i+1,'plan':plan})
                kind=plan['action']
                if kind=='finish':
                    status, summary = self._finish_status(plan, page=self.browser.page)
                    break
                if kind=='ask_user':
                    status='needs_input'; summary=plan.get('summary') or 'The agent needs clarification.'; break
                if kind in {'click','fill','select','check'} and sensitive(str(plan.get('text',''))):
                    raise PermissionError('Blocked a potentially consequential value.')
                if kind in {'click','select','check'} and sensitive(str(plan.get('value',''))+' '+str(plan.get('name',''))):
                    raise PermissionError('Blocked a control whose locator appears to describe a consequential action.')
                if kind=='navigate' and not plan.get('value','').startswith(('http://','https://')): raise ValueError('Navigation must use http(s).')
                result=self._execute_action_with_recovery(plan)
                if kind=='screenshot' and result.get('path'): artifacts.append(result['path'])
                observation={'url':self.browser.page.url,'title':self.browser.page.title(),'result':result,'elements':self.browser.inspect(100)}
                messages.append({'role':'assistant','content':json.dumps(plan,ensure_ascii=False)})
                messages.append({'role':'user','content':json.dumps({'execution_result':result,'updated_observation':observation,'instruction':'Verify progress and select exactly one next action. Do not repeat a successful action unnecessarily.'},ensure_ascii=False)})
                if result.get('ok') is False:
                    messages.append({'role':'user','content':'The action did not verify. Reinspect and recover; do not blindly repeat.'})
            else:
                status='step_limit'; summary=f'Stopped at configured limit ({self.settings.max_steps} steps).'
            report={'status':status,'summary':summary,'steps':trace,'artifacts':artifacts,'elapsed_seconds':round(time.time()-start,2),'url':self.browser.page.url if self.browser and self.browser.page else None}
            if status=='completed': self.memory.add_note(domain,summary,{'task':task,'steps':len(trace)})
            return report
        except Exception as e:
            summary=f'{type(e).__name__}: {e}'
            try:
                if self.browser and self.browser.page:
                    p=self.browser.screenshot(f'{self.settings.artifact_dir}/error_{int(time.time())}.png'); artifacts.append(p)
            except Exception: pass
            return {'status':'failed','summary':summary,'steps':trace,'artifacts':artifacts,'elapsed_seconds':round(time.time()-start,2)}
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
