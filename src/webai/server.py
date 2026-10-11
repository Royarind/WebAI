from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from .agent import Agent
from .memory import Memory
from .config import get_settings

app=FastAPI(title='WebAI Local',version='0.3.0')
PAGE='''<!doctype html><html><head><meta charset="utf-8"><title>WebAI Local</title><style>body{font:16px system-ui;max-width:900px;margin:32px auto;padding:0 16px}textarea,input{width:100%;padding:10px;margin:6px 0;box-sizing:border-box}button{padding:10px 16px;cursor:pointer}pre{white-space:pre-wrap;background:#f4f4f4;padding:14px;border-radius:8px}.note{color:#555}</style></head><body><h1>WebAI Local</h1><p class="note">Local automation dashboard. Use authorized sites only. Consequential actions are blocked by default.</p><label>URL</label><input id="url" placeholder="https://example.com"><label>Task in plain English</label><textarea id="task" rows="4" placeholder="Inspect the page and report available controls"></textarea><button onclick="runTask()">Run task</button> <button onclick="getHistory()">History</button><pre id="out">Ready.</pre><script>async function runTask(){let o=document.querySelector('#out');o.textContent='Running...';try{let r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:document.querySelector('#url').value,task:document.querySelector('#task').value})});o.textContent=JSON.stringify(await r.json(),null,2)}catch(e){o.textContent=String(e)}}async function getHistory(){let r=await fetch('/api/history');document.querySelector('#out').textContent=JSON.stringify(await r.json(),null,2)}</script></body></html>'''
class RunRequest(BaseModel):
    url:str
    task:str
@app.get('/',response_class=HTMLResponse)
def index(): return PAGE
@app.post('/api/run')
def run_task(req:RunRequest):
    if not req.url.startswith(('http://','https://')): raise HTTPException(400,'Only http(s) URLs are accepted.')
    if not req.task.strip(): raise HTTPException(400,'Task is required.')
    return Agent().run(req.task,url=req.url)
@app.get('/api/history')
def history(): return Memory(get_settings().memory_path).recent_runs(30)
