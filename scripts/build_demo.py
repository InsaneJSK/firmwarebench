"""Rebuild the credential-free GitHub Pages demo in docs/ from original evidence."""
import hashlib
import json
import re
import shutil
from pathlib import Path

root = Path(__file__).resolve().parent.parent
dist = root/"docs"
dist.mkdir(parents=True,exist_ok=True)
(dist/'assets').mkdir(exist_ok=True)
(dist/'data').mkdir(exist_ok=True)
records = [
    {'key':'groq','label':'Groq GPT-OSS-20B · full benchmark','file':'groq-comparison.json',
     'note':'48 trials · 2 tasks · 4 scenarios · 3 repetitions. Four decisions and eight tools per trial. Protocol and time limits differ from the Qwen baseline.'},
    {'key':'pilot','label':'Groq GPT-OSS-20B · focused repair pilot','file':'groq-repair-pilot-v2.json',
     'note':'8 trials · 2 tasks · 2 disruptions · 1 repetition. Six decisions and 12 tools per trial. This later pilot is separate from the full benchmark.'},
    {'key':'qwen','label':'Local Qwen 3B · baseline','file':'comparison.json',
     'note':'48 trials · 2 tasks · 4 scenarios · 3 repetitions. Four decisions and eight tools per trial. All outcomes, including failed repairs, are preserved.'}
]
evidence = []
for record in records:
    source = root/'examples'/record['file']
    target = dist/'data'/record['file']
    shutil.copyfile(source,target)
    evidence.append({'file':record['file'],'sha256':hashlib.sha256(source.read_bytes()).hexdigest()})

html = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FirmwareBench · Evidence explorer</title><meta name="description" content="Inspect real coding-agent repairs, controlled failures and independent firmware test evidence. Run your own benchmark with your own model provider."><link rel="stylesheet" href="./assets/style.css"><script defer src="./assets/app.js"></script></head>
<body><header><div class="brand"><i class="mark" aria-hidden="true">▥</i>FirmwareBench</div><span class="host">EVIDENCE EXPLORER</span><nav><a href="./pitch.pdf" target="_blank" rel="noopener">Pitch deck</a><a href="https://github.com/InsaneJSK/firmwarebench" target="_blank" rel="noopener">GitHub ↗</a></nav></header>
<main><section><div class="intro"><div><p class="overline">Coding agents / embedded C repair</p><h1>Every result has evidence.</h1><p class="lead">Compare real agent repairs under controlled failures. Follow each result through the model calls, source patch and independent verifier.</p></div><a class="primary cta" href="https://github.com/InsaneJSK/firmwarebench#run-the-hosted-groq-pilot" target="_blank" rel="noopener">Run with your own provider ↗</a></div>
<div class="demo-note"><strong>Recorded experiments</strong><p>This public dashboard explores saved runs. The full platform runs in your own environment, with your model provider credentials connected through Bifrost. Compilation and grading stay in isolated Docker containers.</p></div>
<div class="toolbar"><label>Experiment <select id="experiment"></select></label><a id="export" href="./data/groq-comparison.json" download>Download evidence ↓</a><label class="import">Open export <input type="file" id="import" accept=".json,application/json"></label></div>
<p class="study-note" id="studyNote"></p><p class="measurement-note">Historical measurements are preserved. Some older smolagents results omit a JSON-parsed completion call; current runs record it. Unknown usage or cost remains unavailable. <a href="https://github.com/InsaneJSK/firmwarebench#measurement-and-evidence" target="_blank" rel="noopener">Measurement definitions ↗</a></p>
<div role="status" id="message" aria-live="polite"></div><div id="evidence"></div></section>
<details class="about"><summary>How to run your own benchmark</summary><p>FirmwareBench is a self-hosted benchmarking platform. Install it from the repository, choose a supported model route through Bifrost, and configure your own provider credentials locally. Live experiments run the agent worker and Docker verifier in your environment.</p><p>This public evidence explorer needs no API key and does not launch jobs. Opening an export reads the file in your browser without uploading it.</p><p><a href="https://github.com/InsaneJSK/firmwarebench#run-the-hosted-groq-pilot" target="_blank" rel="noopener">Installation and provider setup ↗</a> · <a href="./pitch.html">View presentation</a> · <a href="./pitch.pdf" download>Download pitch PDF</a></p></details>
<dialog id="drawer"><div class="dialogbar"><p class="overline">Trial evidence</p><button id="close">Close ×</button></div><div id="detail"></div></dialog></main>
<footer class="site-footer">FirmwareBench · PS02 · Bifrost integration · Host-compiled firmware evidence</footer></body></html>
'''
(dist/'index.html').write_text(html,encoding='utf-8')
css = (root/'web/style.css').read_text(encoding='utf-8') + '''
nav a{color:#d1ded5;text-decoration:none;font-size:14px;padding:8px 0}nav a:hover{text-decoration:underline}
.intro{align-items:flex-start}.lead{font-size:18px;line-height:1.6;color:#52655d;max-width:760px;margin:16px 0 0}
.cta{white-space:nowrap;text-decoration:none;font-size:14px;margin-top:8px}.demo-note{border-left:3px solid #88a65d;background:#e9efdf;padding:16px 20px;margin-top:26px}.demo-note strong{font-size:14px}.demo-note p{font-size:14px;line-height:1.6;margin:6px 0 0;max-width:1000px}
.study-note{font-size:14px;line-height:1.6;color:#435d50;margin-bottom:8px}.measurement-note{font-size:12px;line-height:1.6;color:#52655d;max-width:1050px;margin-top:0}.about{margin-top:30px;line-height:1.65}.about summary{font-weight:600}.about p{max-width:950px}.site-footer{font:12px/1.5 Consolas,monospace;color:#52655d;padding:12px max(4vw,20px) 28px;max-width:1480px;margin:auto}.toolbar select{max-width:min(580px,50vw)}
@media(max-width:760px){header nav{gap:12px}.intro{display:block}.cta{display:inline-block;margin-top:18px}.lead{font-size:16px}.toolbar label:first-child{display:block;width:100%}.toolbar select{display:block;max-width:100%;width:100%;margin-top:8px}.demo-note{padding:14px}.host{display:none}h1{font-size:39px}.section-title h2{font-size:22px}.meta{font-size:12px;overflow-wrap:anywhere}}
'''
(dist/'assets/style.css').write_text(css,encoding='utf-8')
source = (root/'web/app.js').read_text(encoding='utf-8')
shared = source[source.index('function metric('):source.index('async function load()')]
prefix = '''"use strict";
const $ = id => document.getElementById(id);
const records = __RECORDS__;
const catalog = {agents:{inspect:"Inspect ReAct",smolagents:"smolagents ToolCallingAgent"},tasks:{uart:"UART telemetry parser",ring:"Telemetry ring buffer"}};
const names = {clean:"Clean","broken-tool":"Broken tool","model-outage":"Model outage","misleading-fixture":"Misleading fixture"};
const esc = value => String(value ?? "—").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num = value => value == null ? "—" : Number(value).toLocaleString(undefined,{maximumFractionDigits:1});
const usd = value => value == null ? "—" : "$"+Number(value).toFixed(4);
const badge = s => '<span class="pill '+esc(s)+'">'+esc(s)+'</span>';
const title = (a,t) => esc(catalog.agents[a]||a)+" · "+esc(catalog.tasks[t]||t);
let current, imported, selection="groq", importUrl;
function list(){const options=records.map(r=>[r.key,r.label]);if(imported)options.push(["imported","Opened file · "+imported.config.title]);$("experiment").replaceChildren(...options.map(([v,s])=>new Option(s,v)));$("experiment").value=selection;}
'''.replace('__RECORDS__',json.dumps(records))
suffix = '''
function validate(d){
 if(d.schema!=="firmwarebench.experiment.v1"||!Array.isArray(d.trials)||!Array.isArray(d.comparison)||!d.config||d.trials.some(t=>!t.metrics||!Array.isArray(t.events)||!Array.isArray(t.metrics.served))) throw Error("Select a FirmwareBench v1 export.");
 return d;
}
async function load(){const key=selection;$("message").textContent="Loading saved evidence…";$("export").hidden=true;
 try{let d,record=records.find(r=>r.key===key);if(key==="imported")d=imported;else{if(!record)throw Error("Unknown saved experiment.");const response=await fetch("./data/"+record.file);if(!response.ok)throw Error("Saved evidence could not be loaded. Please refresh or download it from GitHub.");d=validate(await response.json());}
 if(key!==selection)return;current=d;render();$("message").textContent="";$("studyNote").textContent=record?record.note:"Locally opened export. This file stays in your browser.";
 $("export").href=record?"./data/"+record.file:importUrl;$("export").download=record?record.file:"firmwarebench-opened-export.json";$("export").hidden=false;
 }catch(err){if(key!==selection)return;$("message").textContent=err.message;$("evidence").replaceChildren();$("studyNote").textContent="";}}
$("close").onclick=()=>$("drawer").close();
$("experiment").onchange=e=>{selection=e.target.value;load();};
$("evidence").onclick=e=>{const b=e.target.closest("button");if(!b)return;const ids=b.dataset.group?b.dataset.group.split(","):[b.dataset.trial];const trial=current.trials.find(t=>t.id===ids[0]);if(trial)showDetail(trial,ids);};
$("import").onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>25e6)throw Error("Export exceeds 25 MB.");const text=await file.text();const data=validate(JSON.parse(text));if(importUrl)URL.revokeObjectURL(importUrl);imported=data;importUrl=URL.createObjectURL(new Blob([text],{type:"application/json"}));selection="imported";list();await load();}catch(err){$("message").textContent=err.message;}finally{e.target.value="";}};
list();load();
'''
(dist/'assets/app.js').write_text(prefix+shared+suffix,encoding='utf-8')
assert 'function configure(' not in (prefix+shared+suffix) and 'method:"POST"' not in (prefix+shared+suffix)
(dist/'.nojekyll').write_text('')
deployment_manifest = [{'path':str(p.relative_to(dist)).replace('\\','/'),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in dist.rglob('*') if p.is_file()]
assert len(deployment_manifest) == 9
patterns = re.compile(rb'(?:gsk_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{32,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
for item in deployment_manifest:
    assert not patterns.search((dist/item['path']).read_bytes()), item['path']
print(json.dumps({'static_files':len(deployment_manifest),'bytes':sum(i['bytes'] for i in deployment_manifest),'evidence_exports':len(evidence),'model_requests':0,'output':str(dist)}))
