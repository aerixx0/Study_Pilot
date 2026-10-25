"use strict";
const T = value => StudyI18n.text(value);
const V = value => StudyI18n.text(value);
const $ = (q, root=document) => root.querySelector(q);
const E = v => String(v ?? "").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let me=null, data=null, page="overview", authPage="login", recoveryCode="", history=[], preview=null, trace=[], sessions=[], authEpoch=0, accountServiceReady=true;
const drafts=new Map();
let renderedView=null, navigationRole=null, chatPending=false;
const names={overview:"学习概览",profile:"学习档案",tasks:"学习任务",plan:"学习计划",records:"学习记录",account:"账号设置",assistant:"对话",development:"开发进度"};
const labels={title:"任务标题",subject:"科目",due_date:"截止日期",estimated_minutes:"预计分钟",priority:"优先级",status:"状态",requires_computer:"需要电脑",notes:"备注",goals:"学习目标",weekly_hours:"每周小时",speed:"学习速度",preference:"学习偏好",max_session_minutes:"单次时长上限",levels:"各科基础",priorities:"科目优先级",availability:"每天时间和设备",study_date:"实际日期",duration:"实际分钟",note:"备注",minutes:"分钟",devices:"设备",task_id:"任务编号",date:"日期",reason:"原因",remaining_minutes:"未安排分钟",planned_minutes:"已安排分钟",goal_deadline:"目标期限",suggestion:"可调整方式"};
const actionNames={create_task:"创建任务",update_task:"修改任务",delete_task:"删除任务",update_profile:"修改学习档案",log_session:"保存真实学习记录",save_schedule:"保存每周计划"};
const toolLabels={get_study_profile:"读取学习档案",list_tasks:"查看学习任务",get_task:"查看任务详情",get_study_records:"查看学习记录",get_progress:"统计学习进度",preview_weekly_plan:"预览每周计划",propose_task_create:"准备新任务建议",propose_task_update:"准备任务调整建议",propose_task_delete:"准备任务删除建议",propose_profile_update:"准备档案修改建议",propose_study_record:"准备学习记录建议",propose_weekly_plan:"准备每周计划建议"};
const navIcons={overview:'<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',profile:'<rect x="5" y="3" width="14" height="18" rx="3"/><path d="M9 8h6M9 12h6M9 16h3"/>',tasks:'<path d="m3 6 2 2 4-4M12 6h9M3 13h6M12 13h9M3 20h6M12 20h9"/>',plan:'<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4M17 3v4M3 11h18M8 15h2M14 15h2"/>',records:'<path d="M4 20h16M7 16v-5M12 16V5M17 16V8"/>',account:'<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',assistant:'<path d="M21 11a8 8 0 0 1-8 8H7l-5 3 2-6a8 8 0 1 1 17-5Z"/><path d="M8 10h8M8 14h5"/>',development:'<path d="m8 6-6 6 6 6M16 6l6 6-6 6M14 3l-4 18"/>'};
const navIcon=id=>'<span class="nav-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'+navIcons[id]+'</svg></span>';
function theme(mode){
  document.documentElement.dataset.theme=mode;
  document.querySelectorAll("[data-theme-choice]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.themeChoice===mode)));
  try{localStorage.setItem("studypilot-web-theme",mode);}catch{}
}
try{theme(localStorage.getItem("studypilot-web-theme")||"light");}catch{theme("light");}
function notice(message,kind="success"){
  $("#notice").innerHTML=message?'<div class="notice '+kind+T('"><button type="button" data-action="dismiss" aria-label="关闭提示">×</button>')+E(message)+'</div>':"";
}
async function api(path,method="GET",body){
  const requestEpoch=authEpoch;
  const headers={"Accept-Language":StudyI18n.language};
  if(method!=="GET"){headers["Content-Type"]="application/json";if(me)headers["X-CSRF-Token"]=me.csrf;}
  if(method==="POST"&&["/tasks","/records"].includes(path))headers["Idempotency-Key"]=StudyWorkflow.retryKey(path,body);
  let response;
  try{response=await fetch("/api"+path,{method,headers,credentials:"same-origin",body:body===undefined?undefined:JSON.stringify(body)});}
  catch{throw new Error(T("网络连接失败，输入内容已保留，请重试。"));}
  let value;try{value=await response.json();}catch{throw new Error(T("服务暂时无法返回结果，请稍后重试。"));}
  if(requestEpoch!==authEpoch)throw new Error(T("登录状态已变化，本次结果未载入。"));
  if(!response.ok){
    if(response.status===401&&me){clearPrivate();render();}
    const error=new Error(value.error||value.detail||T("操作未完成，请重试。"));error.status=response.status;throw error;
  }
  return value;
}
function clearPrivate(){StudyWorkflow.clear();StudyMotion.workspace(false,false);StudyMotion.reset();$("#content").replaceChildren();renderedView=null;authEpoch++;chatPending=false;me=data=null;history=[];trace=[];preview=null;sessions=[];drafts.clear();page="overview";}
function saveDrafts(){
  document.querySelectorAll("#content > .page:not(.page-leaving) form").forEach(form=>{
    const values={};form.querySelectorAll("input,select,textarea").forEach(input=>{if(input.name)values[input.name]=input.type==="checkbox"?input.checked:input.value;});
    drafts.set(form.id,values);
  });
}
function restoreDrafts(){
  document.querySelectorAll("#content > .page:not(.page-leaving) form").forEach(form=>{
    const values=drafts.get(form.id);if(!values)return;
    form.querySelectorAll("input,select,textarea").forEach(input=>{if(input.name in values){if(input.type==="checkbox")input.checked=values[input.name];else input.value=values[input.name];}});
  });
}
const input=(name,label,value="",type="text",extra="")=>'<label>'+E(T(label))+'<input name="'+E(name)+'" type="'+type+'" value="'+E(value)+'" '+extra+'></label>';
const area=(name,label,value="",extra="")=>'<label>'+E(T(label))+'<textarea name="'+name+'" '+extra+'>'+E(value)+'</textarea></label>';
const select=(name,label,options,value)=>'<label>'+E(T(label))+'<select name="'+name+'">'+options.map(x=>'<option value="'+E(x)+'"'+(String(x)===String(value)?" selected":"")+'>'+E(V(x))+'</option>').join("")+'</select></label>';
const check=(name,label,checked=false)=>'<label class="check"><input type="checkbox" name="'+name+'"'+(checked?" checked":"")+'>'+E(T(label))+'</label>';
const confirm=(label=T("我核对了以上内容，确认保存"))=>check("confirmed",label);
const submit=label=>'<div class="actions"><button type="submit">'+E(T(label))+'</button></div>';
const head=(eyebrow,title,text)=>'<div class="eyebrow">'+E(eyebrow)+'</div><h1>'+E(title)+'<span>.</span></h1><p class="intro">'+E(text)+'</p>';
const empty=text=>'<div class="empty">'+E(text)+'</div>';
function pretty(value,field=""){
  if(value===null||value===undefined)return T("无");
  if(typeof value==="boolean")return value?T("是"):T("否");
  if(Array.isArray(value))return value.map(v=>pretty(v,field)).join(StudyI18n.language==="en"?", ":"、");
  if(typeof value==="object")return Object.entries(value).map(([key,v])=>T(labels[key]||key)+(StudyI18n.language==="en"?": ":"：")+pretty(v,["levels","priorities"].includes(field)?field:key)).join("\n");
  return ["subject","status","priority","speed","levels","priorities","devices","reason","suggestion"].includes(field)?V(value):String(value);
}
function table(headers,rows){return '<div class="table-wrap"><table><thead><tr>'+headers.map(x=>'<th>'+E(x)+'</th>').join("")+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(cell=>'<td>'+cell+'</td>').join("")+'</tr>').join("")+'</tbody></table></div>';}
function barChart(items){
  const entries=Object.entries(items);if(!entries.length)return empty(T("还没有真实学习记录。"));
  const max=Math.max(...entries.map(x=>Number(x[1])),1),height=entries.length*42;
  return T('<svg class="chart" role="img" aria-label="真实学习分钟图表" viewBox="0 0 660 ')+height+'">'+entries.map(([name,amount],i)=>'<text x="0" y="'+(i*42+23)+'">'+E(V(name))+'</text><rect class="rail" x="140" y="'+(i*42+8)+'" width="430" height="20" rx="7"/><rect x="140" y="'+(i*42+8)+'" width="'+Math.round(Number(amount)/max*430)+'" height="20" rx="7"/><text x="585" y="'+(i*42+23)+'">'+E(amount)+T(' 分</text>')).join("")+'</svg>';
}
function render(){
  $("#account-bar").innerHTML=me?'<span>'+E(me.personal.avatar)+T(" 已登录：")+E(me.personal.nickname)+(StudyI18n.language==="en"?" (":"（")+E(me.account.username)+(StudyI18n.language==="en"?")":"）")+(me.account.role==="developer"?T(" · 开发者"):"")+T('</span><button class="btn small" data-action="logout">退出登录</button>'):"";
  StudyI18n.shell();
  const nav=$("#navigation"), role=me?.account.role||null;
  nav.hidden=!me;
  if(role!==navigationRole){
    navigationRole=role;
    nav.innerHTML=me?'<span class="nav-capsule" aria-hidden="true"></span>'+Object.entries(names).filter(([id])=>id!=="development"||role==="developer").map(([id,label])=>'<button data-page="'+id+'">'+navIcon(id)+'<span class="nav-label">'+label+'</span></button>').join(""):"";
  }
  nav.querySelectorAll("button[data-page]").forEach(button=>{
    button.querySelector(".nav-label").textContent=T(names[button.dataset.page]);
    if(button.dataset.page===page)button.setAttribute("aria-current","page");
    else button.removeAttribute("aria-current");
  });
  StudyMotion.workspace(Boolean(me&&page==="assistant"));
  document.querySelectorAll('#conversation-sidebar-tools [data-action="clear-chat"]').forEach(button=>button.disabled=chatPending);
  StudyMotion.navigation();
  const renderers={overview:overview,profile:profile,tasks:tasks,plan:plan,records:records,account:account,assistant:assistant,development:development};
  const view=recoveryCode?"recovery":me&&data?"user:"+me.account.id+":"+page:"auth:"+authPage;
  const next=document.createElement("section");next.className="page";
  next.innerHTML=recoveryCode?recovery():me&&data?renderers[page]():login();
  StudyMotion.replace($("#content"),next,view!==renderedView);
  renderedView=view;
  restoreDrafts();
  if(page==="assistant"&&me){
    $("#conversation-prompt").readOnly=chatPending;
    const stream=$(".conversation-scroll");if(stream&&history.length)stream.scrollTop=stream.scrollHeight;
  }
}
function login(){
  const tabs='<div class="auth-tabs">'+[["login",T("登录")],["register",T("注册账号")],["recover",T("找回密码")]].map(([id,title])=>'<button class="btn small" data-auth-page="'+id+'" aria-pressed="'+(authPage===id)+'">'+title+'</button>').join("")+'</div>';
  let fields=input("username",T("用户名"),"","text",'autocomplete="username" maxlength="64" required');
  if(authPage==="recover")fields+=input("recovery_code",T("恢复码"),"","password",'autocomplete="off" required')+input("new_password",T("新密码"),"","password",'autocomplete="new-password" maxlength="128" required')+input("password_again",T("再次输入新密码"),"","password",'autocomplete="new-password" required')+confirm(T("我确认重置密码，并让旧会话退出"));
  else fields+=input("password",T("密码"),"","password",'autocomplete="'+(authPage==="login"?"current-password":"new-password")+'" maxlength="128" required')+(authPage==="register"?input("password_again",T("再次输入密码"),"","password",'autocomplete="new-password" required')+confirm(T("我确认创建自己的账号")):"");
  return '<div class="auth">'+head("HELLO / YOUR OWN LEARNING SPACE",T("欢迎使用 StudyPilot"),T("登录账号，管理学习目标、任务和进度。"))+(!accountServiceReady?T('<div class="info">账号服务暂时不可用，请稍后重试。</div>'):"")+tabs+'<form id="auth-'+authPage+'" class="card" data-kind="'+authPage+'"><fieldset'+(accountServiceReady?"":" disabled")+'>'+fields+submit(authPage==="login"?T("登录"):authPage==="register"?T("创建账号"):T("重置密码"))+T('</fieldset></form><small>用户名支持中文与常用符号，1–64 字；密码为 15–128 字。登录状态过期后，请重新登录。</small></div>');
}
function recovery(){return '<div class="auth">'+head("KEEP IT SAFE",T("请保存你的恢复码"),T("恢复码只显示这一次；丢失密码时可用于重置。"))+'<div class="card"><p class="recovery">'+E(recoveryCode)+T('</p><small>不要发给其他人。恢复码更新后旧码失效。</small><div class="actions"><button class="btn primary" data-action="saved-recovery">我已妥善保存，去登录</button></div></div></div>');}
function gettingStarted(){
  const steps=[["profile",T("1. 确认目标、时间与设备"),Boolean(data.profile_version)],
    ["tasks",T("2. 添加可执行的学习任务"),Boolean(data.tasks.length)],
    ["plan",T("3. 预览并确认每周计划"),Boolean(data.plans.length)]];
  const incomplete=steps.find(step=>!step[2]);
  if(incomplete)return '<section class="card getting-started"><h2>'+E(T("从这里开始"))+'</h2><ol>'+steps.map(([id,label,done])=>'<li><button type="button" class="btn" data-page="'+id+'">'+E((done?"✓ ":"")+label)+'</button></li>').join("")+'</ol><p class="muted">'+E(T("只需检查并确认已有设置，无需重复填写。目标也可以暂时留空。"))+'</p><button type="button" class="btn primary" data-page="'+incomplete[0]+'">'+E(T("继续下一步"))+'</button></section>';
  const next=StudyWorkflow.nextAction(data,me.today);
  return '<section class="card next-action"><h2>'+E(next?.date===me.today?T("今天的第一步"):T("下一步学习安排"))+'</h2>'+(next?'<h3>'+E(next.title)+'</h3><p>'+E(next.date)+' · '+next.minutes+' '+E(T("计划分钟"))+'</p><p>'+E(next.notes||T("开始前先明确要完成的练习；学习后再记录真实用时。"))+'</p><button type="button" class="btn primary" data-page="records">'+E(T("学习后记录真实用时"))+'</button>':'<p>'+E(T("当前没有待执行安排。可以调整任务，再生成新的计划预览。"))+'</p>')+'<button type="button" class="btn" data-page="plan">'+E(T("核对或重新安排"))+'</button></section>';
}
function overview(){
  const p=data.progress,rate=p.completion_rate===null?"—":Math.round(p.completion_rate*100)+"%";
  return gettingStarted()+'<div class="hero"><div>'+head("01 / SMALL STEPS, REAL PROGRESS",T("把想学的，变成做到的"),T("集中管理目标、任务与计划，随时掌握本周学习进度。"))+T('<div class="actions"><button class="btn primary" data-page="tasks">添加学习任务 ↗</button><button class="btn" data-page="profile">调整学习档案</button></div></div><img src="/learning-map.svg" alt="学习路径插画"></div><div class="grid three"><div class="card metric"><span>本周真实学习</span><strong>')+p.actual_minutes+T('<small>分钟</small></strong></div><div class="card metric"><span>本周到期任务</span><strong>')+p.completed_count+' / '+p.task_count+T('</strong><small>已完成 / 全部</small></div><div class="card metric"><span>本周任务完成率</span><strong>')+rate+T('</strong><small>按当前任务状态计算</small></div></div><h2>每周可用时间</h2><small>')+(data.profile_version?T("来自已保存档案"):T("待完善的学习设置"))+T(' · 在学习档案中调整时间与设备</small><div class="days">')+me.options.days.map(day=>'<div class="day">'+E(V(day))+'<strong>'+data.profile.availability[day].minutes+T(' 分</strong>')+E(data.profile.availability[day].devices.map(V).join(" / "))+'</div>').join("")+T('</div><div class="grid"><div class="card"><h3>本周科目投入</h3>')+barChart(p.subjects)+T('</div><div class="card"><h3>每周真实学习</h3>')+barChart(p.weekly_history)+'</div></div>';
}
function profile(){
  const p=data.profile,o=me.options;
  return head("02 / YOUR LEARNING PROFILE",T("制定适合你的学习安排"),T("设置学习目标、可用时间和设备，为任务规划提供依据。目标可暂时留空。"))+(data.profile_version?"":T('<div class="info">请核对时间与设备设置，确认保存后用于生成学习计划。</div>'))+'<form id="profile-'+data.profile_version+'" data-kind="profile" data-version="'+data.profile_version+T('" class="card"><h3>你的学习目标</h3>')+area("goals",T("学习目标"),p.goals,T('maxlength="2000" placeholder="写下希望达成的学习目标，也可以暂时留空"'))+input("goal_deadline",T("目标期限（可选）"),p.goal_deadline||"","date")+T('<small>期限留空代表不设置统一期限；设置后不会安排在该期限之后。</small>')+T('<small>目标可随时编辑或清空，确认保存后生效。也可在对话中讨论目标建议。</small><h2>时间与偏好</h2><div class="grid">')+input("weekly_hours",T("每周小时"),p.weekly_hours,"number",'min="0.1" max="40" step="0.1" required')+select("speed",T("学习速度"),o.speeds,p.speed)+input("max_session_minutes",T("单次学习时长上限（分钟）"),p.max_session_minutes,"number",'min="1" max="180" required')+input("preference",T("学习偏好"),p.preference,"text",'maxlength="500"')+T('</div><details><summary>各科基础与优先级（可展开调整）</summary>')+o.subjects.map((s,i)=>'<div class="grid">'+select("level_"+i,s+T(" · 当前水平"),o.levels,p.levels[s])+select("priority_"+i,s+T(" · 优先级"),o.priorities,p.priorities[s])+'</div>').join("")+T('</details><h2>每天的时间和设备</h2><small>各天分钟总和应至少覆盖每周预算。</small>')+o.days.map((d,i)=>'<div class="card"><h3>'+E(V(d))+'</h3>'+input("day_"+i,T("可用分钟"),p.availability[d].minutes,"number",'min="0" max="1440" required')+'<div class="checks">'+o.devices.map((device,j)=>check("device_"+i+"_"+j,device,p.availability[d].devices.includes(device))).join("")+'</div></div>').join("")+confirm()+submit(T("保存学习档案"))+'</form>';
}
function taskFields(t={}){
  const o=me.options;
  return input("title",T("任务标题"),t.title||"","text",'maxlength="120" required')+'<div class="grid">'+select("subject",T("科目"),o.subjects,t.subject||"Python")+input("due_date",T("截止日期"),t.due_date||data.profile.goal_deadline||me.today,"date","required")+input("estimated_minutes",T("预计学习分钟"),t.estimated_minutes||45,"number",'min="1" max="1440" required')+select("priority",T("优先级"),o.priorities,t.priority||"中")+select("status",T("状态"),o.statuses,t.status||"待开始")+'</div>'+check("requires_computer",T("这项任务需要电脑"),Boolean(t.requires_computer))+area("notes",T("任务备注"),t.notes||"",'maxlength="2000"');
}
function tasks(){
  return head("03 / ONE TASK AT A TIME",T("有序推进每一项任务"),T("设置任务优先级和截止日期，跟进完成情况。删除任务后，已有学习记录仍保留。"))+'<details'+(!data.tasks.length?' open':'')+'>'+T('<summary>＋ 创建学习任务</summary><form id="new-task" data-kind="task-create">')+taskFields()+confirm()+submit(T("创建任务"))+'</form></details>'+(!data.tasks.length?empty(T("还没有任务。先从一个小任务开始。")):data.tasks.map(t=>'<article class="card"><div class="task-head"><div><h3>#'+t.id+' · '+E(t.title)+'</h3><span class="tag">'+E(V(t.subject))+'</span><span class="tag">'+E(V(t.status))+'</span><span class="tag">'+E(V(t.priority))+(StudyI18n.language==="en"?" priority":"优先级")+'</span></div><small>'+T("截止 ")+E(t.due_date)+T(' · 预计 ')+t.estimated_minutes+T(' 分钟')+(t.requires_computer?T(" · 需要电脑"):"")+'</small></div>'+(t.notes?'<p>'+E(t.notes)+'</p>':"")+T('<details><summary>编辑任务</summary><form id="task-')+t.id+'-'+t.version+'" data-kind="task-update" data-id="'+t.id+'" data-version="'+t.version+'">'+taskFields(t)+confirm()+submit(T("保存任务修改"))+T('</form></details><details><summary>删除任务</summary><form id="delete-task-')+t.id+'" data-kind="task-delete" data-id="'+t.id+'" data-version="'+t.version+'">'+confirm(T("我确认删除此任务；历史真实用时保留"))+submit(T("删除任务"))+'</form></details></article>').join(""));
}
function renderPlan(p){
  return '<p><span class="tag">'+E(p.week_start)+' ～ '+E(p.week_end)+T('</span></p><p>周预算 ')+p.budget_minutes+T(' 分钟 · 已记录 ')+p.actual_minutes+T(' 分钟 · 本次安排 ')+p.planned_minutes+T(' 分钟 · 剩余 ')+p.unused_minutes+T(' 分钟</p>')+(p.entries.length?table([T("日期"),T("任务"),T("科目"),T("分钟")],p.entries.map(e=>[E(e.date),E(e.title||e.task_title||"#"+e.task_id),E(V(e.subject)),E(e.minutes)])):empty(T("当前约束下没有可安排的内容。")))+(p.unscheduled.length?T('<h3>未安排部分</h3>')+table([T("任务"),T("说明")],p.unscheduled.map(e=>[E(e.title||"#"+e.task_id),E(pretty(e))])):"");
}
function plan(){
  return head("04 / MAKE ROOM FOR LEARNING",T("把时间，安排得刚刚好"),T("根据可用时间、设备和任务截止日期生成每周安排，核对后保存。"))+'<form id="plan-preview" data-kind="plan-preview" class="card">'+input("week_of",T("选择这一周的任意日期"),me.today,"date","required")+submit(T("生成计划预览"))+'</form>'+(preview?T('<div class="card"><h3>待保存预览</h3>')+renderPlan(preview.preview)+'<form id="plan-save" data-kind="plan-save">'+confirm(preview.expected_version?T("我确认替换该周已保存计划"):T("我核对了计划，确认保存"))+submit(T("保存计划"))+'</form><button type="button" class="btn" data-action="discard-preview">'+E(T('放弃此预览'))+'</button></div>':"")+T('<h2>已保存计划</h2><p class="muted">已保存计划是当时的快照。时间、设备、任务或记录改变后，请重新生成预览并确认。</p>')+(!data.plans.length?empty(T("尚未保存计划。")):data.plans.map(p=>'<details><summary>'+E(p.week_start)+T(' 所在周 · 版本 ')+p.version+'</summary>'+renderPlan(p.payload)+'<form id="delete-plan-'+p.week_start+'" data-kind="plan-delete" data-week="'+p.week_start+'" data-version="'+p.version+'">'+confirm(T("我确认删除此周计划；任务和真实记录不变"))+submit(T("删除此周计划"))+'</form></details>').join(""));
}
function records(){
  return head("05 / REAL EFFORT COUNTS",T("认真记录，每一点投入"),T("只填写确实发生的学习。预计时间和计划不会自动计入真实用时。"))+(data.tasks.length?T('<form id="record-create" data-kind="record-create" class="card"><label>关联任务<select name="task_id">')+data.tasks.map(t=>'<option value="'+t.id+'">#'+t.id+' '+E(t.title)+'</option>').join("")+'</select></label><div class="grid">'+input("study_date",T("实际学习日期"),me.today,"date",'max="'+me.today+'" required')+input("minutes",T("实际分钟"),30,"number",'min="1" max="1440" required')+'</div>'+area("note",T("备注"),"","maxlength=\"1000\"")+confirm(T("我确认这次学习确实发生，并保存记录"))+submit(T("记录真实用时"))+'</form>':empty(T("先创建一项任务，再记录学习用时。")))+T('<h2>已有记录</h2>')+(!data.records.length?empty(T("还没有真实学习记录。")):data.records.map(r=>'<div class="card"><h3>'+E(r.task_title)+'</h3><p>'+E(r.study_date)+' · '+E(V(r.subject))+' · '+r.minutes+T(' 分钟')+(r.deleted_at?T(" · 原任务已删除"):"")+'</p><p>'+E(r.note)+T('</p><details><summary>删除误记</summary><form id="delete-record-')+r.id+'" data-kind="record-delete" data-id="'+r.id+'">'+confirm(T("我确认删除这条误记；统计会相应改变"))+submit(T("删除记录"))+'</form></details></div>').join(""))+T('<div class="card"><h3>每周真实学习</h3>')+barChart(data.progress.weekly_history)+'</div>';
}
function account(){
  const p=data.personal;
  return head("06 / YOUR ACCOUNT",T("账号与安全"),T("个人资料、账号安全和数据管理。"))+'<form id="personal-'+p.version+'" data-kind="personal" data-version="'+p.version+T('" class="card"><h3>个人资料</h3><div class="grid">')+input("nickname",T("昵称"),p.nickname,"text",'maxlength="64" required')+select("avatar",T("头像标识"),me.options.avatars,p.avatar)+'</div>'+input("bio",T("个性签名"),p.bio,"text",'maxlength="120"')+confirm()+submit(T("保存个人资料"))+T('</form><details><summary>修改密码</summary><form id="password-change" data-kind="password">')+input("current_password",T("当前密码"),"","password",'autocomplete="current-password" required')+input("new_password",T("新密码"),"","password",'autocomplete="new-password" maxlength="128" required')+input("password_again",T("再次输入新密码"),"","password",'autocomplete="new-password" required')+confirm(T("我确认更新密码和恢复码，并退出全部旧会话"))+submit(T("更新密码"))+T('</form></details><details><summary>登录会话管理</summary><button class="btn" data-action="load-sessions">查看有效登录会话</button><div id="session-list">')+sessionList()+'</div><form id="revoke-sessions" data-kind="revoke-sessions">'+confirm(T("我确认退出其他登录会话"))+submit(T("退出其他会话"))+T('</form></details><div class="card"><h3>个人学习数据</h3><p class="muted">导出自己的资料、任务、记录、计划、提案与执行收据。不包含密码、恢复码和登录令牌。</p><a class="btn" href="/api/export" download="StudyPilot-export.json">导出学习数据</a></div>');
}
function sessionList(){return sessions.length?table([T("登录时间"),T("最近活动"),T("会话")],sessions.map(s=>[E(StudyI18n.timestamp(s.created_at)),E(StudyI18n.timestamp(s.last_seen)),s.current?T("当前"):T("其他")])):"";}
function proposal(p){
  const d=p.payload,expired=p.expires_at*1000<=Date.now();
  let content="";
  if(p.action==="save_schedule")content=(d.expected_version?T('<div class="info">确认后替换这一周已保存的计划。</div>'):"")+renderPlan(d.after);
  else if(p.action==="delete_task")content=T('<div class="info">将删除任务 #')+d.task_id+'：'+E(d.before.title)+T('。真实学习记录保留。</div><pre>')+E(pretty(d.before))+'</pre>';
  else if(p.action==="update_task"||p.action==="update_profile")content=table([T("字段"),T("当前内容"),T("拟改为")],Object.entries(d.after).filter(([key,v])=>JSON.stringify(v)!==JSON.stringify(d.before[key])).map(([key,v])=>[E(T(labels[key]||key)),'<pre>'+E(pretty(d.before[key],key))+'</pre>','<pre>'+E(pretty(v,key))+'</pre>']));
  else content=(p.action==="log_session"?T('<p>关联任务 #')+d.task_id+'：'+E(d.before.title)+'</p>':"")+'<pre>'+E(pretty(d.after))+'</pre>';
  return '<article class="card"><h3>'+E(T(actionNames[p.action]||p.action))+'</h3><p>'+E(p.reason)+T('</p><small>编号 ')+E(p.id.slice(0,8))+' · '+E(StudyI18n.timestamp(p.created_at))+T(' · 30 分钟有效</small>')+content+(expired?T('<div class="info">提案已过期，请重新生成。</div>'):'<form id="proposal-'+E(p.id)+'" data-kind="proposal-execute" data-id="'+E(p.id)+'">'+confirm(p.action==="log_session"?T("我确认这次学习确实发生，并保存记录"):T("我核对了以上更改，确认执行"))+submit(T("确认执行"))+'</form>')+'<div class="actions"><button class="btn small" data-reject="'+E(p.id)+T('">忽略提案</button></div></article>');
}
function assistant(){
  const pending=data.proposals.filter(p=>p.state==="pending"),applied=data.proposals.filter(p=>p.state==="applied").slice(0,5);
  const suggestions=[[T('总结本周进度'),T('帮我总结本周的学习进度，并建议下一步。'),'chat'],[T('梳理学习目标'),T('和我一起梳理学习目标，先讨论，不要直接修改。'),'goal_coach'],[T('安排每周计划'),T('根据我的任务和可用时间生成本周计划建议。'),'plan_builder']];
  const welcome=!history.length?T('<div class="conversation-welcome"><div class="conversation-mark" aria-hidden="true">↗</div><p class="conversation-eyebrow">YOUR NEXT CHAPTER</p><h1>今天，想推进什么？</h1><p>聊聊目标，理清计划。让每一步都有方向。</p><div class="conversation-suggestions">')+suggestions.map(([label,prompt,mode])=>'<button type="button" data-prompt="'+E(prompt)+'" data-mode="'+mode+'">'+E(T(label))+'<span aria-hidden="true">↗</span></button>').join("")+'</div></div>':"";
  const messages=history.map(m=>'<article class="conversation-message '+m.role+'">'+(m.role==="assistant"?'<div class="message-mark" aria-hidden="true">↗</div>':"")+'<div class="message-body"><span class="sr-only">'+(m.role==="user"?T("你"):"StudyPilot")+'</span>'+E(m.content)+'</div></article>').join("");
  const review=pending.length?T('<section class="conversation-review"><h2>待确认的修改 <span>')+pending.length+T('</span></h2><p class="muted">核对建议后，在卡片中确认应用。</p>')+pending.map(proposal).join("")+'</section>':"";
  return T('<div class="conversation"><div class="conversation-scroll" tabindex="0" aria-label="对话内容"><div class="conversation-thread">')+welcome+'<div class="conversation-messages" role="log" aria-live="polite">'+messages+'</div>'+review+(trace.length?T('<details class="conversation-detail"><summary>本次处理记录</summary>')+table([T("操作"),T("状态")],trace.map(t=>[E(T(toolLabels[t.tool]||T("处理学习请求"))),E(t.state==="pending"?T("待确认提案"):t.state==="read"?T("只读查询"):T("参数未通过"))]))+'</details>':"")+(applied.length?T('<details class="conversation-detail"><summary>最近应用记录</summary>')+table([T("建议"),T("操作"),T("时间")],applied.map(p=>[E(p.id.slice(0,8)),E(T(actionNames[p.action])),E(StudyI18n.timestamp(p.applied_at))]))+'</details>':"")+(!pending.length&&history.length?T('<p class="conversation-note">当前没有待确认的修改。</p>'):"")+'</div></div><div class="composer-dock">'+(!me.ai_configured?T('<p class="conversation-availability">对话服务暂未开放，学习管理功能仍可正常使用。</p>'):"")+T('<form id="agent-chat" data-kind="agent-chat" class="composer"><label class="sr-only" for="conversation-prompt">发送消息</label><textarea id="conversation-prompt" name="prompt" rows="2" maxlength="3000" placeholder="向 StudyPilot 提问" required></textarea><div class="composer-toolbar"><label class="composer-mode"><span class="sr-only">对话模式</span><select name="mode">')+me.modes.values.map(v=>'<option value="'+E(v)+'">'+E(T(me.modes.labels[v]||v))+'</option>').join("")+'</select></label><small id="agent-status" role="status">'+(chatPending?T("正在思考…"):"")+T('</small><button class="composer-send" type="submit" aria-label="发送消息" title="发送消息"')+(me.ai_configured&&!chatPending?"":" disabled")+T('><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6"/></svg></button></div><label class="composer-consent"><input type="checkbox" name="consent">我同意本次对话使用相关学习资料</label></form><p class="composer-disclosure">经你同意，问题、上下文及相关学习资料将发送至智谱或硅基流动，不含账号凭据。AI 建议可能有误，修改仍需确认。对话在刷新或退出后清除。</p></div></div>');
}
function development(){
  return head("DEV / DEVELOPMENT PROGRESS",T("功能与维护"),T("查看已启用功能与后续维护事项。此页面仅对开发者开放。"))+T('<div class="card"><h3>已完成</h3><p>账号与个人资料管理、学习档案、任务与记录、每周计划、进度统计、AI 学习建议与用户确认。</p><h3>后续维护事项</h3><p>目标里程碑完成率、考试优先级自动调整。</p></div>');
}
async function refresh(){data=await api("/state");me.personal=data.personal;}
function numeric(form,name){return Number(new FormData(form).get(name));}
async function submitForm(form){
  const fd=new FormData(form),get=name=>String(fd.get(name)||""),checked=name=>fd.has(name),kind=form.dataset.kind;
  const body={confirmed:checked("confirmed")};
  let path="",method="POST",success=T("已保存。");
  if(kind==="login"){const identity=await api("/login","POST",{username:get("username"),password:get("password")});clearPrivate();me=identity;await refresh();notice("");render();return;}
  if(kind==="register"||kind==="recover"){
    const payload=kind==="register"?{username:get("username"),password:get("password"),password_again:get("password_again"),...body}:{username:get("username"),recovery_code:get("recovery_code"),new_password:get("new_password"),password_again:get("password_again"),...body};
    const result=await api(kind==="register"?"/register":"/recover","POST",payload);drafts.clear();recoveryCode=result.recovery_code;form.reset();render();return;
  }
  if(kind==="profile"){
    const levels={},priorities={},availability={};
    me.options.subjects.forEach((s,i)=>{levels[s]=get("level_"+i);priorities[s]=get("priority_"+i);});
    me.options.days.forEach((day,i)=>{availability[day]={minutes:numeric(form,"day_"+i),devices:me.options.devices.filter((_,j)=>checked("device_"+i+"_"+j))};});
    path="/profile";body.expected_version=Number(form.dataset.version);body.profile={goals:get("goals"),goal_deadline:get("goal_deadline"),weekly_hours:numeric(form,"weekly_hours"),speed:get("speed"),preference:get("preference"),max_session_minutes:numeric(form,"max_session_minutes"),levels,priorities,availability};
  }else if(kind==="task-create"||kind==="task-update"){
    path="/tasks"+(kind==="task-update"?"/"+form.dataset.id:"");method=kind==="task-update"?"PUT":"POST";
    body.expected_version=Number(form.dataset.version||0);body.task={title:get("title"),subject:get("subject"),due_date:get("due_date"),estimated_minutes:numeric(form,"estimated_minutes"),priority:get("priority"),status:get("status"),requires_computer:checked("requires_computer"),notes:get("notes")};
  }else if(kind==="task-delete"){path="/tasks/"+form.dataset.id;method="DELETE";body.expected_version=Number(form.dataset.version);success=T("任务已删除，已有真实学习记录保留。");
  }else if(kind==="record-create"){path="/records";Object.assign(body,{task_id:numeric(form,"task_id"),study_date:get("study_date"),minutes:numeric(form,"minutes"),note:get("note")});
  }else if(kind==="record-delete"){path="/records/"+form.dataset.id;method="DELETE";success=T("误记已删除，统计已更新。");
  }else if(kind==="plan-preview"){preview=await api("/plans/preview?week_of="+encodeURIComponent(get("week_of")));saveDrafts();drafts.delete("plan-save");render();notice(T("已生成预览，尚未保存。"));return;
  }else if(kind==="plan-save"){path="/plans";if(!preview)throw new Error(T("请先生成计划预览。"));Object.assign(body,preview);
  }else if(kind==="plan-delete"){path="/plans/"+form.dataset.week;method="DELETE";body.expected_version=Number(form.dataset.version);success=T("此周计划已删除。");
  }else if(kind==="personal"){path="/personal";Object.assign(body,{expected_version:Number(form.dataset.version),nickname:get("nickname"),avatar:get("avatar"),bio:get("bio")});
  }else if(kind==="password"){
    const result=await api("/password","POST",{...body,current_password:get("current_password"),new_password:get("new_password"),password_again:get("password_again")});clearPrivate();recoveryCode=result.recovery_code;render();return;
  }else if(kind==="revoke-sessions"){path="/sessions/revoke";success=T("其他会话已退出。");
  }else if(kind==="proposal-execute"){path="/proposals/"+form.dataset.id+"/execute";success=T("提案已执行并保存；重复提交不会重复写入。");
  }else if(kind==="agent-chat"){
    if(chatPending)throw new Error(T("正在生成答复，请稍候。"));
    chatPending=true;
    form.elements.prompt.readOnly=true;
    document.querySelectorAll('[data-action="clear-chat"]').forEach(button=>button.disabled=true);
    const status=$("#agent-status");if(status)status.textContent=T("正在思考…");
    let result;
    try{result=await api("/agent","POST",{prompt:get("prompt"),mode:get("mode")||"chat",consent:checked("consent"),history,language:StudyI18n.language});}
    catch(error){try{data=await api("/state");saveDrafts();render();}catch{}if(me)error.message+=" "+T("问题已保留，可修改后重新发送。");throw error;}
    history=[...history,{role:"user",content:get("prompt")},{role:"assistant",content:result.text}].slice(-12);trace=result.trace;
    await refresh();drafts.delete(form.id);render();notice(T("答复已生成，修改仍需在提案卡片中确认。"));return;
  }else throw new Error(T("此表单无法提交，请刷新后重试。"));
  const firstProfile=kind==="profile"&&!data.profile_version,firstTask=kind==="task-create"&&!data.tasks.length;
  await api(path,method,body);
  saveDrafts();drafts.delete(form.id);
  if(kind==="plan-save")preview=null;
  if(kind==="revoke-sessions")sessions=await api("/sessions");
  await refresh();
  if(kind==="task-create"||kind==="record-create")StudyWorkflow.complete(path,body);
  if(firstProfile){page="tasks";success=T("档案已保存，接下来添加一项具体任务。");}
  else if(firstTask&&data.profile_version){page="plan";success=T("任务已保存，接下来预览并确认每周计划。");}
  else if(kind==="plan-save")page="overview";
  render();notice(success);
}
document.addEventListener("submit",async event=>{
  const form=event.target;if(!(form instanceof HTMLFormElement))return;
  event.preventDefault();if(form.dataset.kind==="agent-chat"&&chatPending)return;
  const submitEpoch=authEpoch,buttons=[...form.querySelectorAll("button")];buttons.forEach(b=>b.disabled=true);notice("");
  try{await submitForm(form);}catch(error){notice(error.message,"error");}
  finally{buttons.forEach(b=>b.disabled=false);if(form.dataset.kind==="agent-chat"&&submitEpoch===authEpoch){chatPending=false;document.querySelectorAll('[data-action="clear-chat"]').forEach(button=>button.disabled=false);const prompt=$("#conversation-prompt");if(prompt)prompt.readOnly=false;const send=$('.composer-send');if(send)send.disabled=!me?.ai_configured;const status=$("#agent-status");if(status)status.textContent="";}}
});
document.addEventListener("keydown",event=>{
  if(event.key==="Escape"&&document.body.dataset.sidebarOpen==="true"){
    delete document.body.dataset.sidebarOpen;$("#workspace-menu").setAttribute("aria-expanded","false");$("#workspace-menu").focus();
  }
  if(event.target.id==="conversation-prompt"&&event.key==="Enter"&&!event.shiftKey&&!event.isComposing&&event.keyCode!==229){
    event.preventDefault();const send=$(".composer-send");if(send&&!send.disabled)event.target.form.requestSubmit();
  }
});
document.addEventListener("click",async event=>{
  const button=event.target.closest("button");if(!button)return;
  try{
    if(button.dataset.languageChoice){saveDrafts();StudyI18n.set(button.dataset.languageChoice);notice("");render();return;}
    if(button.dataset.action==="toggle-sidebar"){
      const open=document.body.dataset.sidebarOpen!=="true";document.body.dataset.sidebarOpen=String(open);
      $("#workspace-menu").setAttribute("aria-expanded",String(open));return;
    }
    if(button.closest(".page-leaving"))return;
    if(button.dataset.prompt){
      if(chatPending)return;
      const form=$("#agent-chat");form.elements.prompt.value=button.dataset.prompt;form.elements.mode.value=button.dataset.mode;
      form.elements.prompt.focus();return;
    }
    if(button.dataset.themeChoice){theme(button.dataset.themeChoice);return;}
    if(button.dataset.page){delete document.body.dataset.sidebarOpen;$("#workspace-menu").setAttribute("aria-expanded","false");if(page===button.dataset.page)return;saveDrafts();page=button.dataset.page;notice("");render();return;}
    if(button.dataset.authPage){if(authPage===button.dataset.authPage)return;saveDrafts();authPage=button.dataset.authPage;notice("");render();return;}
    if(button.dataset.reject){button.disabled=true;await api("/proposals/"+button.dataset.reject+"/reject","POST",{});saveDrafts();await refresh();render();notice(T("提案已忽略，没有修改学习数据。"));return;}
    switch(button.dataset.action){
      case "discard-preview":preview=null;saveDrafts();drafts.delete("plan-save");render();notice(T("预览已放弃，已保存的数据没有变化。"));break;
      case "dismiss":notice("");break;
      case "logout":await api("/logout","POST",{});clearPrivate();render();notice(T("已退出登录。"));break;
      case "saved-recovery":recoveryCode="";authPage="login";render();notice("");break;
      case "clear-chat":if(chatPending)break;history=[];trace=[];drafts.delete("agent-chat");delete document.body.dataset.sidebarOpen;$("#workspace-menu").setAttribute("aria-expanded","false");render();$("#conversation-prompt")?.focus();break;
      case "load-sessions":sessions=await api("/sessions");$("#session-list").innerHTML=sessionList();break;
    }
  }catch(error){notice(error.message,"error");button.disabled=false;}
});
async function boot(){
  try{const health=await api("/health");accountServiceReady=health.database_configured;if(!accountServiceReady){render();return;}me=await api("/me");await refresh();render();}
  catch(error){clearPrivate();render();if(error.status!==401)notice(error.message,"error");}
}
boot();
