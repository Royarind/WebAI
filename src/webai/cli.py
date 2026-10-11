import json, typer
from rich import print
from .browser import WebAI
from .agent import Agent
from .config import get_settings
from .memory import Memory
from .planner import rule_plan, llm_plan

app=typer.Typer(no_args_is_help=True,help='WebAI local AI web automation toolkit.')
def show(value): print(json.dumps(value,indent=2,ensure_ascii=False,default=str))

def execute(web,plan):
    action=plan['action']
    if action=='inspect': return {'status':web.status(),'elements':web.inspect()}
    if action=='screenshot': return {'screenshot':web.screenshot(plan.get('path','artifacts/page.png'))}
    if action=='click': return web.click(plan['by'],plan['value'],plan.get('name'))
    if action=='fill': return web.fill(plan['by'],plan['value'],plan['text'],plan.get('name'))
    if action=='read_text': return {'text':web.text(plan['by'],plan['value'],plan.get('name'))}
    if action=='status': return web.status()
    raise ValueError('Unsupported action: '+action)

@app.command()
def doctor():
    """Show LLM provider configuration status without revealing secrets."""
    s=get_settings()
    configured = s.provider == 'ollama' or bool(s.api_key)
    show({'llm_configured':configured,'provider':s.provider,'base_url':s.base_url,'model':s.model,'vision_enabled':s.vision_enabled,'max_steps':s.max_steps,'memory_path':s.memory_path,'artifact_dir':s.artifact_dir})

@app.command()
def open(url:str,headless:bool=typer.Option(False)):
    with WebAI(headless=headless) as web: show(web.open(url))

@app.command()
def inspect(url:str=typer.Option(...),limit:int=typer.Option(150,min=1,max=500),headless:bool=typer.Option(False)):
    with WebAI(headless=headless) as web: web.open(url); show(web.inspect(limit))

@app.command()
def click(by:str=typer.Option(...),value:str=typer.Option(...),name:str=typer.Option(None),url:str=typer.Option(...),headless:bool=typer.Option(False)):
    with WebAI(headless=headless) as web: web.open(url); show(web.click(by,value,name))

@app.command()
def screenshot(url:str=typer.Option(...),path:str=typer.Option('artifacts/page.png'),headless:bool=typer.Option(False)):
    with WebAI(headless=headless) as web: web.open(url); print('Saved:',web.screenshot(path))

@app.command()
def run(url:str=typer.Option(None,help='Optional starting URL; inferred from task when omitted'),task:str=typer.Option(...),planner:str=typer.Option('llm',help='llm or rules'),headless:bool=typer.Option(False)):
    """Run a bounded multi-step agent task. LLM planner is the default."""
    if planner.lower()=='rules':
        if not url:
            raise typer.BadParameter('The rules planner requires --url. Use --planner llm to enable automatic URL discovery.')
        with WebAI(headless=headless) as web:
            opened=web.open(url); outputs=[]
            for step in [x.strip() for x in task.split(' then ') if x.strip()]:
                plan=rule_plan(step); outputs.append({'task':step,'plan':plan,'result':execute(web,plan)})
            show({'opened':opened,'steps':outputs,'status':web.status()})
    else:
        show(Agent().run(task,url=url))

@app.command()
def agent(url:str=typer.Option(None,help='Optional initial URL'),persistent:bool=typer.Option(True),headless:bool=typer.Option(False)):
    """Start a natural-language interactive session using the configured LLM."""
    a=Agent()
    if headless: a.settings.headless=True
    a.chat(url=url,persistent=persistent)

@app.command()
def history(limit:int=typer.Option(10,min=1,max=100)):
    show(Memory(get_settings().memory_path).recent_runs(limit))

@app.command()
def serve(host:str=typer.Option('127.0.0.1'),port:int=typer.Option(8765)):
    """Launch local web control UI; loopback is the safe default."""
    import uvicorn
    from .server import app as web_app
    uvicorn.run(web_app,host=host,port=port)

if __name__=='__main__': app()
