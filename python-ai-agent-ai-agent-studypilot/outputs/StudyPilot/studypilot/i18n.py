"""Web presentation only: keep canonical stored values and user text unchanged."""
import re


def request_language(request):
    choices = []
    for index, item in enumerate(request.headers.get("accept-language", "zh-CN").split(",")):
        pieces = item.strip().lower().split(";")
        try:
            quality = next((float(part.strip()[2:]) for part in pieces[1:] if part.strip().startswith("q=")), 1.0)
        except ValueError:
            continue
        if quality > 0 and pieces[0].split("-")[0] in {"en", "zh"}:
            choices.append((quality, -index, "en" if pieces[0].startswith("en") else "zh-CN"))
    return max(choices)[2] if choices else "zh-CN"


MESSAGES = {
    "请求来源无效，请从本站页面重新提交。": "Invalid request origin. Submit this request from the StudyPilot website.",
    "请使用 JSON 请求。": "This request must use JSON.",
    "提交内容过大，请缩小范围。": "This request is too large. Please reduce its size.",
    "账号服务暂时不可用，请稍后重试。": "Account services are temporarily unavailable. Please try again later.",
    "服务暂时不可用，请稍后重试。若问题持续，请联系维护人员。": "The service is temporarily unavailable. Please try again later or contact support if this continues.",
    "提交字段或类型不正确，请检查后重试。输入内容已保留。": "Some fields or their types are invalid. Check your input and try again. Your input is preserved.",
    "登录已失效，请重新登录。": "Your session has expired. Please sign in again.",
    "确认凭据无效，请刷新页面。": "Your confirmation token is invalid. Refresh the page and try again.",
    "两次密码不一致，输入内容已保留。": "The passwords do not match. Your input is preserved.",
    "请先同意将本次问题、对话上下文及相关学习资料发送至上述模型服务商。": "Please first agree to send your question, conversation context, and relevant learning data to the listed model providers.",
    "仅开发者可查看。": "This page is available only to developers.",
    "请输入用户名。": "Enter a username.",
    "用户名不能包含换行、控制字符或不可见格式字符。": "Your username cannot contain line breaks, control characters, or invisible formatting characters.",
    "用户名须为 1–64 个字符，可使用中文、字母、数字、空格和常用符号。": "Your username must be 1–64 characters. Unicode letters, numbers, spaces, and common symbols are supported.",
    "密码须为 15–128 个字符，可以使用较长的短语。": "Your password must be 15–128 characters. A longer passphrase is welcome.",
    "请使用较难猜测的密码，避免空白或重复的单个字符。": "Choose a password that is hard to guess. Avoid whitespace-only passwords or a single repeated character.",
    "该用户名已被使用，请换一个用户名。": "This username is already in use. Choose another one.",
    "用户名、密码或恢复码不正确，或尝试过于频繁，请稍后重试。": "The username, password, or recovery code is incorrect, or there have been too many attempts. Please try again later.",
    "昵称和个性签名不能包含控制字符或不可见格式字符。": "Your display name and bio cannot contain control or invisible formatting characters.",
    "请选择提供的头像标识。": "Choose one of the available avatars.",
    "个人资料已在其他页面保存，请刷新。": "Your personal details were saved elsewhere. Refresh the page.",
    "个人资料已发生变化，请刷新后重新确认。": "Your personal details have changed. Refresh, review, and confirm again.",
    "登录用户名已发生变化，请刷新。": "Your sign-in username has changed. Refresh the page.",
    "账号状态已发生变化，请刷新。": "Your account status has changed. Refresh the page.",
    "请先勾选确认，再提交更改。": "Select the confirmation checkbox before submitting changes.",
    "每周学习时间须大于 0 且不超过 40 小时。": "Your weekly study budget must be more than 0 and no more than 40 hours.",
    "请选择有效的学习速度。": "Choose a valid learning pace.",
    "请为每个科目设置有效的当前水平。": "Choose a valid current level for every subject.",
    "请为每个科目设置有效的优先级。": "Choose a valid priority for every subject.",
    "请填写一周七天的可用时间。": "Set your availability for all seven days of the week.",
    "各天可用时间合计少于每周学习时间，请调整其中一项。": "Your daily availability is below your weekly study budget. Adjust one of these settings.",
    "科目、优先级或状态无效。": "The subject, priority, or status is invalid.",
    "档案已在其他页面保存，请刷新后重试。": "Your learning profile was saved elsewhere. Refresh and try again.",
    "档案已发生变化，请刷新后重新确认。": "Your learning profile has changed. Refresh, review, and confirm again.",
    "任务不存在或已删除，请刷新页面。": "This task does not exist or has been deleted. Refresh the page.",
    "任务已被修改或删除，请刷新后重新确认。": "This task was changed or deleted. Refresh, review, and confirm again.",
    "实际学习日期不能在未来。": "Actual study cannot be recorded for a future date.",
    "学习记录不存在，请刷新页面。": "This study record does not exist. Refresh the page.",
    "请先确认保存学习档案，再生成计划。": "Review and confirm your learning profile before generating a plan.",
    "计划预览无效，请重新生成。": "This plan preview is invalid. Generate a new preview.",
    "档案、任务、学习记录或其他周计划已变化，请重新生成预览。": "Your profile, tasks, study records, or other weekly plans have changed. Generate a new preview.",
    "计划内容与规则计算结果不一致，请重新生成。": "This plan does not match the scheduling rules. Generate a new preview.",
    "本周计划已在其他页面保存，请重新生成。": "This week's plan was saved elsewhere. Generate a new preview.",
    "本周计划已被修改或删除，请重新生成。": "This week's plan was changed or deleted. Generate a new preview.",
    "本周计划已被修改或删除，请刷新。": "This week's plan was changed or deleted. Refresh the page.",
    "请选择有效的计划日期。": "Choose a valid planning date.",
    "不能为已经过去的一周生成新计划。": "You cannot generate a new plan for a past week.",
    "任务编号须为正整数。": "Task IDs must be positive integers.",
    "不支持这种修改提案。": "This type of change is not supported.",
    "任务已变化，请重新读取后生成提案。": "This task has changed. Read it again before creating a suggestion.",
    "学习档案已变化，请重新读取后生成提案。": "Your learning profile has changed. Read it again before creating a suggestion.",
    "不能记录未来的实际学习。": "Actual study cannot be recorded for a future date.",
    "提案没有实际修改。": "This suggestion contains no changes.",
    "提案内容过大，请缩小修改范围。": "This suggestion is too large. Reduce the scope of the changes.",
    "待确认提案已达 20 项，请先处理已有提案。": "You have 20 pending suggestions. Review them before creating more.",
    "提案不存在或不属于当前账号。": "This suggestion does not exist or is not available to this account.",
    "提案已被忽略，不能执行。": "This suggestion was dismissed and cannot be applied.",
    "提案已超过 30 分钟，请重新生成。": "This suggestion has expired after 30 minutes. Generate a new one.",
    "任务已变化或删除，请重新生成提案。": "This task was changed or deleted. Generate a new suggestion.",
    "未知提案类型，未执行。": "This suggestion type is not supported. No changes were applied.",
    "提案已处理或不存在，请刷新。": "This suggestion was already handled or no longer exists. Refresh the page.",
    "今天全站 AI 使用额度已达上限，请明天再试；其他学习功能仍可正常使用。": "Today's site-wide AI limit has been reached. Try again tomorrow. Other learning features remain available.",
    "对话上下文过长，请清空后重试。": "This conversation is too long. Start a new chat and try again.",
    "对话上下文格式错误或过长，请清空后重试。": "The conversation context is invalid or too long. Start a new chat.",
    "对话只接受有长度限制的用户和助手文字消息。": "Conversations accept only user and assistant text messages within the length limits.",
    "对话包含无效文字编码，请检查后重试。": "This conversation contains invalid text encoding. Check the text and try again.",
    "本次处理达到时间上限，已停止；已生成的提案仍可在下方查看。": "The request timed out and was stopped. Any suggestions already created can still be reviewed below.",
    "本次上下文过大，请清空对话或缩小查询范围。": "This request has too much context. Start a new chat or narrow your question.",
    "模型未完成响应，已停止；下方已有提案尚未执行。": "The model did not finish its response. Existing suggestions below have not been applied.",
    "模型响应格式异常，已停止。": "The model returned an invalid response. The request was stopped.",
    "模型消息格式异常，已停止。": "The model returned an invalid message. The request was stopped.",
    "模型未返回可展示的答复，请重试。": "The model returned no reply to display. Please try again.",
    "本次工具调用达到上限，已停止；已生成提案仍待用户确认。": "The tool-call limit was reached. Any suggestions already created still need your confirmation.",
    "模型处理轮次达到上限，已停止；下方已有提案仍待确认。": "The processing limit was reached. Existing suggestions still need your confirmation.",
    "对话语言不受支持。": "Choose English or Simplified Chinese.",
}

FIELDS = {
    "问题": "Question", "学习目标": "Learning goals", "学习偏好": "Learning preferences", "单次学习时长": "Session length",
    "任务标题": "Task title", "任务备注": "Task notes", "截止日期": "Due date", "预计时长": "Estimated duration",
    "昵称": "Display name", "个性签名": "Bio", "备注": "Notes", "实际分钟": "Actual minutes", "实际学习日期": "Study date",
    "周一": "Monday", "周二": "Tuesday", "周三": "Wednesday", "周四": "Thursday", "周五": "Friday", "周六": "Saturday", "周日": "Sunday",
}


def error_text(message, language):
    message = str(message)
    if language != "en":
        return message
    if message in MESSAGES:
        return MESSAGES[message]
    patterns = (
        (r"(.+)必须是文字。", "{field} must be text."),
        (r"请填写(.+)。", "Enter {field}."),
        (r"(.+)最多 (\d+) 字。", "{field} must be at most {amount} characters."),
        (r"(.+)必须是 1–(\d+) 的整数分钟。", "{field} must be a whole number of minutes between 1 and {amount}."),
        (r"(.+)须使用 YYYY-MM-DD 格式。", "{field} must use YYYY-MM-DD format."),
        (r"(.+)可用时间和设备格式无效。", "Check the time and devices for {field}."),
        (r"(.+)可用时间须为 0–1440 分钟的整数。", "Availability for {field} must be a whole number from 0 to 1440 minutes."),
        (r"(.+)设备无效。", "Choose valid devices for {field}."),
        (r"(.+)有可用时间，请至少选择一种设备。", "Choose at least one device for {field}, or set its available time to zero."),
    )
    for pattern, template in patterns:
        match = re.fullmatch(pattern, message)
        if match and match[1] in FIELDS:
            return template.format(field=FIELDS[match[1]], amount=match[2] if len(match.groups()) > 1 else "")
    if message.startswith("AI 请求过于频繁"):
        return "You have made too many AI requests. Please wait a few minutes and try again."
    # Unknown domain errors must remain helpful and cannot leak unreviewed data.
    return "Unable to complete this request. Check your input and try again. If this continues, contact support."
