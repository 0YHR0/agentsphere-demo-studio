/* Recorded controls and training observations; no synthetic performance scores. */
window.StudioVisuals=window.StudioVisuals||{};
window.StudioVisuals.order_router=(()=>{
 const tasks=['daily','monthly','customer'],labels=['日报','分类汇总','客户对账'];
 const tools=['整表','流式','分块','SQLite'];
 const steps=['orders_prepare','orders_baseline','orders_train','orders_evaluate','orders_checkpoint','orders_cleanup'];
 const titles=['准备环境','测对照组','开始训练','验证最终效果','保存模型','回收沙箱'];
 const finite=n=>typeof n==='number'&&Number.isFinite(n);
 const f=(n,p=3)=>finite(n)?n.toFixed(p):'—';
 const pp=n=>finite(n)?(n>0?'+':'')+n.toFixed(n!==0&&Math.abs(n)<.01?4:2)+' pp':'—';
 const avg=(rows,key)=>rows.length?rows.reduce((s,r)=>s+r[key],0)/rows.length:undefined;
 let cached='',starting=false,roundChoice=null,panel='probability',controlSet='auto',runId='';
 function controls(rows){return Object.fromEntries(['initial','rule'].map(route=>{const r=(rows||[]).filter(x=>x.route===route);return [route,r.length?{count:r.length,correct:r.filter(x=>x.correct).length,mean_reward:avg(r,'reward'),mean_wall_s:avg(r,'wall_s'),mean_peak_rss_mib:avg(r,'peak_rss_mib')}:null];}));}
 function presentResult(id,result,run){
  if(!result)return null;
  if(id==='orders_baseline'){
   const rows=controls(result.calibration);
   return {table:{caption:'对照组 · 训练前校准集 · 不更新参数',columns:[['route','策略'],['correct','正确'],['score','基准得分'],['time','耗时'],['rss','峰值内存']].map(([key,label])=>({key,label})),rows:['initial','rule'].filter(k=>rows[k]).map(k=>{const r=rows[k];return {route:k==='initial'?'初始策略（固定整表）':'人工规则',correct:r.correct+'/'+r.count,score:f(r.mean_reward,4),time:f(r.mean_wall_s*1000,1)+' ms',rss:f(r.mean_peak_rss_mib,1)+' MiB'};})}};
  }
  if(id==='orders_train')return {table:{caption:'强化学习 · 每轮6次执行后更新概率',columns:[['round','轮次'],['count','执行次数'],['score','本轮平均分'],['change','最大单项概率变化']].map(([key,label])=>({key,label})),rows:(result.history||[]).map(row=>{const trace=(result.display||run?.display)?.trace?.find(t=>t.step===row.step);return {round:row.step,count:row.samples.length,score:f(row.mean_reward,4),change:trace?f(Math.max(...trace.delta_pp.flat().map(Math.abs)),2)+' pp':'未验证'};})}};
  if(id==='orders_evaluate'&&result.presentation)return {...result.presentation,table:{...result.presentation.table,caption:'最终对照 · 同一新文件验证集 · 每组12次'}};
  return null;
 }
 function render(host,ctx){
  const {state,escapeHTML:esc}=ctx,run=state.scenario_runs?.order_reports||{},history=run.history||[],display=run.display||{};
  if(runId!==run.run_id){runId=run.run_id;roundChoice=null;controlSet='auto';panel='probability';}
  const rounds=Number(run.settings?.rounds||state.config.orders_rounds||12),comparison=run.comparison||{};
  const jobs=(state.jobs||[]).filter(j=>j.workflow==='order_reports-v1'&&j.scenario_sandbox_id===run.sandbox_id&&(!j.run_id||j.run_id===run.run_id));
  const last=jobs.at(-1),busy=jobs.some(j=>j.status==='running'),failed=last?.status==='failed';
  const next=run.deleted?0:!run.installed?0:!run.calibration?1:history.length<rounds?2:!run.comparison?3:!run.checkpoint_verified?4:5;
  const setup=!state.config.api_key_configured||!state.config.gateway_id||!state.config.gateway_url||!!state.sdk?.errors?.length;
  const needsTemplate=!state.config.orders_template_ref;
  const key=JSON.stringify([run,state.busy,last?.error,last?.status,setup,needsTemplate,starting,roundChoice,panel,controlSet]);
  if(cached===key&&host.dataset.mounted==='order_router')return;cached=key;host.dataset.mounted='order_router';
  const opened=new Set([...host.querySelectorAll('details[open]')].map(el=>el.dataset.detail));
  const split=controlSet==='auto'?(comparison.initial?'heldout':'calibration'):controlSet;
  const control=split==='heldout'?comparison:(display.control_calibration||controls(run.calibration));
  const selectedRound=history.find(h=>h.step===roundChoice)||history.at(-1);
  const trace=display.trace?.find(t=>t.step===selectedRound?.step),trained=comparison.trained;
  const complete=[!!run.installed,!!run.calibration,history.length>=rounds,!!comparison.outcome,!!run.checkpoint_verified,!!run.deleted];
  const action=setup?'连接环境':needsTemplate?'配置模板':run.deleted?'新一轮实验':(failed?'重试 · ':'')+titles[next];
  const outcome={better:'RL 得分高于人工规则',worse:'RL 未优于人工规则',similar:'RL 与人工规则接近'}[comparison.outcome];
  const allCorrect=['initial','rule','trained'].every(k=>comparison[k]?.count>0&&comparison[k].correct===comparison[k].count);
  const progress=busy&&last?.case==='orders_evaluate'?'验证 '+(run.partial_evaluation?.length||0)+'/36':busy?'执行中':run.deleted?'已完成':'步骤 '+(next+1)+'/6';
  host.innerHTML=`
   <header class="orders-intro"><h1>订单报表：对照组 vs 强化学习</h1><span>算对报表，再优化时间与内存</span></header>
   <div class="experiment-toolbar"><ol class="experiment-steps" aria-label="演示进度">${['环境','对照','训练','验证','保存','回收'].map((s,i)=>`<li class="${complete[i]?'done':i===next?'current':''}" ${i===next&&!run.deleted?'aria-current="step"':''}>${complete[i]?'✓ ':''}${s}</li>`).join('')}</ol><div><span role="status">${progress}</span><button id="orders-next" class="primary" ${state.busy||starting?'disabled':''}>${esc(action)}</button>${busy?'<button id="orders-stop" class="quiet">停止</button>':'<button id="orders-settings" class="quiet">配置</button>'}</div></div>
   ${last?.error?`<div class="orders-error" role="alert">${esc(last.error)}</div>`:''}
   <div class="experiment-groups">
    <section class="experiment-card controls" aria-labelledby="control-title"><header><h2 id="control-title">对照组</h2><span>不更新概率</span></header><div class="control-split"><label for="orders-control-set">测量数据</label><select id="orders-control-set"><option value="calibration" ${split==='calibration'?'selected':''}>训练前基准 · 校准集</option><option value="heldout" ${split==='heldout'?'selected':''} ${comparison.initial?'':'disabled'}>最终复测 · 同一验证集</option></select></div>
     <div class="experiment-table"><table><thead><tr><th>策略</th><th>得分</th><th>耗时</th><th>内存</th></tr></thead><tbody>${[['initial','初始策略','固定选整表'],['rule','人工规则','按任务选工具']].map(([k,label,note])=>{const r=control[k];return `<tr><th scope="row">${label}<small>${note}</small></th><td>${f(r?.mean_reward,4)}</td><td>${r?f(r.mean_wall_s*1000,1)+' ms':'—'}</td><td>${r?f(r.mean_peak_rss_mib,1)+' MiB':'—'}</td></tr>`;}).join('')}</tbody></table></div>
     <div class="experiment-foot"><span>${control.initial?control.initial.correct+'/'+control.initial.count+'、'+control.rule.correct+'/'+control.rule.count+' 正确 · ':''}${split==='heldout'?'与右侧使用相同文件':'校准集不与右侧最终分数直接相减'}</span><button class="text-link" data-sdk="orders_baseline">基准 SDK</button></div>
    </section>
    <section class="experiment-card treatment" aria-labelledby="rl-title"><header><h2 id="rl-title">强化学习</h2><span>${history.length} / ${rounds} 轮 · ${history.reduce((n,h)=>n+h.samples.length,0)} 次训练执行</span></header><div class="experiment-final"><div><span>最终得分 · 新文件验证</span><strong id="orders-final-score">${f(trained?.mean_reward,4)}</strong></div><div class="experiment-final-metrics"><span>正确 <b>${trained?trained.correct+'/'+trained.count:'—'}</b></span><span>耗时 <b>${trained?f(trained.mean_wall_s*1000,1)+' ms':'—'}</b></span><span>内存 <b>${trained?f(trained.mean_peak_rss_mib,1)+' MiB':'—'}</b></span></div></div><div class="orders-verdict" role="status">${trained?(allCorrect?outcome:'存在报表错误，暂不判断收益'):'训练完成后，在新文件上测最终得分'}</div><div class="experiment-foot"><span>采样工具 → 沙箱评分 → 更新概率</span><div><button class="text-link" data-sdk="orders_train">训练 SDK</button><button class="text-link" data-sdk="orders_evaluate">验证 SDK</button></div></div></section>
   </div>
   <section class="experiment-history"><header><div><h2>训练过程</h2><span>初始概率均为 25%</span></div><label>轮次 <select id="orders-round" ${history.length?'':'disabled'}>${history.length?history.map(h=>`<option value="${h.step}" ${h.step===selectedRound?.step?'selected':''}>第 ${h.step} 轮 · 平均分 ${f(h.mean_reward,4)}</option>`).join(''):'<option>尚未训练</option>'}</select></label></header>
    <div class="experiment-tabs" role="tablist" aria-label="训练记录"><button id="orders-tab-probability" role="tab" aria-controls="orders-probability-panel" aria-selected="${panel==='probability'}" data-panel="probability">概率变化</button><button id="orders-tab-results" role="tab" aria-controls="orders-samples-panel" aria-selected="${panel==='results'}" data-panel="results">${selectedRound?selectedRound.samples.length:6} 次执行结果</button></div>
    <div id="orders-probability-panel" role="tabpanel" aria-labelledby="orders-tab-probability" ${panel==='probability'?'':'hidden'}>${trace?`<div class="experiment-table"><table class="probability-table"><thead><tr><th>任务</th>${tools.map(t=>`<th>${t}</th>`).join('')}</tr></thead><tbody>${tasks.map((t,i)=>`<tr><th scope="row">${labels[i]}</th>${tools.map((tool,a)=>`<td><strong>${f(trace.after[i][a]*100,1)}%</strong><small class="${trace.delta_pp[i][a]>0?'up':trace.delta_pp[i][a]<0?'down':''}">${pp(trace.delta_pp[i][a])}</small></td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="experiment-note">第 ${trace.step} 轮更新后概率 · 增减相对本轮更新前（pp = 百分点）</p>`:`<p class="experiment-empty">${display.trace_error?'概率记录校验失败，未展示推算值。':'执行训练后，展示每轮概率变化。'}</p>`}</div>
    <div id="orders-samples-panel" role="tabpanel" aria-labelledby="orders-tab-results" ${panel==='results'?'':'hidden'}>${selectedRound?`<div class="experiment-table"><table><thead><tr><th>任务</th><th>工具</th><th>得分</th><th>耗时</th><th>内存</th></tr></thead><tbody>${selectedRound.samples.map(s=>`<tr><th scope="row">${labels[tasks.indexOf(s.task)]}</th><td>${tools[s.action]}</td><td>${f(s.reward,4)}${s.correct?'':' · 错误'}</td><td>${f(s.wall_s*1000,1)} ms</td><td>${f(s.peak_rss_mib,1)} MiB</td></tr>`).join('')}</tbody></table></div>`:'<p class="experiment-empty">暂无执行记录</p>'}</div>
   </section>
   <details class="orders-details" data-detail="score"><summary>评分规则<span>正确为前提 · 越快、越省内存，得分越高</span></summary><div class="orders-detail-content"><p><strong>正确：1 ÷ (1 + 0.6 × 耗时/T + 0.4 × 峰值内存/M)</strong>；错误或执行超时：0 分。</p><p>每次执行单独评分，再取平均。T/M 是固定标尺：日报 0.25秒/32MiB，分类汇总 1.5秒/48MiB，客户对账 0.8秒/48MiB；不是硬性资源上限。</p><p>初始策略的四种概率均为25%，评估按固定顺序选整表。人工规则：≤2000行用整表、分类汇总用流式、客户对账用SQLite。</p><p>正确性验证全部总额与分组。时间不含SDK网络与数据生成，内存为进程峰值RSS；合成数据的小样本实测不代表生产收益。RL与规则得分差在±0.01内标为接近，非统计显著性检验。</p><p>每轮概率用已记录的reward和更新公式复算，并核对更新前后参数hash；不重新运行沙箱或生成性能成绩。</p></div></details>
   ${run.checkpoint_verified?'<div class="experiment-download"><button class="secondary" id="orders-download">下载模型与记录</button></div>':''}`;
  host.querySelectorAll('details[data-detail]').forEach(el=>el.open=opened.has(el.dataset.detail));
  const refresh=()=>{cached='';render(host,ctx);};
  host.querySelector('#orders-control-set').onchange=e=>{controlSet=e.target.value;refresh();};
  host.querySelector('#orders-round').onchange=e=>{roundChoice=Number(e.target.value);refresh();};
  host.querySelectorAll('[data-panel]').forEach(el=>el.onclick=()=>{panel=el.dataset.panel;refresh();});
  host.querySelectorAll('[data-sdk]').forEach(el=>el.onclick=async()=>{await ctx.selectCase(el.dataset.sdk,true);document.getElementById('code-details').open=true;});
  host.querySelector('#orders-settings')?.addEventListener('click',ctx.openSettings);
  host.querySelector('#orders-next').onclick=async()=>{if(starting||state.busy)return;if(setup){ctx.openSetup();return;}if(needsTemplate){ctx.openSettings();return;}starting=true;host.querySelector('#orders-next').disabled=true;try{await ctx.selectCase(steps[next]);await ctx.action(steps[next]);}finally{starting=false;cached='';}};
  host.querySelector('#orders-stop')?.addEventListener('click',ctx.stop);
  host.querySelector('#orders-download')?.addEventListener('click',async()=>{await ctx.selectCase('orders_checkpoint');document.getElementById('download-artifact').click();});
 }
 return {render,presentResult,groups:[{title:'对照组',cases:steps.slice(0,2)},{title:'强化学习',cases:steps.slice(2)}]};
})();
