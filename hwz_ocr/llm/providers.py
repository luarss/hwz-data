import base64
import io
import os
from collections.abc import Mapping
from dataclasses import dataclass

import requests
from openai import OpenAI
from PIL import Image

DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MAX_OUTPUT_TOKENS = 16384
NEMOTRON_PARSE_MODEL = "nvidia/nemotron-parse"
NEMOTRON_PARSE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NEMOTRON_PARSE_MAX_IMAGE_BYTES = 180_000
NEMOTRON_PARSE_TIMEOUT_SECONDS = 180
NVIDIA_NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}
ZAI_NO_THINKING = {"thinking": {"type": "disabled"}}


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str
    key_env: str
    text_model: str
    vision_model: str | None
    daily_limit: int
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    fallback_models: tuple[str, ...] = ()
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    stream: bool = False
    extra_body: dict | None = None


PROVIDER_SPECS = (
    ProviderSpec(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        key_env="GEMINI_API_KEY",
        text_model="gemini-3.5-flash-lite",
        vision_model="gemini-3.8-flash",
        daily_limit=1500,
        max_output_tokens=65536,
        fallback_models=("gemini-3.5-flash-lite",),
    ),
    ProviderSpec(
        name="ollama",
        base_url="https://ollama.com/v1",
        key_env="OLLAMA_API_KEY",
        text_model="gpt-oss:120b-cloud",
        vision_model=None,
        daily_limit=300,
        max_output_tokens=32768,
    ),
    ProviderSpec(
        name="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        key_env="NVIDIA_API_KEY",
        text_model="nvidia/nemotron-3-super-120b-a12b",
        vision_model=None,
        daily_limit=300,
        max_output_tokens=32768,
        timeout_seconds=900,
        stream=True,
        extra_body=NVIDIA_NO_THINKING,
    ),
    ProviderSpec(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        key_env="GROQ_API_KEY",
        text_model="openai/gpt-oss-120b",
        vision_model="qwen/qwen3.8-27b",
        daily_limit=100,
        max_output_tokens=16384,
    ),
    ProviderSpec(
        name="zai",
        base_url="https://api.z.ai/api/paas/v4",
        key_env="ZAI_API_KEY",
        text_model="glm-4.7-flash",
        vision_model="glm-4.6v-flash",
        daily_limit=800,
        max_output_tokens=16384,
        extra_body=ZAI_NO_THINKING,
    ),
)


@dataclass(frozen=True)
class Provider:
    name: str
    client: OpenAI
    text_model: str
    vision_model: str | None
    daily_limit: int
    supports_vision: bool
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    fallback_models: tuple[str, ...] = ()
    stream: bool = False
    extra_body: dict | None = None


def build_provider(spec: ProviderSpec, api_key: str) -> Provider:
    client = OpenAI(
        base_url=spec.base_url,
        api_key=api_key,
        max_retries=0,
        timeout=spec.timeout_seconds,
    )
    return Provider(
        name=spec.name,
        client=client,
        text_model=spec.text_model,
        vision_model=spec.vision_model,
        daily_limit=spec.daily_limit,
        supports_vision=spec.vision_model is not None,
        max_output_tokens=spec.max_output_tokens,
        fallback_models=spec.fallback_models,
        stream=spec.stream,
        extra_body=spec.extra_body,
    )


def build_providers(environ: Mapping[str, str] | None = None) -> list[Provider]:
    environ = os.environ if environ is None else environ
    return [
        build_provider(spec, environ[spec.key_env])
        for spec in PROVIDER_SPECS
        if environ.get(spec.key_env)
    ]


def png_data_url(image_png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(image_png).decode("ascii")


def build_content(prompt: str, image_png: bytes | None) -> str | list[dict]:
    if image_png is None:
        return prompt
    return [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": png_data_url(image_png)}},
    ]


def build_request(
    provider: Provider, prompt: str, image_png: bytes | None, model: str, json_mode: bool
) -> dict:
    request = {
        "model": model,
        "messages": [{"role": "user", "content": build_content(prompt, image_png)}],
        "temperature": 0,
        "max_tokens": provider.max_output_tokens,
    }
    if json_mode:
        request["response_format"] = {"type": "json_object"}
    if provider.extra_body:
        request["extra_body"] = provider.extra_body
    return request


def collect_stream(stream) -> str:
    pieces = []
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            pieces.append(chunk.choices[0].delta.content)
    return "".join(pieces)


def call(
    provider: Provider,
    *,
    prompt: str,
    image_png: bytes | None,
    model: str,
    json_mode: bool,
) -> str:
    request = build_request(provider, prompt, image_png, model, json_mode)
    if provider.stream:
        return collect_stream(provider.client.chat.completions.create(**request, stream=True))
    response = provider.client.chat.completions.create(**request)
    return response.choices[0].message.content or ""


def shrink_for_inline_upload(image_png: bytes) -> tuple[str, bytes]:
    if len(image_png) <= NEMOTRON_PARSE_MAX_IMAGE_BYTES:
        return "image/png", image_png
    image = Image.open(io.BytesIO(image_png)).convert("RGB")
    for quality in (85, 70, 55, 40):
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        if buffer.tell() <= NEMOTRON_PARSE_MAX_IMAGE_BYTES:
            return "image/jpeg", buffer.getvalue()
        image = image.resize((int(image.width * 0.85), int(image.height * 0.85)))
    return "image/jpeg", buffer.getvalue()


def nemotron_parse(api_key: str, image_png: bytes, *, tool: str = "markdown_no_bbox") -> str:
    mime_type, payload = shrink_for_inline_upload(image_png)
    encoded = base64.b64encode(payload).decode("ascii")
    response = requests.post(
        NEMOTRON_PARSE_URL,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        json={
            "model": NEMOTRON_PARSE_MODEL,
            "tools": [{"type": "function", "function": {"name": tool}}],
            "messages": [
                {"role": "user", "content": f'<img src="data:{mime_type};base64,{encoded}" />'}
            ],
        },
        timeout=NEMOTRON_PARSE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    tool_calls = response.json()["choices"][0]["message"].get("tool_calls") or []
    return "".join(tool_call["function"]["arguments"] for tool_call in tool_calls)
