# StudyPilot：每次只学一个模块

先运行程序，然后按顺序阅读。第一周用 8 小时可以这样分配：安装和体验 1 小时、模块 1 练习 2 小时、模块 2 练习 2 小时、模块 3 练习 2 小时、复盘 1 小时。不需要现在理解所有 SQL 或界面代码。

## 模块 1：数据模型与校验（studypilot/models.py）

**解决什么问题**：统一“一个任务有哪些字段”，拒绝空标题、无效日期、负时长；保存未来排课需要的时间和设备约束。

**Python 知识**：变量、元组、字典、`@dataclass`、函数、`if` 判断、异常。`TaskInput` 可以理解成任务表格的一行；`validated()` 是提交前的检查员。`default_factory` 给每份档案创建独立字典，避免两份档案意外共享同一份可修改数据。

**Windows 上实验**：在项目根目录执行 `py` 进入交互环境，然后逐行输入：

```python
from datetime import date
from studypilot.models import TaskInput
task = TaskInput("写一个问候程序", "Python", date.today().isoformat(), 30)
task.validated()
```

最后一行返回字典，不会写数据库。把第一项改成空字符串，再调用 `validated()`，观察中文错误。输入 `exit()` 退出。

**亲自改哪几行**：搜索 `max_session_minutes: int = 45`，改成 `30`；搜索 `preference: str`，把默认偏好改成自己的话。它们只影响未保存的默认档案；已保存的资料应在界面修改。暂时不要改科目常量，因为它会影响已有数据的校验。

**如何测试**：`py -m unittest tests.test_database -v`。另外启动界面，检查尚未保存的默认档案是否显示 30 分钟；已有档案不需要删除。

## 模块 2：SQLite 数据库（studypilot/database.py）

**解决什么问题**：程序关闭后任务仍存在；创建、修改、删除与学习记录都先要求确认。数据库用版本号识别旧页面，避免覆盖刚刚保存的新内容。

**Python 知识**：类与方法、`with` 上下文管理器、`Path`、JSON、关键字参数。SQL 的 `?` 把用户输入当成数据，不能把任务标题当作 SQL 执行。事务让任务修改和历史记录一起成功或一起回滚。

**Windows 上实验**：运行 `py`，在交互环境中输入：

```python
from datetime import date
from studypilot.database import Database
from studypilot.models import TaskInput
db = Database("scratch.db")
task = TaskInput("测试任务", "数学", date.today().isoformat(), 20)
db.create_task(task)  # 会提示需要确认，不会保存
db.create_task(task, confirmed=True)  # 实验中手动明确确认
db.get_tasks()
```

退出 Python 后重新打开，再执行 `Database("scratch.db").get_tasks()`，任务仍然存在。此处使用独立实验数据库 `scratch.db`，不会影响应用数据；退出后可删除该实验文件，它也被 `.gitignore` 忽略。

**亲自改哪几行**：只搜索 `请先勾选确认，再提交更改。`，把提示文字改成自己更容易理解的句子。保留 `if confirmed is not True`，先不要改表结构或删除逻辑。

**如何测试**：`py -m unittest tests.test_database.DatabaseTests -v`，然后在界面尝试不勾确认提交。你在实验脚本中手动传 `True`，不代表未来可以让大模型自行确认。

## 模块 3：Streamlit 界面（app.py）

**解决什么问题**：不需要命令行输入任务，把表单值交给数据层，并显示成功和错误。`st.form` 等你点击提交才处理填写内容；成功后 `st.rerun()` 重新读取数据库。

**Python 知识**：模块导入、函数调用、`if/elif`、列表推导式、`lambda`。`commit()` 只在提交按钮被点击后执行操作，复用同一套错误处理。创建和记录表单提交后会清空，防止误复用已勾选的确认。

**Windows 上运行**：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

**亲自改哪几行**：搜索 `小步前进，也是在前进。`，换成自己的首页寄语。只改文字，不改 `key` 和提交逻辑。Streamlit 通常会提示或自动刷新；重新打开页面检查文字。

**如何测试**：`.\.venv\Scripts\python.exe -m unittest tests.test_app -v`。这些测试模拟点击表单并检查真实 SQLite 内容，使用临时数据库。

## 模块 4：真实学习统计（studypilot/progress.py）

**解决什么问题**：按周汇总实际分钟和科目比例；没有任务时不会乱算完成率，没有记录时不画假图。

**Python 知识**：日期运算、`timedelta`、列表筛选、`defaultdict`、除法、纯函数。`get_progress()` 只使用传入数据，不写数据库，容易单独验证。

**Windows 上实验**：进入 `py`，输入：

```python
from datetime import date
from studypilot.progress import week_bounds, get_progress
week_bounds(date(2026, 10, 11))
get_progress([], [], date(2026, 10, 11))["completion_rate"]
```

第一条得到周一和下一周周一；第二条得到 `None`，意思是没有任务，无法定义完成率。

**亲自改哪几行**：先不要改变统计口径。打开 `tests/test_database.py`，搜索 `test_empty_progress_does_not_claim_zero_completion`，在末尾添加 `self.assertEqual(result["weekly_history"], {})`。这是你写的第一条自动化断言。

**如何测试**：`py -m unittest tests.test_database.ProgressTests -v`。在界面记录一次真实学习，查看“实际分钟”是否相等；预计时长可以不同。

## 这一阶段只需掌握的路径

```text
你填写任务 → app.py 收集输入 → models.py 检查输入
          → database.py 保存 SQLite → progress.py 汇总 → app.py 展示
```

规则排课已在第二阶段实现；第三阶段新增模型选工具、修改提案与用户确认，见下面的小课。

## 第三阶段小课：工具调用不是自动授权

`agent.py` 把问题和工具定义交给 OpenAI Responses API。模型可能返回 `function_call`，服务端按工具白名单校验参数，把结果作为同一 call_id 的 `function_call_output` 发回，再让模型继续答复。完整响应项一同回传，轮次、调用次数和响应大小都有上限。这里用到列表、字典、JSON、循环、异常和依赖注入。

`agent_tools.py` 的六个查询工具通过只读 SQLite 连接获取当前账号数据。模型不能填写账号 ID、数据库路径或 SQL。六个 propose 工具只让 `proposals.py` 保存待审内容，不修改任务、档案、真实记录或已保存计划；不存在供模型调用的 execute 工具。

`agent_ui.py` 显示提案内容或前后差异。用户核对、勾选并点击“确认执行”后，独立入口重新验证账号、期限和版本，在一个事务中保存业务数据与执行收据。两次点击同一提案只产生一次结果。聊天里说“确认”不能替代这个入口。

```text
问题 → 模型选择工具 → 参数验证 → 只读结果 → 模型继续
                               → 修改提案 → 页面审阅 → 用户确认 → 原子执行与收据
```

先阅读 `tests/test_agent.py` 的协议循环测试：FakeResponses 只用于测试，提供可重复的模型响应，不发真实网络请求。试着把提案标题改成另一个实验标题，运行测试观察“确认前没有任务、确认后只有一个任务”的断言；不要给模型增加 confirmed 参数。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent -v
```

测试使用临时账号与数据库。真正联网需要按 README 配置本机 Key，并在助手页同意本次数据发送；本次开发没有真实 Key，因此不把离线协议验证当作联网模型验证。

## 界面改版新增：Python 与 CSS 怎么分工

`studypilot/theme.py` 解决组件外观复用的问题。它用函数生成页头、空状态和每周可用时间；`html.escape()` 先转义动态文本，避免学习目标中的尖括号被解释成页面代码。Python 负责决定显示什么，CSS 负责怎么显示。

`assets/style.css` 集中管理颜色、字体、留白、按钮和小窗口布局。`assets/learning-map.svg` 是项目原创插画，没有联网下载图片或字体的依赖。可以先只学一个 CSS 变量：搜索 `--accent: #df6045`，将重点色改成喜欢的颜色。若要修改原生控件的选中色，也要同步 `.streamlit/config.toml` 中的 `primaryColor`，然后重启服务。

Windows 运行命令仍是 `.\.venv\Scripts\python.exe -m streamlit run app.py`；测试仍是 `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`。改色后用浏览器刷新观察，不需要改数据库。

## 本次小课：输入值、提示文字和正式数据

目标管理解决的是“谁决定目标”的问题。`models.py` 中的 `goals: str = ""` 表示新档案没有目标；`app.py` 中的 `placeholder=GOAL_PLACEHOLDER` 只显示示例，输入框返回值仍然是空字符串。只有用户提交表单并确认后，`save_profile()` 才把真实输入写进 SQLite。

这里用到了字符串、函数参数、`if` 分支和表单事件。`required=False` 允许空字符串通过校验，因此用户可以清空目标；2000 字限制和文字类型检查仍然生效。旧数据没有来源信息时，不能用字符串相等来推断用户没有选择过它。

先亲自修改 `app.py` 中 `GOAL_PLACEHOLDER` 的一行示例，再打开一个空目标档案观察：提示变化，但目标仍为空。不要把示例写回 `StudyProfile.goals`。Windows 上双击 `Start-StudyPilot.cmd` 运行，用以下测试检查这个区别（在项目目录执行）：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_app.AppTests.test_goal_placeholder_is_not_real_data_and_empty_save_is_allowed -v
```

当前开发工作区如果复用 `work` 环境，将命令中的 Python 路径换为 `..\..\work\.venv\Scripts\python.exe`。测试使用临时数据库，不会改动你的真实档案。

## 本次小课：账号、会话与权限

先只看 `auth_ui.py` 中的 `login_gate()`：用户填写用户名和密码，界面调用 `auth.login()`；验证通过后只把随机会话令牌放入本次页面会话，不保存密码。`app.py` 每次执行都向 `auth.authenticate()` 确认令牌有效，之后才显示学习页面。

`auth.py` 解决“这个人是谁、能看哪些内容”的问题。这里用到数据类、随机数、哈希、上下文管理器和数据库事务。密码不能直接写进数据库，也不应自己设计加密算法；本项目使用 Python 的 `hashlib.scrypt()` 和随机盐，恢复码与高强度随机令牌只存 SHA-256 摘要。

每个账号生成一个随机 ID，只有服务端会把它转换成个人数据库路径。网页不能通过提交另一个人的用户名或 ID 来访问其学习记录。昵称和登录用户名独立，修改登录用户名也不改变账号 ID 或个人数据库路径。退出时清空页面状态，修改密码或恢复账号时撤销所有旧令牌。开发者角色同样从账号库读取，注册页面不能选择。

在 Windows 项目目录运行 `Start-StudyPilot.cmd`，先注册并保存恢复码，然后登录。测试命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_auth tests.test_auth_ui -v
```

没有项目 `.venv` 时，当前工作区可用 `..\..\work\.venv\Scripts\python.exe` 替代。测试使用临时账号与数据库。先尝试修改 `auth_ui.py` 中的登录欢迎语，然后运行测试；暂时不要修改哈希参数、令牌检查或角色判断。
