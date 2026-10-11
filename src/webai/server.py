from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from .agent import Agent
from .browser import WebAI
from .memory import Memory
from .config import get_settings

app = FastAPI(title="WebAI Local", version="0.4.0")

# The dashboard owns one visible browser session. Keeping the Agent alive across
# API requests lets a user solve CAPTCHAs, sign in, or handle consent prompts and
# then resume against the same live page instead of a closed/recreated browser.
session_agent = Agent(browser=WebAI(headless=False))
last_task = ""
last_url = ""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>WebAI Local</title>
<style>
body{font:16px system-ui;max-width:900px;margin:32px auto;padding:0 16px}
textarea,input{width:100%;padding:10px;margin:6px 0;box-sizing:border-box}
button{padding:10px 16px;cursor:pointer;margin:4px 4px 4px 0}
pre{white-space:pre-wrap;background:#f4f4f4;padding:14px;border-radius:8px;overflow:auto}
.note{color:#555}.hidden{display:none}.intervention{background:#fff4d6;padding:12px;border-radius:8px}
</style></head><body>
<h1>WebAI Local</h1>
<p class="note">The visible browser stays open when WebAI needs you to intervene. Only use sites and accounts you are authorized to access.</p>
<label>URL (optional)</label><input id="url" placeholder="Leave blank to let WebAI find the starting website">
<label>Task in plain English</label><textarea id="task" rows="4" placeholder="Inspect the page and report available controls"></textarea>
<button id="run" onclick="runTask()">Run task</button>
<button onclick="getHistory()">History</button>
<div id="intervention" class="intervention hidden">
<strong>WebAI is waiting for you.</strong>
<p id="interventionText">Switch to the WebAI browser window and complete the required manual step. Do not close the browser. When finished, click Resume.</p>
<button id="resume" onclick="resumeTask()">Resume after intervention</button>
</div>
<pre id="out">Ready.</pre>
<script>
function showResult(data){
 const out=document.querySelector('#out');
 out.textContent=JSON.stringify(data,null,2);
 const paused=['needs_input','needs_approval'].includes(data.status);
 document.querySelector('#intervention').classList.toggle('hidden',!paused);
 if(paused){
   document.querySelector('#interventionText').textContent =
     'WebAI paused at '+(data.url||'the current page')+'. Switch to the visible WebAI browser, solve the CAPTCHA or complete the requested manual step, and leave that tab open. Then click Resume after intervention.';
 }
}
async function runTask(){
 const out=document.querySelector('#out');
 const task=document.querySelector('#task').value;
 out.textContent='Running...';
 document.querySelector('#intervention').classList.add('hidden');
 try{
   const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({url:document.querySelector('#url').value,task})});
   const data=await r.json(); showResult(data);
 }catch(e){out.textContent=String(e)}
}
async function resumeTask(){
 const out=document.querySelector('#out'); out.textContent='Resuming on the current browser page...';
 document.querySelector('#resume').disabled=true;
 try{
   const r=await fetch('/api/resume',{method:'POST'});
   const data=await r.json(); showResult(data);
 }catch(e){out.textContent=String(e)}
 finally{document.querySelector('#resume').disabled=false}
}
async function getHistory(){
 const r=await fetch('/api/history');
 document.querySelector('#out').textContent=JSON.stringify(await r.json(),null,2);
}
</script></body></html>"""

class RunRequest(BaseModel):
    url: str = ""
    task: str

@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE

@app.post("/api/run")
def run_task(req: RunRequest):
    global last_task, last_url
    url = req.url.strip()
    task = req.task.strip()
    if url and not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL must start with http:// or https://, or be left blank for automatic discovery.")
    if not task:
        raise HTTPException(400, "Task is required.")
    last_task, last_url = task, url
    return session_agent.run(task, url=url or None)

@app.post("/api/resume")
def resume_task():
    if not last_task:
        raise HTTPException(409, "There is no paused task to resume. Run a task first.")
    browser = session_agent.browser
    if browser is None or browser.page is None:
        raise HTTPException(409, "The browser session is no longer available. Run the task again.")
    # Intentionally omit the original URL: navigating to it could discard the
    # user's CAPTCHA/login/consent work. Agent observes the current live page.
    return session_agent.run(last_task, url=None)

@app.get("/api/history")
def history():
    return Memory(get_settings().memory_path).recent_runs(30)
