'use strict';
const $ = id => document.getElementById(id);
const form = $('config-form');
let state = null, catalog = [], selected = 'command', group = '全部', wizard = 0;
let templateOptionsKey = '';
let basicSelected='command', businessSelected=null;
let packages=[], scenarios=[], activeScenario=null, businessSteps=[];
const caseMeta=id=>catalog.find(c=>c.id===id);
const currentScenario=()=>scenarios.find(s=>s.id===activeScenario)||scenarios[0];
function renderBusiness(){
 const scene=currentScenario();if(!scene)return;
 businessSteps=scene.steps.map(s=>[s.id,s.title,s.description]);
 $('scenario-title').textContent=scene.title;
 $('scenario-description').textContent=scene.description;
 $('scenario-outcome').textContent=scene.outcome;
 $('scenario-prerequisites').replaceChildren(...scene.prerequisites.map(s=>{const li=document.createElement('li');li.textContent=s;return li;}));
 $('scenario-picker').value=scene.id;
 const stepButton=([id,title],i)=>{
  const job=latestJob(id);
  return `<button data-business="${escapeHTML(id)}" class="${selected===id?'active':''}"><b>${String(i+1).padStart(2,'0')}</b><strong>${escapeHTML(title)}</strong><small>${job?escapeHTML(jobLabel(job)):'待执行'}</small></button>`;
 };
 const stepGroups=window.StudioVisuals?.[scene.visualizer]?.groups;
 $('business-steps').innerHTML=stepGroups?stepGroups.map(g=>`<section class="business-step-group"><h3>${escapeHTML(g.title)}</h3><div>${businessSteps.filter(s=>g.cases.includes(s[0])).map(s=>stepButton(s,businessSteps.indexOf(s))).join('')}</div></section>`).join(''):businessSteps.map(stepButton).join('');
 document.querySelectorAll('[data-business]').forEach(el=>el.onclick=()=>selectCase(el.dataset.business,true));
 const i=businessSteps.findIndex(s=>s[0]===selected), step=businessSteps[Math.max(0,i)];
 $('business-position').textContent='步骤 '+String(Math.max(0,i)+1).padStart(2,'0')+' / '+String(businessSteps.length).padStart(2,'0');
 $('business-purpose').textContent=step[2];$('business-next').disabled=i===businessSteps.length-1;
 renderExperience();
}
function renderExperience(){
 const scene=currentScenario(), key=view==='scenario'?(scene?.visualizer||''):'';
 const visual=window.StudioVisuals?.[key], host=$('scenario-visual');
 document.body.classList.toggle('orders-friendly',key==='order_router');
 if(state&&$('workbench').dataset.visualizer!==key){
   $('workbench').dataset.visualizer=key;
   $('code-details').open=!visual;$('raw-details').open=!visual;
   $('scenario-technical-details').open=!visual;
   const templateField=scene?.fields.find(f=>f.key.endsWith('_template_ref'));
   $('scenario-config-details').open=key==='order_router'?false:!visual||!state?.config?.api_key_configured||!(state?.config?.[templateField?.key]||state?.config?.ready_template_id);
 }
 host.hidden=!visual;
 if(visual&&state)visual.render(host,{state,scene,selected,escapeHTML,selectCase,action,
   openSettings:()=>{$('scenario-config-details').open=true;$('scenario-config-details').scrollIntoView({behavior:'smooth'});},
   openSetup:()=>setView('setup'),stop:()=>document.getElementById('stop').click()});
}
function renderGenericScene(){
 const scene=view==='scenario'?currentScenario():packages.find(p=>p.id===caseMeta(selected)?.package);if(!scene)return;
 const host=$('generic-scene-fields');host.hidden=false;
 const fields=view==='scenario'?scene.fields:scene.fields.filter(f=>caseMeta(selected)?.settings.includes(f.key));
 const scopeKey=scene.id+':'+(view==='scenario'?'all':selected);
 if(host.dataset.package!==scopeKey){
  host.dataset.package=scopeKey;
  host.innerHTML=fields.map(f=>{
   const control=f.kind==='select'?`<select data-generic-key="${escapeHTML(f.key)}">${f.choices.map(([value,label])=>`<option value="${escapeHTML(value)}">${escapeHTML(label)}</option>`).join('')}</select>`:`<input data-generic-key="${escapeHTML(f.key)}" type="${f.kind==='secret'?'password':f.kind==='number'?'number':'text'}" autocomplete="off">`;
   return `<label>${escapeHTML(f.label)}${control}<small>${escapeHTML(f.help||'仅用于本步骤；保存不执行云端操作')}${f.kind==='secret'&&state?.config[f.key+'_configured']?' · 已保存，留空保留':''}</small></label>`;
  }).join('');
 }
 const draft=sceneDraft(view==='scenario'?scene.config_action:selected);
 host.querySelectorAll('[data-generic-key]').forEach(el=>{el.value=draft[el.dataset.genericKey]||'';el.disabled=!!state.busy||saving;});
 $('scene-settings-title').textContent=scene.title+' · 场景配置';
 $('scene-save-state').textContent='仅本机保存 · '+scene.title;
 $('scene-save-note').textContent='保存不会发起云端请求。仅准备状态不执行最终演示动作；模型任务只在选择执行时调用。密钥留空保留，报告不回显密钥。';
}

const executionCases = new Set();
const executionDrafts = {};
function executionFor(id){return executionDrafts[id]||{command_user:state?.config.command_user||'root',command_cwd:state?.config.command_cwd||'/'};}
let sceneFields={};
const sceneDrafts={};
const sceneScope=id=>caseMeta(id)?.kind==='scenario'?caseMeta(id).package:id;
function sceneDraft(id){
  const scope=sceneScope(id);
  if(!sceneDrafts[scope]){
    const keys=scenarios.find(s=>s.id===scope)?.fields.map(f=>f.key)||sceneFields[id]||[];
    sceneDrafts[scope]=Object.fromEntries(keys.map(k=>[k,packages.some(s=>s.fields.some(f=>f.key===k&&f.kind==='secret'))?'':state?.config[k]||'']));
  }
  return sceneDrafts[scope];
}
function renderScene(){
 const available=view==='scenario'||!!sceneFields[selected];$('scene-settings').hidden=!available;
 if(!available||!state)return;
 renderGenericScene();
}
async function saveScene(id=selected){
  if(view==='scenario')id=currentScenario().config_action;
  if(!sceneFields[id])return true;
  if(saving||state?.busy)return false;
  saving=true;renderState();
  try{
    const draft=sceneDraft(id),values=Object.fromEntries(sceneFields[id].map(k=>[k,draft[k]||'']));
    await request('/api/scenario-config',{case:id,values});
    for(const f of packages.find(p=>p.id===caseMeta(id)?.package)?.fields||[]){if(f.kind==='secret')draft[f.key]='';} 
    state=await request('/api/state');csrf=state.csrf;
    renderScene();$('scene-save-state').textContent='本场景配置已保存在本机';return true;
  }catch(e){toast(e.message);return false;}finally{saving=false;renderState();}
}
function renderExecution(){
  $('execution-settings').hidden=!executionCases.has(selected);
  if(executionCases.has(selected)){const v=executionFor(selected);$('execution-user').value=v.command_user;$('execution-cwd').value=v.command_cwd;}
  renderCode();
}
function renderCode(){
  if(!selectedInfo)return;
  const prefix=executionCases.has(selected)?'# 本次场景参数：映射到 SDK 的 user / cwd，不修改模板或环境配置\nexecution = '+JSON.stringify(executionFor(selected),null,2)+'\n\n':'';
  $('code').textContent=prefix+selectedInfo.code;
}
let csrf = '', saving = false, configLoaded = false, selectedInfo = null, view = 'demo';
const icons = {'准备':'◉','模板':'▱','沙箱':'⬡','文件':'▤','连续性':'↻','OpenClaw':'⌘','清理':'↗','健康检查':'♡'};
const statusNames = {skipped:'未执行（无需操作）',passed:'执行成功',failed:'失败',running:'执行中',cancelled:'已停止',interrupted:'已中断'};
const jobLabel = job => job.mode==='prepare' && job.status==='passed' ? '已准备' : statusNames[job.status]||job.status;
const escapeHTML = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = value => value ? new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) : '—';
function toast(message){$('toast').textContent=message;$('toast').classList.add('show');setTimeout(()=>$('toast').classList.remove('show'),5000);}
async function request(path, body){
  const opts=body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json','X-Studio-CSRF':csrf},body:JSON.stringify(body)};
  const r=await fetch(path,{...opts,signal:AbortSignal.timeout(15000)});
  const data=await r.json();if(!r.ok)throw Error(data.error||'请求失败');return data;
}
function setView(next){
  view=['demo','setup','resources','scenario'].includes(next)?next:'demo';
  document.querySelectorAll('.view').forEach(el=>el.hidden=el.id!=='view-'+view);
  document.querySelectorAll('[data-view]').forEach(el=>el.classList.toggle('active',el.dataset.view===view));
  $('page-label').textContent={demo:'基础能力',setup:'环境配置',resources:'演示资源',scenario:'客户场景'}[view];
  const scenario=view==='scenario';
  if(view==='demo'||scenario){
    const host=$(scenario?'scenario-workbench-host':'basic-workbench-host');host.append($('workbench'));
    if(scenario)$('scenario-config-host').append($('scene-settings'));
    else $('execution-settings').before($('scene-settings'));
    const target=scenario?businessSelected:basicSelected;
    if(selected!==target)selectCase(target);
    renderScene();
    $('prepare').hidden=false;$('run').textContent=scenario?'执行本业务步骤 ↗':'准备并演示 ↗';
    renderBusiness();
  }
  history.replaceState(null,'','#'+view+(view==='scenario'?'/'+activeScenario:''));window.scrollTo({top:0,behavior:'instant'});
}
function renderCards(){
  const query=$('search').value.trim().toLowerCase();
  const filtered=catalog.filter(c=>c.kind==='capability').filter(c=>(group==='全部'||group===c.group)&&(`${c.title} ${c.description} ${c.id}`).toLowerCase().includes(query));
  $('case-grid').innerHTML=filtered.map(c=>{
    const job=[...(state?.jobs||[])].reverse().find(j=>j.case===c.id);
    return `<button class="case-card ${c.id===selected?'active':''}" data-select="${c.id}"><div class="card-top"><span class="card-icon">${icons[c.group]||'◈'}</span><span class="number">${String(catalog.indexOf(c)+1).padStart(2,'0')} / ${escapeHTML(c.group)}</span></div><strong>${escapeHTML(c.title)}</strong><span class="go">↗</span><p>${escapeHTML(c.expected)}</p>${job?`<span class="card-state">${escapeHTML(jobLabel(job))}</span>`:''}</button>`;
  }).join('')||'<p>没有匹配的能力。</p>';
  document.querySelectorAll('[data-select]').forEach(el=>el.onclick=()=>selectCase(el.dataset.select,true));
}
async function selectCase(id, scroll=false){
  selected=id;if(caseMeta(id)?.kind==='scenario'){businessSelected=id;activeScenario=caseMeta(id).package;}else basicSelected=id;renderCards();renderBusiness();
  try{
    const info=await request('/api/case/'+id);if(selected!==id)return;
    selectedInfo=info;const c=info.case;
    $('case-group').textContent=c.group.toUpperCase()+' / CAPABILITY';
    $('case-title').textContent=c.title;$('case-description').textContent=c.description;
    $('expected').textContent=c.expected;renderExecution();renderScene();
    $('plan').replaceChildren(...info.plan.steps.map(s=>{const li=document.createElement('li');li.textContent=s;return li;}));
    renderResult();if(scroll){if(view==='scenario')$('scenario-technical-details').open=true;$('workbench').scrollIntoView({behavior:'smooth',block:'start'});}
  }catch(e){toast(e.message);}
}
function latestJob(id){
 const meta=caseMeta(id), sid=state?.scenario_runs?.[meta?.package]?.sandbox_id;
 return [...(state?.jobs||[])].reverse().find(j=>j.case===id&&(meta?.kind!=='scenario'||j.workflow===meta.package+'-v1'&&j.scenario_sandbox_id===sid)&&(!meta?.resource_state_key||!j.result?.sandbox_id||j.result.sandbox_id===state?.[meta.resource_state_key]));
}
function renderResult(){
  const job=latestJob(selected);
  const resourceKey=caseMeta(selected)?.resource_state_key;
  const activeId=resourceKey!=null?(resourceKey?state?.[resourceKey]:null):caseMeta(selected)?.kind==='scenario'?state?.scenario_runs?.[caseMeta(selected).package]?.sandbox_id:selected==='liveness'?state?.liveness_test?.sandbox_id:state?.active_sandbox;
  const active=(state?.sandboxes||[]).find(s=>s.sandbox_id===activeId&&!s.deleted);
  $('same-sandbox').textContent=active?'Sandbox: '+active.sandbox_id:'';
  $('result-status').textContent=job?jobLabel(job):'待执行';
  $('result-status').className='pill '+(job?.status||'neutral');
  $('result-empty').hidden=!!job;$('result').hidden=!job;
  const result=job?.result;
  const renderer=window.StudioVisuals?.[currentScenario()?.visualizer];
  const presentation=(caseMeta(selected)?.kind==='scenario'?renderer?.presentResult?.(selected,result,state?.scenario_runs?.[caseMeta(selected).package]):null)||result?.presentation;
  $('result-metrics').hidden=!presentation?.metrics?.length;
  $('result-metrics').innerHTML=(presentation?.metrics||[]).map(m=>`<article><small>${escapeHTML(m.label)}</small><strong>${escapeHTML(m.value)}</strong></article>`).join('');
  const series=presentation?.series, points=series?.points||[];
  $('result-chart').hidden=!points.length;
  if(points.length){
    const coords=points.map((p,i)=>`${35+(i/Math.max(1,points.length-1))*570},${150-Math.max(0,Math.min(1,Number(p.y)))*120}`);
    $('result-chart').innerHTML=`<p>${escapeHTML(series.label)}</p><svg viewBox="0 0 640 185" role="img" aria-label="训练reward曲线"><path d="M35 25V150H615" fill="none" stroke="#cbd0d8"/><text x="8" y="32">1</text><text x="8" y="155">0</text><polyline points="${coords.join(' ')}" fill="none" stroke="#c7000b" stroke-width="2.5"/>${coords.map((c,i)=>`<circle cx="${c.split(',')[0]}" cy="${c.split(',')[1]}" r="4" fill="#c7000b"><title>第${i+1}轮 reward ${escapeHTML(points[i].y)}</title></circle>`).join('')}<text x="35" y="178">第1轮</text><text x="550" y="178">第${points.length}轮</text></svg>`;
  }else $('result-chart').replaceChildren();
  const table=presentation?.table;$('result-table').hidden=!table;
  $('result-table').innerHTML=table?`<table>${table.caption?'<caption>'+escapeHTML(table.caption)+'</caption>':''}<thead><tr>${table.columns.map(c=>`<th>${escapeHTML(c.label)}</th>`).join('')}</tr></thead><tbody>${table.rows.map(row=>`<tr>${table.columns.map(c=>`<td>${escapeHTML(row[c.key])}</td>`).join('')}</tr>`).join('')}</tbody></table>`:'';
  let formatted=result?JSON.stringify({...result,presentation:undefined},null,2):'';
  if(result?.prepared)formatted='所需状态已准备，正式 SDK 演示动作尚未执行。\n\n'+JSON.stringify(result.plan,null,2);
  else if(result?.artifact)formatted='业务交付物\n\n'+result.artifact+'\n\n—— 执行证据 ——\n文件：'+result.artifact_path+(result.sandbox_id?'\nSandbox：'+result.sandbox_id:'')+(result.model_calls!==undefined?'\n模型调用：'+result.model_calls+' 次\n退出码：'+result.exit_code:'\nSHA256：'+result.sha256)+(result.model_calls!==undefined?'\n真实模型 Key：仅在本机':'');
  else if(result?.stdout)formatted=result.stdout+'\nexit_code: '+result.exit_code+'\nSandbox: '+result.sandbox_id;
  else if(result?.outcome)formatted='探针验证结果：'+({marked_error:'已识别异常并标记 Error',service_recovered:'检测到服务恢复',not_detected:'未确认异常识别'}[result.outcome]||result.outcome)+'\n\n标记 Error 耗时：'+(result.detected_error_s??'未观察到')+' 秒\n业务自动恢复耗时：'+(result.service_restarted_s??'未观察到')+' 秒\nSandbox：'+result.sandbox_id+'\n\n'+result.note+'\n\n'+JSON.stringify(result,null,2);
  else if(result?.log_entries)formatted='Template: '+result.template_id+'\nBuild: '+result.build_id+'\n状态：'+result.status+'\n\n'+(result.log_entries.map(e=>'['+e.timestamp+'] '+e.level+' '+e.message).join('\n')||'本次接口未返回日志。')+'\n\n原因：'+(result.reason||'无')+(result.livenessProbe?'\n\n服务端回显的存活探针：\n'+JSON.stringify({invoke:result.invoke,livenessProbe:result.livenessProbe},null,2):'');
  $('download-artifact').hidden=!(job?.status==='passed'&&result?.artifact);
  $('download-artifact').textContent='下载 '+(result?.artifact_path?.split('/').pop()||'本次交付物');
  $('result').textContent=job?(job.error||formatted||'SDK 正在执行；请查看下面的执行过程。'):'';
  $('result-time').textContent=job?'本次记录 '+time(job.finished_at||job.started_at):'尚未执行';
  $('events').textContent=(job?.events?.map(e=>`[${time(e.at)}] ${e.message}`).join('\n')||'等待演示开始。')+(job?.operations?.length?'\n\n—— SDK 操作 / 已捕获 HTTP 返回（脱敏）——\n'+JSON.stringify(job.operations,null,2):'');
  $('event-count').textContent=(job?.events?.length||0)+' 条事件';
  const blocked=!!state?.busy||saving||!state?.config?.api_key_configured||!!state?.sdk?.errors?.length;
  $('run').disabled=blocked;$('prepare').disabled=blocked;$('stop').disabled=!state?.busy;
  $('execution-user').disabled=!!state?.busy||saving;$('execution-cwd').disabled=!!state?.busy||saving;
  $('save-scene').disabled=!!state?.busy||saving;
  const setupJob=[...(state?.jobs||[])].reverse().find(j=>j.case==='check');
  $('setup-result').hidden=!setupJob;
  $('raw-details').hidden=!job;
  renderExperience();
  if(setupJob)$('setup-result').textContent=setupJob.error||JSON.stringify(setupJob.result||{status:setupJob.status},null,2);
}
function renderResources(){
  const resources=[...(state?.sandboxes||[]).map(r=>({...r,kind:'Sandbox',id:r.sandbox_id})),...(state?.templates||[]).map(r=>({...r,kind:'Template',id:r.template_id}))];
  const count=resources.filter(r=>!r.deleted).length;
  $('resource-count').textContent=String(count);$('owned-summary').textContent=`${count} 个待清理资源 · 共创建 ${resources.length} 个`;
  $('cleanup').disabled=!count||!!state?.busy||saving;
  $('resource-rows').innerHTML=resources.map(r=>`<tr><td>${r.kind}<span class="small">本工具创建 · ${escapeHTML(r.scope||r.scene||'basic')}</span></td><td class="mono">${escapeHTML(r.id)}</td><td><span class="pill ${r.deleted?'neutral':String(r.detailed_state).toLowerCase()==='error'?'failed':'passed'}">${escapeHTML(r.deleted?'已删除':r.detailed_state||r.state||r.status||'已创建')}</span>${r.error_message?`<span class="small">${escapeHTML(r.error_message)}</span>`:''}</td><td class="mono">${escapeHTML(r.kind==='Sandbox'?r.template_id:r.build_id)}<span class="small">${escapeHTML(r.end_at?'到期：'+time(r.end_at):'')}</span></td></tr>`).join('')||'<tr><td colspan="4">尚未创建云端资源。填写的外部模板不会被加入这里。</td></tr>';
  $('job-history').innerHTML=[...(state?.jobs||[])].reverse().slice(0,20).map(j=>`<div class="history-row"><button data-job-case="${escapeHTML(j.case)}">${escapeHTML(CATALOGTitle(j.case))}</button><span>${j.mode==='prepare'?'状态准备':'SDK 演示'}</span><time>${escapeHTML(time(j.finished_at||j.started_at))}</time><span class="pill ${escapeHTML(j.status)}">${escapeHTML(jobLabel(j))}</span></div>`).join('')||'<p>还没有演示记录。</p>';
  document.querySelectorAll('[data-job-case]').forEach(el=>el.onclick=()=>{if(el.dataset.jobCase==='cleanup')return;setView(caseMeta(el.dataset.jobCase)?.kind==='scenario'?'scenario':'demo');selectCase(el.dataset.jobCase,true);});
}
function CATALOGTitle(id){return catalog.find(c=>c.id===id)?.title||(id==='cleanup'?'资源清理':id);}
function renderState(){
  if(!state)return;
  const c=state.config, ready=c.api_key_configured&&c.gateway_id&&c.gateway_url;
  $('setup-callout').hidden=!!ready;$('setup-dot').textContent=ready?'':'•';
  $('connection').textContent=state.busy?'SDK 执行中':'本地后台已连接';
  $('sdk-side').textContent=`E2B ${state.sdk.versions.e2b} · Patch ${state.sdk.versions['agentsphere-e2b-patch']}`;
  $('key-state').textContent=c.api_key_configured?'已保存在本机；留空保留已有 Key。':'尚未保存 API Key';
  $('version-check').innerHTML=Object.entries(state.sdk.versions).map(([k,v])=>`<div class="version-row"><span>${escapeHTML(k)}</span><b>${escapeHTML(v)}</b></div>`).join('')+`<div class="version-row"><span>官网 patch</span><b>${state.sdk.patch_loaded?'已加载 ✓':'未加载'}</b></div>`+(state.sdk.errors.length?`<p>${escapeHTML(state.sdk.errors.join('；'))}</p>`:'');
  $('check-connection').disabled=!!state.busy||saving;
  const templateJob=[...(state.jobs||[])].reverse().find(j=>['check','template_list'].includes(j.case)&&j.status==='passed');
  const templates=(templateJob?.result?.templates||[]).filter(t=>String(t.buildStatus).toLowerCase()==='ready'&&t.gatewayID===c.gateway_id);
  const optionsKey=JSON.stringify(templates.map(t=>[t.templateID,t.buildID,t.names]));
  if(optionsKey!==templateOptionsKey){
    templateOptionsKey=optionsKey;
    $('template-options').replaceChildren(...templates.map(t=>new Option((t.names||[]).join(',')+' · Ready',t.buildID?t.templateID+':'+t.buildID:t.templateID)));
  }
  $('load-templates').disabled=!!state.busy||saving;
  renderResult();renderResources();renderCards();renderBusiness();
}
function fillForm(){
  if(configLoaded||!state)return;
  for(const el of form.elements){if(el.name&&state.config[el.name]!==undefined)el.value=state.config[el.name];}
  configLoaded=true;renderExecution();renderScene();renderTemplateSource();
}
function renderTemplateSource(){
  const mode=form.elements.template_source.value;
  $('existing-template-fields').hidden=mode==='build';
  $('build-template-fields').hidden=mode==='existing';
  for(const id of ['existing-template-fields','build-template-fields']){const panel=$(id);panel.querySelectorAll('input,select,textarea').forEach(el=>el.disabled=panel.hidden);}
  $('source-mode-note').textContent={
    existing:'使用你提供的 Ready 模板创建沙箱，无需构建新模板。只需填写下方的模板引用。',
    build:'从下方镜像创建并构建新模板。后续新建沙箱使用本次构建结果；即使本机以前保存过已有模板 ID，也不会使用它。',
    both:'现场提交新模板构建，同时用你提供的已有 Ready 模板创建沙箱，继续演示其他能力，无需等待本次 Build 完成。'
  }[mode];
}
function setWizard(step){
  wizard=Math.max(0,Math.min(3,step));
  document.querySelectorAll('[data-step]').forEach(el=>el.hidden=Number(el.dataset.step)!==wizard);
  document.querySelectorAll('[data-setup]').forEach(el=>el.classList.toggle('active',Number(el.dataset.setup)===wizard));
  $('wizard-prev').disabled=wizard===0;$('wizard-next').textContent=wizard===3?'进入能力演示 →':'下一步 →';
}
async function saveConfig(){
  if(saving)return false;saving=true;renderState();
  try{
    const values=Object.fromEntries(new FormData(form));
    await request('/api/config',values);
    form.elements.api_key.value='';
    state=await request('/api/state');csrf=state.csrf;
    $('setup-save-state').textContent='已保存 · '+new Date().toLocaleTimeString('zh-CN');toast('配置已保存在本机');return true;
  }catch(e){toast(e.message);return false;}finally{saving=false;renderState();}
}
async function action(id,mode='run'){
  if(saving||state?.busy)return;
  if((sceneFields[id]||view==='scenario')&&!await saveScene(id))return;
  saving=true;renderState();
  try{const payload={case:id,mode};if(executionCases.has(id))payload.execution=executionFor(id);
    await request('/api/action',payload);state=await request('/api/state');csrf=state.csrf;toast(mode==='prepare'?'正在准备所需状态…':'正在执行 SDK 演示…');}
  catch(e){toast(e.message);}finally{saving=false;renderState();}
}
async function poll(){
  try{state=await request('/api/state');csrf=state.csrf;fillForm();renderState();}
  catch(e){$('connection').textContent='后台未连接，请检查启动窗口';}
  setTimeout(poll,1200);
}
document.querySelectorAll('[data-view]').forEach(el=>el.onclick=()=>setView(el.dataset.view));
document.querySelectorAll('[data-setup]').forEach(el=>el.onclick=()=>setWizard(Number(el.dataset.setup)));
document.querySelectorAll('[data-case]').forEach(el=>el.onclick=()=>{setView('demo');selectCase(el.dataset.case,true);});
$('show-scenario').onclick=()=>setView('scenario');$('config-shortcut').onclick=()=>setView('setup');$('start-setup').onclick=()=>setView('setup');
$('wizard-prev').onclick=()=>setWizard(wizard-1);$('wizard-next').onclick=()=>wizard===3?setView('demo'):setWizard(wizard+1);
form.onsubmit=async e=>{e.preventDefault();await saveConfig();};
$('check-connection').onclick=async()=>{if(await saveConfig()){await action('check');}};
$('run').onclick=()=>action(selected);$('prepare').onclick=()=>action(selected,'prepare');
$('stop').onclick=async()=>{try{const r=await request('/api/stop',{});toast(r.note);}catch(e){toast(e.message);}};
$('cleanup').onclick=async()=>{await action('cleanup');};
$('search').oninput=renderCards;
$('save-scene').onclick=()=>saveScene();
$('scenario-setup').onclick=()=>setView('setup');
$('business-next').onclick=()=>{const i=businessSteps.findIndex(s=>s[0]===selected);selectCase(businessSteps[Math.min(i+1,businessSteps.length-1)][0],true);};
$('download-artifact').onclick=()=>{
 const job=latestJob(selected);
 if(job?.status!=='passed'||!job.result?.artifact)return;
 const url=URL.createObjectURL(new Blob([job.result.artifact],{type:job.result.artifact_path?.endsWith('.jsonl')?'application/x-ndjson;charset=utf-8':job.result.artifact_path?.endsWith('.json')?'application/json;charset=utf-8':'text/markdown;charset=utf-8'}));
 const a=document.createElement('a');a.href=url;a.download=job.result.artifact_path?.split('/').pop()||'delivery.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
for(const id of ['execution-user','execution-cwd'])$(id).oninput=()=>{executionDrafts[selected]={command_user:$('execution-user').value,command_cwd:$('execution-cwd').value};renderCode();};
$('template-source').onchange=renderTemplateSource;
$('preset-http-probe').onclick=()=>{$('build-probe-json').value=JSON.stringify({invoke:{protocol:'HTTP',port:18789},livenessProbe:{probeHandler:{httpGet:{path:'/health'}},probeConfig:{enabled:true,initialDelaySeconds:5,timeoutSeconds:3,periodSeconds:10,failureThreshold:3}}},null,2);};
$('preset-exec-probe').onclick=()=>{$('build-probe-json').value=JSON.stringify({livenessProbe:{probeHandler:{exec:{command:['/usr/bin/test','-f','/tmp/myapp-ready']}},probeConfig:{enabled:true,periodSeconds:15,failureThreshold:3}}},null,2);};
$('clear-build-probe').onclick=()=>{$('build-probe-json').value='';};
$('load-templates').onclick=async()=>{if(await saveConfig())await action('template_list');};
form.elements.region.onchange=()=>{const url=form.elements.api_url.value;if(!url||/^https:\/\/agentsandbox\.[a-z0-9-]+\.myhuaweicloud\.com$/.test(url))form.elements.api_url.value='https://agentsandbox.'+form.elements.region.value.trim()+'.myhuaweicloud.com';};
$('present').onclick=()=>{document.body.classList.toggle('present');$('present').textContent=document.body.classList.contains('present')?'退出演示模式':'演示模式';};
$('copy-code').onclick=async e=>{e.preventDefault();try{await navigator.clipboard.writeText($('code').textContent);toast('SDK 代码已复制');}catch(e){toast('请选中代码后复制');}};
document.addEventListener('keydown',e=>{if(e.key==='Escape'){document.body.classList.remove('present');$('present').textContent='演示模式';}});

$('scenario-picker').onchange=()=>{activeScenario=$('scenario-picker').value;businessSelected=currentScenario().steps[0].id;selectCase(businessSelected);renderScene();history.replaceState(null,'','#scenario/'+activeScenario);};
$('generic-scene-fields').oninput=e=>{const key=e.target.dataset.genericKey;if(key){sceneDraft(view==='scenario'?currentScenario().config_action:selected)[key]=e.target.value;$('scene-save-state').textContent='本场景有未保存修改';}};

async function init(){
  try{
    [catalog,packages]=await Promise.all([request('/api/catalog'),request('/api/packages')]);
    scenarios=packages.filter(p=>p.kind==='scenario').sort((a,b)=>Number(!!b.recommended)-Number(!!a.recommended));
    activeScenario=scenarios[0]?.id;businessSelected=currentScenario()?.steps[0]?.id;
    sceneFields=Object.fromEntries(catalog.filter(c=>c.settings?.length).map(c=>[c.id,c.settings]));
    catalog.filter(c=>c.execution_params).forEach(c=>executionCases.add(c.id));
    $('basic-count').textContent=catalog.filter(c=>c.kind==='capability').length;
    $('scenario-picker').innerHTML=scenarios.map(s=>`<option value="${escapeHTML(s.id)}">${escapeHTML(s.title)}</option>`).join('');
    $('filters').innerHTML=['全部',...new Set(catalog.filter(c=>c.kind==='capability').map(c=>c.group))].map((g,i)=>`<button data-group="${g}" class="${i===0?'active':''}">${g}</button>`).join('');
    document.querySelectorAll('[data-group]').forEach(el=>el.onclick=()=>{group=el.dataset.group;document.querySelectorAll('[data-group]').forEach(b=>b.classList.toggle('active',b===el));renderCards();});
    const route=location.hash.slice(1).split('/');
    if(route[0]==='scenario'&&scenarios.some(p=>p.id===route[1])){activeScenario=route[1];businessSelected=currentScenario().steps[0].id;}
    setView(route[0]||'demo');setWizard(0);await selectCase(selected);poll();
  }catch(e){toast('启动失败：'+e.message);}
}
init();
