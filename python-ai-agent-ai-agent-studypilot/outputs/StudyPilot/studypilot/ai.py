"""服务器端免费模型适配器：主用智谱 GLM-4.7-Flash，备用硅基流动 Xing4.0-29B。

整个程序只有这一处知道服务地址和模型名：浏览器、对话内容和模型输出都不能指定
Base URL、模型或服务商，因此不会因为配置漂移而切到收费模型。两家接口都是
OpenAI 兼容的 /chat/completions，这里把内部使用的 Responses 形状
（instructions/input/tools → output）与对话形状互相转换，调用方不需要改动。

新增服务只能在此文件中显式写入常量；密钥只从服务端环境变量读取，
日志只记录服务商、模型、耗时、错误类型，不记录提示词、用户资料或密钥。
"""

from dataclasses import dataclass
import json
import logging
import os
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


CHAT_PATH = "/chat/completions"
DEFAULT_MAX_TOKENS = 1800
MAX_REQUEST_BYTES = 1_048_576
MAX_RESPONSE_BYTES = 1_048_576
LOG = logging.getLogger("studypilot.ai")


class AIError(ValueError):
    """可向用户展示的 AI 失败说明；不包含密钥、请求内容或上游原文。"""


class _NoRedirect(HTTPRedirectHandler):
    """不跟随重定向，避免带密钥的请求被转到其它主机。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Provider:
    """一家服务商的固定配置；全部来自代码，不来自环境变量、浏览器或模型。"""

    name: str
    label: str
    base_url: str
    model: str
    key_env: str


# 只有免费模型；没有收费服务的隐式兜底。改动这里等于改动服务商白名单。
PRIMARY = Provider("zhipu", "智谱 GLM-4.7-Flash", "https://open.bigmodel.cn/api/paas/v4",
                   "glm-4.7-flash", "ZHIPU_API_KEY")
BACKUP = Provider("siliconflow", "硅基流动 Xing4.0-29B", "https://api.siliconflow.cn/v1",
                  "XingChenAGI/Xing4.0-29B", "SILICONFLOW_API_KEY")
PROVIDERS = (PRIMARY, BACKUP)
DEFAULT_MODEL = PRIMARY.model

KIND_TEXT = {
    "rate_limit": "限流", "timeout": "超时", "network": "连接失败", "server_error": "服务端错误",
    "auth": "身份验证失败", "request": "请求被拒绝", "protocol": "响应格式异常",
    "empty": "空的响应", "oversize": "响应过大",
}


class ProviderFailure(Exception):
    """单家服务的失败；kind 只用于日志和友好提示。"""

    def __init__(self, kind, message, status=None):
        super().__init__(message)
        self.kind = kind
        self.status = status


def provider_key(provider, keys=None):
    value = (keys or {}).get(provider.name) if keys else None
    if value is None:
        value = os.getenv(provider.key_env, "")
    return value.strip() if isinstance(value, str) else ""


def ai_configured(keys=None):
    """至少配置了一家免费服务的密钥时才允许联网。"""
    return os.getenv("STUDYPILOT_AI_ENABLED", "1") == "1" and any(provider_key(provider, keys) for provider in PROVIDERS)


def configured_providers(keys=None):
    return tuple(provider for provider in PROVIDERS if provider_key(provider, keys))


def text_of(value):
    """把 Responses 的 content 或对话的 content 统一成纯文本。"""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts = []
    for part in value:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict):
            if isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part.get("refusal"), str):
                parts.append(part["refusal"])
    return "".join(parts)


def chat_messages(items, instructions=""):
    """把 Responses 形状的 input 转成对话消息；reasoning 等无对应字段的项不回传。"""
    messages = []
    if isinstance(instructions, str) and instructions.strip():
        messages.append({"role": "system", "content": instructions})
    open_assistant = None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind is None:
            role, content = item.get("role"), text_of(item.get("content"))
            if role not in ("user", "assistant", "system") or not content:
                continue
            messages.append({"role": role, "content": content})
            open_assistant = len(messages) - 1 if role == "assistant" else None
            continue
        if kind == "message":
            content = text_of(item.get("content"))
            if not content:
                continue
            messages.append({"role": "assistant", "content": content})
            open_assistant = len(messages) - 1
            continue
        if kind == "function_call":
            name, call_id, arguments = item.get("name"), item.get("call_id"), item.get("arguments")
            if not isinstance(name, str) or not isinstance(call_id, str):
                continue
            call = {"id": call_id, "type": "function",
                    "function": {"name": name, "arguments": arguments if isinstance(arguments, str) else "{}"}}
            if open_assistant is None:
                messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
                open_assistant = len(messages) - 1
            else:
                messages[open_assistant].setdefault("tool_calls", []).append(call)
            continue
        if kind == "function_call_output":
            output = item.get("output")
            if not isinstance(output, str):
                output = json.dumps(output, ensure_ascii=False, allow_nan=False, default=str)
            messages.append({"role": "tool", "tool_call_id": item.get("call_id", ""), "content": output})
            open_assistant = None
    return messages


def chat_tools(tools):
    """转换工具声明。不发送 strict：免费接口对未知字段容忍度不同；参数仍由服务端强制校验。"""
    converted = []
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        name, description, parameters = tool.get("name"), tool.get("description", ""), tool.get("parameters")
        if not isinstance(name, str) or not name or not isinstance(parameters, dict):
            continue
        converted.append({"type": "function", "function": {
            "name": name, "description": description if isinstance(description, str) else "", "parameters": parameters}})
    return converted


def chat_payload(provider, payload):
    """按服务商构造对话请求；模型名只来自常量，不来自调用方。"""
    maximum = payload.get("max_output_tokens") if isinstance(payload, dict) else None
    if type(maximum) is not int or not 64 <= maximum <= 8192:
        maximum = DEFAULT_MAX_TOKENS
    body = {"model": provider.model,
            "messages": chat_messages(payload.get("input"), payload.get("instructions")),
            "max_tokens": maximum, "stream": False}
    if provider == PRIMARY:
        body["thinking"] = {"type": "disabled"}
    tools = chat_tools(payload.get("tools"))
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    return body


def completion_output(data):
    """把对话响应转成 Responses 形状的 output；结构不符就当作该服务失败。"""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderFailure("protocol", "响应缺少可用的答复。")
    choice = choices[0]
    if choice.get("finish_reason") == "content_filter":
        raise ProviderFailure("request", "响应被服务商的安全策略拦截。")
    if choice.get("finish_reason") not in {"stop", "tool_calls"}:
        raise ProviderFailure("protocol", "响应未完整结束。")
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ProviderFailure("protocol", "响应缺少消息内容。")
    output = []
    text = text_of(message.get("content"))
    if text.strip():
        output.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]})
    calls = message.get("tool_calls")
    if calls is not None and not isinstance(calls, list):
        raise ProviderFailure("protocol", "工具调用格式不正确。")
    if len(calls or []) > 12:
        raise ProviderFailure("protocol", "工具调用过多。")
    for index, call in enumerate(calls or []):
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict):
            raise ProviderFailure("protocol", "工具调用格式不正确。")
        name, arguments = function.get("name"), function.get("arguments")
        if not isinstance(name, str) or not 1 <= len(name) <= 80:
            raise ProviderFailure("protocol", "工具调用缺少名称。")
        if not isinstance(arguments, str) or len(arguments) > 20000:
            raise ProviderFailure("protocol", "工具参数格式不正确。")
        call_id = call.get("id")
        if not isinstance(call_id, str) or not 1 <= len(call_id) <= 128:
            raise ProviderFailure("protocol", "工具调用缺少有效编号。")
        output.append({"type": "function_call", "name": name, "arguments": arguments, "call_id": call_id})
    if not output:
        raise ProviderFailure("empty", "模型未返回可展示的答复。")
    return {"status": "completed", "output": output}


def kind_for_status(status):
    if status == 429:
        return "rate_limit"
    if status == 408:
        return "timeout"
    if status in (401, 403):
        return "auth"
    if status >= 500:
        return "server_error"
    return "request"


class FreeChatTransport:
    """两家免费服务顺序尝试：先 GLM，失败再试硅基流动，一次请求最多两家。

    请求是非流式的，整段响应拿到后才向界面输出；因此不存在“流式输出已开始后
    切换模型”的情况。keys/opener/clock 只供测试注入，正常运行时全部来自环境变量和标准库。
    """

    def __init__(self, keys=None, opener=None, clock=time.monotonic):
        self._keys = dict(keys or {})
        self._opener = opener or build_opener(_NoRedirect())
        self._clock = clock
        self._failed = set()

    def key(self, provider):
        return provider_key(provider, self._keys)

    def available(self):
        if os.getenv("STUDYPILOT_AI_ENABLED", "1") != "1":
            raise AIError("免费 AI 已由管理员暂停，请稍后重试。")
        available = [(provider, self.key(provider)) for provider in PROVIDERS]
        available = [(provider, key) for provider, key in available if key]
        if not available:
            raise AIError("尚未配置免费模型密钥：请在服务端设置 ZHIPU_API_KEY（主模型）或 "
                          "SILICONFLOW_API_KEY（备用模型），本机不会改用其它收费服务。")
        return available

    def create(self, payload, *, timeout):
        failures = []
        available = [(provider, key) for provider, key in self.available() if provider.name not in self._failed]
        deadline = self._clock() + timeout
        for index, (provider, key) in enumerate(available):
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            started = self._clock()
            try:
                # Both attempts share the caller's time budget; leave time for fallback.
                attempt_timeout = remaining * .6 if index + 1 < len(available) else remaining
                data = self._post(provider, key, payload, attempt_timeout)
                result = completion_output(data)
            except ProviderFailure as failure:
                failures.append((provider, failure))
                self._record(provider, started, failure.kind, failure.status, failed=True)
                if failure.kind not in {"rate_limit", "timeout", "network", "server_error"}:
                    break
                self._failed.add(provider.name)
                continue
            self._record(provider, started, "ok", 200, failed=False)
            return result
        raise AIError(self._message(failures))

    def _post(self, provider, key, payload, timeout):
        try:
            body = json.dumps(chat_payload(provider, payload), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise ProviderFailure("request", "请求内容无法编码。") from None
        if len(body.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise AIError("本次上下文过大，请清空对话或缩小查询范围。")
        request = Request(provider.base_url + CHAT_PATH, data=body.encode("utf-8"), method="POST",
                          headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                   "Accept": "application/json"})
        try:
            with self._opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise ProviderFailure(kind_for_status(status), "服务返回错误状态。", status=status) from None
        except URLError as exc:
            kind = "timeout" if isinstance(exc.reason, (socket.timeout, TimeoutError)) else "network"
            raise ProviderFailure(kind, "无法连接服务。") from None
        except (TimeoutError, socket.timeout):
            raise ProviderFailure("timeout", "请求超时。") from None
        except OSError:
            raise ProviderFailure("network", "无法连接服务。") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderFailure("oversize", "响应超出大小上限。")
        try:
            data = json.loads(raw)
            json.dumps(data, ensure_ascii=False).encode("utf-8")
        except (ValueError, UnicodeError, RecursionError):
            raise ProviderFailure("protocol", "响应无法解析。") from None
        if not isinstance(data, dict):
            raise ProviderFailure("protocol", "响应结构不正确。")
        if data.get("error") and not data.get("choices"):
            code = data["error"].get("code") if isinstance(data["error"], dict) else None
            kind = "rate_limit" if str(code) in {"429", "1302", "1303", "1305"} else "request"
            raise ProviderFailure(kind, "服务返回错误信息。")
        return data

    @staticmethod
    def _message(failures):
        details = "、".join(f"{provider.label} {KIND_TEXT.get(failure.kind, '不可用')}"
                           for provider, failure in failures)
        return f"免费模型暂时不可用（{details or '服务不可用'}），请稍后重试；已有提案仍需你核对确认。"

    def _record(self, provider, started, outcome, status, *, failed):
        elapsed = max(0, int((self._clock() - started) * 1000))
        # 只记录非敏感信息：服务商、模型、结果、状态码、耗时。
        if failed:
            LOG.warning("free_ai provider=%s model=%s outcome=%s status=%s ms=%d",
                        provider.name, provider.model, outcome, status if status else "-", elapsed)
        else:
            LOG.info("free_ai provider=%s model=%s outcome=%s status=%s ms=%d",
                     provider.name, provider.model, outcome, status if status else "-", elapsed)
