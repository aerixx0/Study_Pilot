"use strict";
const $ = (q, root=document) => root.querySelector(q);
const E = v => String(v ?? "").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let me=null, data=null, page="overview", authPage="login", recoveryCode="", history=[], preview=null, trace=[], sessions=[], authEpoch=0, accountServiceReady=true;
const drafts=new Map();
const names={overview:"学习概览",profile:"学习档案",tasks:"学习任务",plan:"学习计划",records:"学习记录",account:"账号设置",assistant:"AI 助手",development:"开发进度"};
const labels={title:"任务标题",subject:"科目",due_date:"截止日期",estimated_minutes:"预计分钟",priority:"优先级",status:"状态",requires_computer:"需要电脑",notes:"备注",goals:"学习目标",weekly_hours:"每周小时",speed:"学习速度",preference:"学习偏好",max_session_minutes:"单次时长上限",levels:"各科基础",priorities:"科目优先级",availability:"每天时间和设备",study_date:"实际日期",duration:"实际分钟",note:"备注",minutes:"分钟",devices:"设备"};
const actionNames={create_task:"创建任务",update_task:"修改任务",delete_task:"删除任务",update_profile:"修改学习档案",log_session:"保存真实学习记录",save_schedule:"保存每周计划"};
function theme(mode){
  document.documentElement.dataset.theme=mode;
  document.querySelectorAll("[data-theme-choice]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.themeChoice===mode)));
  try{localStorage.setItem("studypilot-web-theme",mode);}catch{}
}
try{theme(localStorage.getItem("studypilot-web-theme")||"light");}catch{theme("light");}
function notice(message,kind="success"){
  $("#notice").innerHTML=message?'<div class="notice '+kind+'"><button type="button" data-action="dismiss" aria-label="关闭提示">×</button>'+E(message)+'</div>':"";
}
async function api(path,method="GET",body){
  const requestEpoch=authEpoch;
  const headers={};
  if(method!=="GET"){headers["Content-Type"]="application/json";if(me)headers["X-CSRF-Token"]=me.csrf;}
  let response;
  try{response=await fetch("/api"+path,{method,headers,credentials:"same-origin",body:body===undefined?undefined:JSON.stringify(body)});}
  catch{throw new Error("网络连接失败，输入内容已保留，请重试。");}
  let value;try{value=await response.json();}catch{throw new Error("服务暂时无法返回结果，请稍后重试。");}
  if(requestEpoch!==authEpoch)throw new Error("登录状态已变化，本次结果未载入。");
  if(!response.ok){
    if(response.status===401&&me){clearPrivate();render();}
    throw new Error(value.error||value.detail||"操作未完成，请重试。");
  }
  return value;
}
function clearPrivate(){authEpoch++;me=data=null;history=[];trace=[];preview=null;sessions=[];drafts.clear();page="overview";}
function saveDrafts(){
  document.querySelectorAll("#content form").forEach(form=>{
    const values={};form.querySelectorAll("input,select,textarea").forEach(input=>{if(input.name)values[input.name]=input.type==="checkbox"?input.checked:input.value;});
    drafts.set(form.id,values);
  });
}
function restoreDrafts(){
  document.querySelectorAll("#content form").forEach(form=>{
    const values=drafts.get(form.id);if(!values)return;
    form.querySelectorAll("input,select,textarea").forEach(input=>{if(input.name in values){if(input.type==="checkbox")input.checked=values[input.name];else input.value=values[input.name];}});
  });
}
const input=(name,label,value="",type="text",extra="")=>'<label>'+E(label)+'<input name="'+E(name)+'" type="'+type+'" value="'+E(value)+'" '+extra+'></label>';
const area=(name,label,value="",extra="")=>'<label>'+E(label)+'<textarea name="'+name+'" '+extra+'>'+E(value)+'</textarea></label>';
const select=(name,label,options,value)=>'<label>'+E(label)+'<select name="'+name+'">'+options.map(x=>'<option value="'+E(x)+'"'+(String(x)===String(value)?" selected":"")+'>'+E(x)+'</option>').join("")+'</select></label>';
const check=(name,label,checked=false)=>'<label class="check"><input type="checkbox" name="'+name+'"'+(checked?" checked":"")+'>'+E(label)+'</label>';
const confirm=(label="我核对了以上内容，确认保存")=>check("confirmed",label);
const submit=label=>'<div class="actions"><button type="submit">'+E(label)+'</button></div>';
const head=(eyebrow,title,text)=>'<div class="eyebrow">'+E(eyebrow)+'</div><h1>'+E(title)+'<span>.</span></h1><p class="intro">'+E(text)+'</p>';
const empty=text=>'<div class="empty">'+E(text)+'</div>';
function pretty(value){
  if(value===null||value===undefined)return"无";
  if(typeof value==="boolean")return value?"是":"否";
  if(Array.isArray(value))return value.map(pretty).join("、");
  if(typeof value==="object")return Object.entries(value).map(([key,v])=>(labels[key]||key)+"："+pretty(v)).join("\n");
  return String(value);
}
function table(headers,rows){return '<div class="table-wrap"><table><thead><tr>'+headers.map(x=>'<th>'+E(x)+'</th>').join("")+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(cell=>'<td>'+cell+'</td>').join("")+'</tr>').join("")+'</tbody></table></div>';}
function barChart(items){
  const entries=Object.entries(items);if(!entries.length)return empty("还没有真实学习记录。");
  const max=Math.max(...entries.map(x=>Number(x[1])),1),height=entries.length*42;
  return '<svg class="chart" role="img" aria-label="真实学习分钟图表" viewBox="0 0 660 '+height+'">'+entries.map(([name,amount],i)=>'<text x="0" y="'+(i*42+23)+'">'+E(name)+'</text><rect class="rail" x="140" y="'+(i*42+8)+'" width="430" height="20" rx="7"/><rect x="140" y="'+(i*42+8)+'" width="'+Math.round(Number(amount)/max*430)+'" height="20" rx="7"/><text x="585" y="'+(i*42+23)+'">'+E(amount)+' 分</text>').join("")+'</svg>';
}
function render(){
  $("#account-bar").innerHTML=me?'<span>'+E(me.personal.avatar)+" 已登录："+E(me.personal.nickname)+"（"+E(me.account.username)+"）"+(me.account.role==="developer"?" · 开发者":"")+'</span><button class="btn small" data-action="logout">退出登录</button>':"";
  $("#navigation").hidden=!me;
  $("#navigation").innerHTML=me?Object.entries(names).filter(([id])=>id!=="development"||me.account.role==="developer").map(([id,label])=>'<button data-page="'+id+'"'+(page===id?' aria-current="page"':"")+'>'+label+'</button>').join(""):"";
  const renderers={overview:overview,profile:profile,tasks:tasks,plan:plan,records:records,account:account,assistant:assistant,development:development};
  $("#content").innerHTML='<section class="page">'+(recoveryCode?recovery():me&&data?renderers[page]():login())+'</section>';
  restoreDrafts();
}
function login(){
  const tabs='<div class="auth-tabs">'+[["login","登录"],["register","注册账号"],["recover","找回密码"]].map(([id,title])=>'<button class="btn small" data-auth-page="'+id+'" aria-pressed="'+(authPage===id)+'">'+title+'</button>').join("")+'</div>';
  let fields=input("username","用户名","","text",'autocomplete="username" maxlength="64" required');
  if(authPage==="recover")fields+=input("recovery_code","恢复码","","password",'autocomplete="off" required')+input("new_password","新密码","","password",'autocomplete="new-password" maxlength="128" required')+input("password_again","再次输入新密码","","password",'autocomplete="new-password" required')+confirm("我确认重置密码，并让旧会话退出");
  else fields+=input("password","密码","","password",'autocomplete="'+(authPage==="login"?"current-password":"new-password")+'" maxlength="128" required')+(authPage==="register"?input("password_again","再次输入密码","","password",'autocomplete="new-password" required')+confirm("我确认创建自己的账号"):"");
  return '<div class="auth">'+head("HELLO / YOUR OWN LEARNING SPACE","为你的学习，留一个位置","登录自己的账号，让目标和每一步努力都有归处。")+(!accountServiceReady?'<div class="info">网页已上线，账号服务仍在准备中。数据库连接完成后，即可注册、登录并保存学习数据。</div>':"")+tabs+'<form id="auth-'+authPage+'" class="card" data-kind="'+authPage+'"><fieldset'+(accountServiceReady?"":" disabled")+'>'+fields+submit(authPage==="login"?"登录":authPage==="register"?"创建账号":"重置密码")+'</fieldset></form><small>用户名支持中文与常用符号，1–64 字；密码为 15–128 字。提交失败会保留填写内容。会话最长 12 小时，30 分钟无操作过期。</small></div>';
}
function recovery(){return '<div class="auth">'+head("KEEP IT SAFE","请保存你的恢复码","恢复码只显示这一次；丢失密码时可用于重置。")+'<div class="card"><p class="recovery">'+E(recoveryCode)+'</p><small>不要发给其他人。恢复码更新后旧码失效。</small><div class="actions"><button class="btn primary" data-action="saved-recovery">我已妥善保存，去登录</button></div></div></div>';}
function overview(){
  const p=data.progress,rate=p.completion_rate===null?"—":Math.round(p.completion_rate*100)+"%";
  return '<div class="hero"><div>'+head("01 / SMALL STEPS, REAL PROGRESS","把想学的，变成做到的","小步前进，也是在前进。今天的安排，从你的时间和真实记录出发。")+'<div class="actions"><button class="btn primary" data-page="tasks">添加学习任务 ↗</button><button class="btn" data-page="profile">调整学习档案</button></div></div><img src="/learning-map.svg" alt="学习路径插画"></div><div class="grid three"><div class="card metric"><span>本周真实学习</span><strong>'+p.actual_minutes+'<small>分钟</small></strong></div><div class="card metric"><span>本周到期任务</span><strong>'+p.completed_count+' / '+p.task_count+'</strong><small>已完成 / 全部</small></div><div class="card metric"><span>本周任务完成率</span><strong>'+rate+'</strong><small>按当前任务状态计算</small></div></div><h2>你的一周，有这些时间</h2><small>'+(data.profile_version?"来自已保存档案":"默认档案草稿，尚未保存")+' · 可用时间不代表已安排或真实学习</small><div class="days">'+me.options.days.map(day=>'<div class="day">'+day+'<strong>'+data.profile.availability[day].minutes+' 分</strong>'+E(data.profile.availability[day].devices.join(" / "))+'</div>').join("")+'</div><div class="grid"><div class="card"><h3>本周科目投入</h3>'+barChart(p.subjects)+'</div><div class="card"><h3>每周真实学习</h3>'+barChart(p.weekly_history)+'</div></div>';
}
function profile(){
  const p=data.profile,o=me.options;
  return head("02 / YOUR LEARNING PROFILE","给学习留一点空间","目标、时间和设备，按你的真实生活填写。目标可以为空。")+(data.profile_version?"":'<div class="info">以下为默认草稿，确认保存后才生效。</div>')+'<form id="profile-'+data.profile_version+'" data-kind="profile" data-version="'+data.profile_version+'" class="card"><h3>你的学习目标</h3>'+area("goals","学习目标",p.goals,'maxlength="2000" placeholder="例如：提高数学解题能力；也可以先留空"')+'<small>可直接编辑、删去某行或清空全部目标。需要 AI 协助时，可到 AI 助手讨论，修改仍需确认。</small><h2>时间与偏好</h2><div class="grid">'+input("weekly_hours","每周小时",p.weekly_hours,"number",'min="0.1" max="40" step="0.1" required')+select("speed","学习速度",o.speeds,p.speed)+input("max_session_minutes","单次学习时长上限（分钟）",p.max_session_minutes,"number",'min="1" max="180" required')+input("preference","学习偏好",p.preference,"text",'maxlength="500"')+'</div><h2>各科基础和优先级</h2>'+o.subjects.map((s,i)=>'<div class="grid">'+select("level_"+i,s+" · 当前水平",o.levels,p.levels[s])+select("priority_"+i,s+" · 优先级",o.priorities,p.priorities[s])+'</div>').join("")+'<h2>每天的时间和设备</h2><small>各天分钟总和应至少覆盖每周预算。</small>'+o.days.map((d,i)=>'<div class="card"><h3>'+d+'</h3>'+input("day_"+i,"可用分钟",p.availability[d].minutes,"number",'min="0" max="1440" required')+'<div class="checks">'+o.devices.map((device,j)=>check("device_"+i+"_"+j,device,p.availability[d].devices.includes(device))).join("")+'</div></div>').join("")+confirm()+submit("保存学习档案")+'</form>';
}
function taskFields(t={}){
  const o=me.options;
  return input("title","任务标题",t.title||"","text",'maxlength="120" required')+'<div class="grid">'+select("subject","科目",o.subjects,t.subject||"Python")+input("due_date","截止日期",t.due_date||me.today,"date","required")+input("estimated_minutes","预计学习分钟",t.estimated_minutes||45,"number",'min="1" max="1440" required')+select("priority","优先级",o.priorities,t.priority||"中")+select("status","状态",o.statuses,t.status||"待开始")+'</div>'+check("requires_computer","这项任务需要电脑",Boolean(t.requires_computer))+area("notes","任务备注",t.notes||"",'maxlength="2000"');
}
function tasks(){
  return head("03 / ONE TASK AT A TIME","让下一步，清楚一点","完成状态和真实用时分别记录。删除任务会保留已有学习记录。")+'<details><summary>＋ 创建学习任务</summary><form id="new-task" data-kind="task-create">'+taskFields()+confirm()+submit("创建任务")+'</form></details>'+(!data.tasks.length?empty("还没有任务。先从一个小任务开始。"):data.tasks.map(t=>'<article class="card"><div class="task-head"><div><h3>#'+t.id+' · '+E(t.title)+'</h3><span class="tag">'+E(t.subject)+'</span><span class="tag">'+E(t.status)+'</span><span class="tag">'+E(t.priority)+'优先级</span></div><small>截止 '+E(t.due_date)+' · 预计 '+t.estimated_minutes+' 分钟'+(t.requires_computer?" · 需要电脑":"")+'</small></div>'+(t.notes?'<p>'+E(t.notes)+'</p>':"")+'<details><summary>编辑任务</summary><form id="task-'+t.id+'-'+t.version+'" data-kind="task-update" data-id="'+t.id+'" data-version="'+t.version+'">'+taskFields(t)+confirm()+submit("保存任务修改")+'</form></details><details><summary>删除任务</summary><form id="delete-task-'+t.id+'" data-kind="task-delete" data-id="'+t.id+'" data-version="'+t.version+'">'+confirm("我确认删除此任务；历史真实用时保留")+submit("删除任务")+'</form></details></article>').join(""));
}
function renderPlan(p){
  return '<p><span class="tag">'+E(p.week_start)+' ～ '+E(p.week_end)+'</span></p><p>周预算 '+p.budget_minutes+' 分钟 · 已记录 '+p.actual_minutes+' 分钟 · 本次安排 '+p.planned_minutes+' 分钟 · 剩余 '+p.unused_minutes+' 分钟</p>'+(p.entries.length?table(["日期","任务","科目","分钟"],p.entries.map(e=>[E(e.date),E(e.title||e.task_title||"#"+e.task_id),E(e.subject),E(e.minutes)])):empty("当前约束下没有可安排的内容。"))+(p.unscheduled.length?'<h3>未安排部分</h3>'+table(["任务","说明"],p.unscheduled.map(e=>[E(e.title||"#"+e.task_id),E(pretty(e))])):"");
}
function plan(){
  return head("04 / MAKE ROOM FOR LEARNING","把时间，安排得刚刚好","按每周预算、每天时间、设备和截止日期生成规则计划。预览后再确认保存。")+'<form id="plan-preview" data-kind="plan-preview" class="card">'+input("week_of","选择这一周的任意日期",me.today,"date","required")+submit("生成计划预览")+'</form>'+(preview?'<div class="card"><h3>待保存预览</h3>'+renderPlan(preview.preview)+'<form id="plan-save" data-kind="plan-save">'+confirm(preview.expected_version?"我确认替换该周已保存计划":"我核对了计划，确认保存")+submit("保存计划")+'</form></div>':"")+'<h2>已保存计划</h2>'+(!data.plans.length?empty("尚未保存计划。"):data.plans.map(p=>'<details><summary>'+E(p.week_start)+' 所在周 · 版本 '+p.version+'</summary>'+renderPlan(p.payload)+'<form id="delete-plan-'+p.week_start+'" data-kind="plan-delete" data-week="'+p.week_start+'" data-version="'+p.version+'">'+confirm("我确认删除此周计划；任务和真实记录不变")+submit("删除此周计划")+'</form></details>').join(""));
}
function records(){
  return head("05 / REAL EFFORT COUNTS","认真记录，每一点投入","只填写确实发生的学习。预计时间和计划不会自动计入真实用时。")+(data.tasks.length?'<form id="record-create" data-kind="record-create" class="card"><label>关联任务<select name="task_id">'+data.tasks.map(t=>'<option value="'+t.id+'">#'+t.id+' '+E(t.title)+'</option>').join("")+'</select></label><div class="grid">'+input("study_date","实际学习日期",me.today,"date",'max="'+me.today+'" required')+input("minutes","实际分钟",30,"number",'min="1" max="1440" required')+'</div>'+area("note","备注","","maxlength=\"1000\"")+confirm("我确认这次学习确实发生，并保存记录")+submit("记录真实用时")+'</form>':empty("先创建一项任务，再记录学习用时。"))+'<h2>已有记录</h2>'+(!data.records.length?empty("还没有真实学习记录。"):data.records.map(r=>'<div class="card"><h3>'+E(r.task_title)+'</h3><p>'+E(r.study_date)+' · '+E(r.subject)+' · '+r.minutes+' 分钟'+(r.deleted_at?" · 原任务已删除":"")+'</p><p>'+E(r.note)+'</p><details><summary>删除误记</summary><form id="delete-record-'+r.id+'" data-kind="record-delete" data-id="'+r.id+'">'+confirm("我确认删除这条误记；统计会相应改变")+submit("删除记录")+'</form></details></div>').join(""))+'<div class="card"><h3>每周真实学习</h3>'+barChart(data.progress.weekly_history)+'</div>';
}
function account(){
  const p=data.personal;
  return head("06 / YOUR ACCOUNT","你的账号，由你掌握","个人资料、账号安全和数据管理。昵称与登录用户名相互独立。")+'<form id="personal-'+p.version+'" data-kind="personal" data-version="'+p.version+'" class="card"><h3>个人资料</h3><div class="grid">'+input("nickname","昵称",p.nickname,"text",'maxlength="64" required')+select("avatar","头像标识",me.options.avatars,p.avatar)+'</div>'+input("bio","个性签名",p.bio,"text",'maxlength="120"')+confirm()+submit("保存个人资料")+'</form><details><summary>修改登录用户名</summary><form id="username-change" data-kind="username" data-username="'+E(me.account.username)+'">'+input("new_username","新用户名",me.account.username,"text",'maxlength="64" required')+input("current_password","当前密码","","password",'autocomplete="current-password" required')+confirm("我确认修改登录用户名，并让其他会话退出")+submit("修改登录用户名")+'</form></details><details><summary>修改密码</summary><form id="password-change" data-kind="password">'+input("current_password","当前密码","","password",'autocomplete="current-password" required')+input("new_password","新密码","","password",'autocomplete="new-password" maxlength="128" required')+input("password_again","再次输入新密码","","password",'autocomplete="new-password" required')+confirm("我确认更新密码和恢复码，并退出全部旧会话")+submit("更新密码")+'</form></details><details><summary>登录会话管理</summary><button class="btn" data-action="load-sessions">查看有效登录会话</button><div id="session-list">'+sessionList()+'</div><form id="revoke-sessions" data-kind="revoke-sessions">'+confirm("我确认退出其他登录会话")+submit("退出其他会话")+'</form></details><div class="card"><h3>个人学习数据</h3><p class="muted">导出自己的资料、任务、记录、计划、提案与执行收据。不包含密码、恢复码和登录令牌。</p><a class="btn" href="/api/export" download="StudyPilot-export.json">导出 JSON</a></div>';
}
function sessionList(){return sessions.length?table(["登录时间","最近活动","会话"],sessions.map(s=>[E(new Date(s.created_at*1000).toLocaleString()),E(new Date(s.last_seen*1000).toLocaleString()),s.current?"当前":"其他"])):"";}
function proposal(p){
  const d=p.payload,expired=p.expires_at*1000<=Date.now();
  let content="";
  if(p.action==="save_schedule")content=(d.expected_version?'<div class="info">确认后替换这一周已保存的计划。</div>':"")+renderPlan(d.after);
  else if(p.action==="delete_task")content='<div class="info">将软删除任务 #'+d.task_id+'：'+E(d.before.title)+'。真实学习记录保留。</div><pre>'+E(pretty(d.before))+'</pre>';
  else if(p.action==="update_task"||p.action==="update_profile")content=table(["字段","当前内容","拟改为"],Object.entries(d.after).filter(([key,v])=>JSON.stringify(v)!==JSON.stringify(d.before[key])).map(([key,v])=>[E(labels[key]||key),'<pre>'+E(pretty(d.before[key]))+'</pre>','<pre>'+E(pretty(v))+'</pre>']));
  else content=(p.action==="log_session"?'<p>关联任务 #'+d.task_id+'：'+E(d.before.title)+'</p>':"")+'<pre>'+E(pretty(d.after))+'</pre>';
  return '<article class="card"><h3>'+E(actionNames[p.action]||p.action)+'</h3><p>'+E(p.reason)+'</p><small>编号 '+E(p.id.slice(0,8))+' · '+E(new Date(p.created_at*1000).toLocaleString())+' · 30 分钟有效</small>'+content+(expired?'<div class="info">提案已过期，请重新生成。</div>':'<form id="proposal-'+E(p.id)+'" data-kind="proposal-execute" data-id="'+E(p.id)+'">'+confirm(p.action==="log_session"?"我确认这次学习确实发生，并保存记录":"我核对了以上更改，确认执行")+submit("确认执行")+'</form>')+'<div class="actions"><button class="btn small" data-reject="'+E(p.id)+'">忽略提案</button></div></article>';
}
function assistant(){
  const pending=data.proposals.filter(p=>p.state==="pending"),applied=data.proposals.filter(p=>p.state==="applied").slice(0,5);
  return head("AI / YOUR STUDY ASSISTANT","先看清，再向前一步","查询真实学习情况，把修改建议留给你决定。")+(me.ai_configured?'<div class="info">对话使用 OpenAI。问题、上下文及工具读取的当前账号学习数据会发送给 OpenAI；账号凭据不会发送。</div>':'<div class="info">AI 未启用：服务未配置 OPENAI_API_KEY。本地功能和已有提案仍可使用。</div>')+'<div class="chat">'+history.map(m=>'<div class="bubble '+m.role+'"><span class="chat-label">'+(m.role==="user"?"你":"学习助手")+'</span>'+E(m.content)+'</div>').join("")+'</div><div class="actions"><button class="btn small" data-action="clear-chat">清空对话</button></div><form id="agent-chat" data-kind="agent-chat" class="card">'+input("model","模型",me.default_model,"text",'maxlength="100" required')+area("prompt","你想查询或调整什么？","","maxlength=\"3000\" placeholder=\"例如：看看我本周的学习情况；调整任务 #1，先给我看修改提案。\" required")+check("consent","我同意将本次问题、对话上下文及工具读取的学习数据发送给 OpenAI")+'<div class="actions"><button type="submit"'+(me.ai_configured?"":" disabled")+'>发送给学习助手</button><small id="agent-status"></small></div></form><small>对话仅保留在当前页面，刷新或退出后清除。提案和收据保存在当前账号中；聊天中的“确认”不会执行。</small>'+(trace.length?'<details><summary>本次工具调用记录</summary>'+table(["工具","状态"],trace.map(t=>[E(t.tool),E(t.state==="pending"?"待确认提案":t.state==="read"?"只读查询":"参数未通过")]))+'</details>':"")+'<h2>待确认的修改</h2>'+(!pending.length?empty("暂无待确认提案。只读查询不会修改数据。"):pending.map(proposal).join(""))+(applied.length?'<details><summary>最近执行记录</summary>'+table(["提案","操作","执行时间"],applied.map(p=>[E(p.id.slice(0,8)),E(actionNames[p.action]),E(new Date(p.applied_at*1000).toLocaleString())]))+'</details>':"");
}
function development(){
  return head("DEV / DEVELOPMENT PROGRESS","每一步，有迹可循","仅开发者可见。权限每次由服务端重新验证。")+'<div class="card"><h3>已完成</h3><p>账号与数据隔离、规则式学习计划、OpenAI 工具调用与提案确认、Vercel Web 入口与 PostgreSQL 持久化。</p><h3>尚未实现</h3><p>目标里程碑完成率、考试优先级自动调整。</p></div>';
}
async function refresh(){data=await api("/state");me.personal=data.personal;}
function numeric(form,name){return Number(new FormData(form).get(name));}
async function submitForm(form){
  const fd=new FormData(form),get=name=>String(fd.get(name)||""),checked=name=>fd.has(name),kind=form.dataset.kind;
  const body={confirmed:checked("confirmed")};
  let path="",method="POST",success="已保存。";
  if(kind==="login"){const identity=await api("/login","POST",{username:get("username"),password:get("password")});clearPrivate();me=identity;await refresh();notice("");render();return;}
  if(kind==="register"||kind==="recover"){
    const payload=kind==="register"?{username:get("username"),password:get("password"),password_again:get("password_again"),...body}:{username:get("username"),recovery_code:get("recovery_code"),new_password:get("new_password"),password_again:get("password_again"),...body};
    const result=await api(kind==="register"?"/register":"/recover","POST",payload);drafts.clear();recoveryCode=result.recovery_code;form.reset();render();return;
  }
  if(kind==="profile"){
    const levels={},priorities={},availability={};
    me.options.subjects.forEach((s,i)=>{levels[s]=get("level_"+i);priorities[s]=get("priority_"+i);});
    me.options.days.forEach((day,i)=>{availability[day]={minutes:numeric(form,"day_"+i),devices:me.options.devices.filter((_,j)=>checked("device_"+i+"_"+j))};});
    path="/profile";body.expected_version=Number(form.dataset.version);body.profile={goals:get("goals"),weekly_hours:numeric(form,"weekly_hours"),speed:get("speed"),preference:get("preference"),max_session_minutes:numeric(form,"max_session_minutes"),levels,priorities,availability};
  }else if(kind==="task-create"||kind==="task-update"){
    path="/tasks"+(kind==="task-update"?"/"+form.dataset.id:"");method=kind==="task-update"?"PUT":"POST";
    body.expected_version=Number(form.dataset.version||0);body.task={title:get("title"),subject:get("subject"),due_date:get("due_date"),estimated_minutes:numeric(form,"estimated_minutes"),priority:get("priority"),status:get("status"),requires_computer:checked("requires_computer"),notes:get("notes")};
  }else if(kind==="task-delete"){path="/tasks/"+form.dataset.id;method="DELETE";body.expected_version=Number(form.dataset.version);success="任务已删除，已有真实学习记录保留。";
  }else if(kind==="record-create"){path="/records";Object.assign(body,{task_id:numeric(form,"task_id"),study_date:get("study_date"),minutes:numeric(form,"minutes"),note:get("note")});
  }else if(kind==="record-delete"){path="/records/"+form.dataset.id;method="DELETE";success="误记已删除，统计已更新。";
  }else if(kind==="plan-preview"){preview=await api("/plans/preview?week_of="+encodeURIComponent(get("week_of")));saveDrafts();render();notice("已生成预览，尚未保存。");return;
  }else if(kind==="plan-save"){path="/plans";if(!preview)throw new Error("请先生成计划预览。");Object.assign(body,preview);
  }else if(kind==="plan-delete"){path="/plans/"+form.dataset.week;method="DELETE";body.expected_version=Number(form.dataset.version);success="此周计划已删除。";
  }else if(kind==="personal"){path="/personal";Object.assign(body,{expected_version:Number(form.dataset.version),nickname:get("nickname"),avatar:get("avatar"),bio:get("bio")});
  }else if(kind==="username"){path="/username";Object.assign(body,{new_username:get("new_username"),current_password:get("current_password"),expected_username:form.dataset.username});
  }else if(kind==="password"){
    const result=await api("/password","POST",{...body,current_password:get("current_password"),new_password:get("new_password"),password_again:get("password_again")});clearPrivate();recoveryCode=result.recovery_code;render();return;
  }else if(kind==="revoke-sessions"){path="/sessions/revoke";success="其他会话已退出。";
  }else if(kind==="proposal-execute"){path="/proposals/"+form.dataset.id+"/execute";success="提案已执行并保存；重复提交不会重复写入。";
  }else if(kind==="agent-chat"){
    const status=$("#agent-status");if(status)status.textContent="正在分析；修改只会生成提案…";
    let result;
    try{result=await api("/agent","POST",{prompt:get("prompt"),model:get("model"),consent:checked("consent"),history});}
    catch(error){try{data=await api("/state");saveDrafts();render();}catch{}throw error;}
    history=[...history,{role:"user",content:get("prompt")},{role:"assistant",content:result.text}].slice(-12);trace=result.trace;
    await refresh();drafts.delete(form.id);render();notice("答复已生成，修改仍需在提案卡片中确认。");return;
  }else throw new Error("此表单无法提交，请刷新后重试。");
  await api(path,method,body);
  saveDrafts();drafts.delete(form.id);
  if(kind==="plan-save")preview=null;
  if(kind==="username")me=await api("/me");
  if(kind==="revoke-sessions")sessions=await api("/sessions");
  await refresh();render();notice(success);
}
document.addEventListener("submit",async event=>{
  const form=event.target;if(!(form instanceof HTMLFormElement))return;
  event.preventDefault();const buttons=[...form.querySelectorAll("button")];buttons.forEach(b=>b.disabled=true);notice("");
  try{await submitForm(form);}catch(error){notice(error.message,"error");}
  finally{buttons.forEach(b=>b.disabled=false);const status=$("#agent-status");if(status)status.textContent="";}
});
document.addEventListener("click",async event=>{
  const button=event.target.closest("button");if(!button)return;
  try{
    if(button.dataset.themeChoice){theme(button.dataset.themeChoice);return;}
    if(button.dataset.page){saveDrafts();page=button.dataset.page;notice("");render();return;}
    if(button.dataset.authPage){saveDrafts();authPage=button.dataset.authPage;notice("");render();return;}
    if(button.dataset.reject){button.disabled=true;await api("/proposals/"+button.dataset.reject+"/reject","POST",{});saveDrafts();await refresh();render();notice("提案已忽略，没有修改学习数据。");return;}
    switch(button.dataset.action){
      case "dismiss":notice("");break;
      case "logout":await api("/logout","POST",{});clearPrivate();render();notice("已退出登录。");break;
      case "saved-recovery":recoveryCode="";authPage="login";render();notice("");break;
      case "clear-chat":history=[];trace=[];saveDrafts();render();break;
      case "load-sessions":sessions=await api("/sessions");$("#session-list").innerHTML=sessionList();break;
    }
  }catch(error){notice(error.message,"error");button.disabled=false;}
});
async function boot(){
  try{const health=await api("/health");accountServiceReady=health.database_configured;if(!accountServiceReady){render();return;}me=await api("/me");await refresh();render();}
  catch(error){clearPrivate();render();if(!/登录已失效/.test(error.message))notice(error.message,"error");}
}
boot();
