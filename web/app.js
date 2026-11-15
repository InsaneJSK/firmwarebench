"use strict";
const $ = id => document.getElementById(id);
let catalog, current, imported, poll, selection = "saved";
const names = {"clean":"Clean", "broken-tool":"Broken tool", "model-outage":"Model outage", "misleading-fixture":"Misleading fixture"};
const esc = value => String(value ?? "—").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num = value => value == null ? "—" : Number(value).toLocaleString(undefined, {maximumFractionDigits:1});
const usd = value => value == null ? "—" : "$" + Number(value).toFixed(4);
const badge = s => '<span class="pill '+esc(s)+'">'+esc(s)+'</span>';
const title = (a,t) => esc(catalog.agents[a])+" · "+esc(catalog.tasks[t]);
function page(setup) {
  $("results").hidden=setup; $("setup").hidden=!setup;
  $("setupNav").toggleAttribute("aria-current",setup); $("compareNav").toggleAttribute("aria-current",!setup);
  window.scrollTo(0,0);
}
async function api(path, init) {
  const response=await fetch(path, init);
  if (!response.ok) { const body=await response.json().catch(()=>({})); throw Error(typeof body.detail==="string"?body.detail:"Request failed ("+response.status+"). Check the configuration and local services."); }
  return response.json();
}
function configure() {
  const f=$("form"), options=obj=>Object.entries(obj).map(([k,v])=>'<option value="'+esc(k)+'">'+esc(v)+'</option>').join("");
  f.agentA.innerHTML=options(catalog.agents); f.agentB.innerHTML=options(catalog.agents); f.agentB.selectedIndex=1;
  f.route.innerHTML=options(Object.fromEntries(catalog.routes.map(x=>[x,x])));
  function checks(id,items) { $(id).innerHTML=Object.entries(items).map(([k,v])=>'<label><input type="checkbox" name="'+id+'" value="'+esc(k)+'" checked> '+esc(v)+'</label>').join(""); }
  f.suite.innerHTML=options(Object.fromEntries(Object.keys(catalog.suites).map(k=>[k,k])));
  function suiteTasks(){const versions=catalog.suites[f.suite.value];checks("tasks",Object.fromEntries(Object.entries(versions).map(([k,v])=>[k,catalog.tasks[k]+" · v"+v])));}
  suiteTasks();
  f.suite.addEventListener("change",()=>{suiteTasks();update();});
  checks("scenarios",names);
  if (f.route.value === "groq/openai/gpt-oss-20b") {
    f.show_edit_feedback.checked = true;
    f.repeats.value = 1;
    f.turn_limit.value = 6;
    f.tool_limit.value = 12;
    f.seconds.value = 300;
    f.querySelectorAll('[name="tasks"]').forEach(box => { box.checked = box.value === "uart"; });
    f.querySelectorAll('[name="scenarios"]').forEach(box => { box.checked = box.value === "model-outage"; });
  }
  const update=()=>{const d=new FormData(f); $("count").textContent=(2*d.getAll("tasks").length*d.getAll("scenarios").length*Number(d.get("repeats")))+" trials scheduled";};
  f.addEventListener("input",update); update();
  f.onsubmit=async e=>{ e.preventDefault(); const d=new FormData(f); const c=Object.fromEntries(d);
    c.agents=[c.agentA,c.agentB]; delete c.agentA; delete c.agentB;
    c.tasks=d.getAll("tasks"); c.scenarios=d.getAll("scenarios");
    c.show_edit_feedback = f.show_edit_feedback.checked;
    ["repeats","seconds","tool_limit","turn_limit"].forEach(k=>c[k]=Number(c[k]));
    if(c.agents[0]===c.agents[1]||!c.tasks.length||!c.scenarios.length){$("formError").textContent="Select two different agents, a task and a scenario.";return;}
    const submit=f.querySelector("button[type=submit]"); submit.disabled=true;
    try { const r=await api("/api/experiments",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(c)}); await list(r.id); page(false); await load(); $("formError").textContent=""; }
    catch(err){$("formError").textContent=err.message;} finally {submit.disabled=false;}
  };
}
async function list(id) {
  const records=await api("/api/experiments"); const opts=[["saved","Saved benchmark"],...records.map(e=>[e.id,e.config.title+" · "+new Date(e.created*1000).toLocaleTimeString()])];
  if(imported) opts.push(["imported","Opened file · "+imported.config.title]);
  $("experiment").replaceChildren(...opts.map(([v,s])=>new Option(s,v)));
  selection=id; $("experiment").value=id;
}
function metric(label,value) {return '<div class="metric"><small>'+esc(label)+'</small><strong>'+esc(value)+'</strong></div>';}
function render() {
  const d=current, trials=d.trials, valid=trials.filter(t=>["passed","failed"].includes(t.status));
  const done=trials.filter(t=>["passed","failed","invalid"].includes(t.status));
  const passed=valid.filter(t=>t.status==="passed").length;
  const fired=valid.filter(t=>t.triggered && t.scenario!=="clean");
  const m=done.map(t=>t.metrics);
  const total=m.reduce((s,x)=>s+x.provider_attempts,0), covered=m.reduce((s,x)=>s+x.usage_covered,0);
  const stats=[metric("Verified passes",passed+" / "+valid.length),metric("Triggered & passed",fired.filter(t=>t.status==="passed").length+" / "+fired.length),metric("Usage coverage",covered+" / "+total),metric("Trials finished",done.length+" / "+trials.length)].join("");
  const pct=g=>g&&g.valid?g.passed/g.valid:null;
  const rows=d.comparison.map(g=>{const base=d.comparison.find(x=>x.task===g.task&&x.agent===g.agent&&x.scenario==="clean");
    let delta="—"; if(g.scenario!=="clean"&&pct(base)!=null&&pct(g)!=null){const diff=Math.round(100*(pct(g)-pct(base)));delta=(diff>0?"+":"")+diff+" pp";}
    return '<tr><td>'+esc(catalog.agents[g.agent]||g.agent)+'</td><td>'+esc(catalog.tasks[g.task]||g.task)+'</td><td>'+esc(names[g.scenario]||g.scenario)+'</td><td><button data-group="'+esc(g.ids.join(","))+'">'+esc(g.passed)+' / '+esc(g.valid)+' ↗</button></td><td>'+esc(delta)+'</td><td>'+esc(g.invalid)+'</td><td>'+(g.scenario==="clean"?"—":esc(g.recovered)+" / "+esc(g.triggered))+'</td><td>'+usd(g.cost_per_success)+'</td></tr>';
  }).join("");
  const trs=trials.map(t=>'<tr><td><button data-trial="'+esc(t.id)+'">'+esc(t.id.slice(0,8))+' ↗</button></td><td>'+title(t.agent,t.task)+'</td><td>'+esc(names[t.scenario])+'</td><td>'+esc(t.repetition)+'</td><td>'+badge(t.status)+'</td><td>'+num(t.metrics.steps)+'</td><td>'+num(t.metrics.tool_calls)+'</td><td>'+num(t.metrics.tokens)+'</td><td>'+usd(t.metrics.cost)+'</td><td>'+num(t.agent_seconds)+'</td></tr>').join("");
  $("evidence").innerHTML='<div class="section-title"><h2>'+esc(d.config.title)+'</h2><span class="meta">'+esc(d.config.route)+' · '+esc(d.config.suite)+'</span></div><div class="metrics">'+stats+'</div><div class="section-title"><h2>Agent comparison</h2><small>Passed / valid trials</small></div><div class="tablewrap"><table><thead><tr><th>Agent</th><th>Task</th><th>Scenario</th><th>Passes</th><th>Δ clean</th><th>Invalid</th><th>Pass / fired</th><th>Cost / pass</th></tr></thead><tbody>'+rows+'</tbody></table></div><div class="section-title"><h2>Trial ledger</h2><small>'+esc(d.config.turn_limit)+' turns · '+esc(d.config.tool_limit)+' tools · '+esc(d.config.seconds)+'s limit</small></div><div class="tablewrap"><table><thead><tr><th>Trial</th><th>Configuration</th><th>Scenario</th><th>Repeat</th><th>Verdict</th><th>Steps</th><th>Tools</th><th>Tokens</th><th>Cost</th><th>Agent sec</th></tr></thead><tbody>'+trs+'</tbody></table></div>';
}
function showDetail(t,ids) {
  const choose=ids.length>1?'<label>Repetition <select id="rep">'+ids.map(i=>{const r=current.trials.find(x=>x.id===i);return '<option value="'+esc(i)+'" '+(i===t.id?"selected":"")+'>'+r.repetition+" · "+esc(r.status)+'</option>';}).join("")+'</select></label>':"";
  const section=(name,data)=>'<details><summary>'+esc(name)+'</summary><pre>'+esc(JSON.stringify(data,null,2))+'</pre></details>';
  const checks=t.verifier?.assertions||[];

  const toolCalls=t.events.filter(e=>e.kind==="tool"&&e.data.name==="run_public_tests");
  const faultTime=t.events.find(e=>e.kind==="fault")?.at;
  let attribution="";
  if(t.scenario==="model-outage" && faultTime!=null) {
    attribution=t.metrics.gateway_recovery?"Bifrost recovered the model call after the controlled HTTP 503.":"The controlled primary returned HTTP 503.";
  } else if(t.scenario==="broken-tool" && faultTime!=null) {
    attribution=toolCalls.length>1?"The agent called public tests again after the injected failure.":"The transient failure fired. No second public-test call was recorded.";
  } else if(t.scenario==="broken-tool" && ["passed","failed"].includes(t.status)) {
    attribution="The agent did not call the public-test tool. The fault did not fire.";
  } else if(t.scenario==="misleading-fixture" && faultTime!=null) {
    attribution="The issue and the obsolete note were both supplied. The assertions below grade the final behavior.";
  }
  const route=t.metrics.served.join(", ")||"Unavailable";
  $("detail").innerHTML='<h2>'+title(t.agent,t.task)+'</h2><p>'+badge(t.status)+' · '+esc(names[t.scenario])+' · repetition '+esc(t.repetition)+'</p>'+choose+
    '<p class="meta">'+esc(t.reason||"")+'</p><div class="metrics">'+metric("Agent sec",num(t.agent_seconds))+metric("Queue sec",num(t.queue_seconds))+metric("Grader sec",num(t.grader_seconds))+metric("Fault fired",t.scenario==="clean"?"—":t.triggered?"Yes":"No")+'</div>'+
    '<p><b>Served model</b> '+esc(route)+'</p>'+(attribution?'<p>'+esc(attribution)+'</p>':'')+'<h3>Verifier assertions</h3>'+(checks.length?checks.map(a=>'<details><summary>'+badge(a.pass?"passed":"failed")+' '+esc(a.scope)+' · '+esc(a.name)+'</summary><pre>'+esc(JSON.stringify(a,null,2))+'</pre></details>').join(""):'<p>Awaiting verifier evidence.</p>')+
    '<h3>Candidate patch</h3><pre>'+esc(t.diff||"No recorded changes to firmware.c.")+'</pre>'+
    '<h3>Timeline</h3>'+t.events.map(e=>'<details><summary>'+num(e.at)+' s · '+esc(e.kind)+' · '+esc(e.data.name||e.data.provider||e.data.requested||e.data.profile||e.data.model||"")+'</summary><pre>'+esc(JSON.stringify(e.data,null,2))+'</pre></details>').join("")+
    section("Metrics and coverage",t.metrics)+section("Pinned versions",t.versions);
  if($("rep")) $("rep").onchange=e=>showDetail(current.trials.find(r=>r.id===e.target.value),ids);
  if(!$("drawer").open) $("drawer").showModal();
}
async function load() {
  const key=selection; clearTimeout(poll);
  try {const d=key==="imported"?imported:await api("/api/experiments/"+encodeURIComponent(key)); if(key!==selection)return;
    current=d; $("message").textContent=""; $("export").hidden=key==="imported"; $("export").href="/api/experiments/"+encodeURIComponent(key)+"/export"; render();
    if(!["saved","imported"].includes(key)&&d.trials.some(t=>["running","queued"].includes(t.status))) poll=setTimeout(load,2000);
  } catch(err){ if(key!==selection)return; $("message").textContent=err.message; $("evidence").replaceChildren(); $("export").hidden=true; }
}
$("new").onclick=$("setupNav").onclick=()=>page(true); $("compareNav").onclick=()=>page(false);
$("close").onclick=()=>$("drawer").close(); $("experiment").onchange=e=>{selection=e.target.value;load();};
$("evidence").onclick=e=>{const b=e.target.closest("button");if(!b)return;const ids=b.dataset.group?b.dataset.group.split(","):[b.dataset.trial];const t=current.trials.find(t=>t.id===ids[0]);if(t)showDetail(t,ids);};
$("import").onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>25e6)throw Error("Export exceeds 25 MB.");
  const d=JSON.parse(await file.text());if(d.schema!=="firmwarebench.experiment.v1"||!Array.isArray(d.trials)||!Array.isArray(d.comparison)||!d.config||d.trials.some(t=>!t.metrics||!Array.isArray(t.events)))throw Error("Select a FirmwareBench v1 export.");
  imported=d;await list("imported");await load();}catch(err){$("message").textContent=err.message;}};
(async()=>{try{catalog=await api("/api/catalog");configure();await list("saved");await load();}catch(err){$("message").textContent=err.message;}})();



