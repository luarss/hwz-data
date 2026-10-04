import json
from datetime import date

import pytest
from openai import OpenAIError

from hwz_ocr.llm.providers import Provider
from hwz_ocr.llm.router import Router, RouterExhausted


class StatusError(OpenAIError):
    def __init__(self, status_code: int):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def make_provider(name: str, *, supports_vision: bool = True, daily_limit: int = 10) -> Provider:
    return Provider(
        name=name,
        client=None,
        text_model=f"{name}-text",
        vision_model=f"{name}-vision" if supports_vision else None,
        daily_limit=daily_limit,
        supports_vision=supports_vision,
    )


class FakeCaller:
    def __init__(self, behaviours: dict[str, list]):
        self.behaviours = behaviours
        self.calls: list[tuple[str, str]] = []

    def __call__(self, provider, *, prompt, image_png, model, json_mode):
        self.calls.append((provider.name, model))
        queue = self.behaviours.get(provider.name, ["ok"])
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(outcome, Exception):
            raise outcome
        return f"{outcome}:{provider.name}"


def build_router(tmp_path, providers, caller, today=date(2026, 10, 4)):
    sleeps: list[float] = []
    router = Router(
        providers,
        quota_path=tmp_path / "quota.json",
        call_function=caller,
        sleep=sleeps.append,
        today=lambda: today,
    )
    return router, sleeps


def test_default_order_prefers_gemini(tmp_path):
    providers = [make_provider("groq"), make_provider("github"), make_provider("gemini")]
    router, _ = build_router(tmp_path, providers, FakeCaller({}))
    response, provider_name, model = router.complete(
        prompt="p", image_png=None, needs_vision=False, preferred=None
    )
    assert (response, provider_name, model) == ("ok:gemini", "gemini", "gemini-text")


def test_preferred_order_overrides_default(tmp_path):
    providers = [make_provider("gemini"), make_provider("groq")]
    router, _ = build_router(tmp_path, providers, FakeCaller({}))
    _, provider_name, _ = router.complete(
        prompt="p", image_png=None, needs_vision=False, preferred=["groq"]
    )
    assert provider_name == "groq"


def test_vision_skips_text_only_providers(tmp_path):
    providers = [make_provider("gemini", supports_vision=False), make_provider("nvidia")]
    caller = FakeCaller({})
    router, _ = build_router(tmp_path, providers, caller)
    _, provider_name, model = router.complete(
        prompt="p", image_png=b"png", needs_vision=True, preferred=None
    )
    assert (provider_name, model) == ("nvidia", "nvidia-vision")
    assert caller.calls == [("nvidia", "nvidia-vision")]


def test_rate_limit_backs_off_then_falls_back(tmp_path):
    providers = [make_provider("gemini"), make_provider("nvidia")]
    caller = FakeCaller({"gemini": [StatusError(429)]})
    router, sleeps = build_router(tmp_path, providers, caller)
    _, provider_name, _ = router.complete(prompt="p", image_png=None, needs_vision=False)
    assert provider_name == "nvidia"
    assert [name for name, _ in caller.calls] == ["gemini", "gemini", "gemini", "nvidia"]
    assert sleeps == [2.0, 4.0]


def test_server_error_recovers_on_retry(tmp_path):
    caller = FakeCaller({"gemini": [StatusError(503), "ok"]})
    router, sleeps = build_router(tmp_path, [make_provider("gemini")], caller)
    response, _, _ = router.complete(prompt="p", image_png=None, needs_vision=False)
    assert response == "ok:gemini"
    assert sleeps == [2.0]


def test_client_error_moves_on_without_retry(tmp_path):
    providers = [make_provider("gemini"), make_provider("groq")]
    caller = FakeCaller({"gemini": [StatusError(400)]})
    router, sleeps = build_router(tmp_path, providers, caller)
    _, provider_name, _ = router.complete(prompt="p", image_png=None, needs_vision=False)
    assert provider_name == "groq"
    assert sleeps == []


def test_exhausted_quota_is_skipped(tmp_path):
    providers = [make_provider("gemini", daily_limit=1), make_provider("groq")]
    router, _ = build_router(tmp_path, providers, FakeCaller({}))
    first = router.complete(prompt="p", image_png=None, needs_vision=False)[1]
    second = router.complete(prompt="p", image_png=None, needs_vision=False)[1]
    assert (first, second) == ("gemini", "groq")


def test_raises_when_nothing_left(tmp_path):
    providers = [make_provider("gemini", supports_vision=False)]
    router, _ = build_router(tmp_path, providers, FakeCaller({}))
    with pytest.raises(RouterExhausted):
        router.complete(prompt="p", image_png=b"png", needs_vision=True)


def test_quota_persists_across_router_instances(tmp_path):
    providers = [make_provider("gemini", daily_limit=2), make_provider("groq")]
    router, _ = build_router(tmp_path, providers, FakeCaller({}))
    router.complete(prompt="p", image_png=None, needs_vision=False)
    router.complete(prompt="p", image_png=None, needs_vision=False)
    stored = json.loads((tmp_path / "quota.json").read_text())
    assert stored == {"date": "2026-10-04", "counts": {"gemini": 2}}
    reloaded, _ = build_router(tmp_path, providers, FakeCaller({}))
    assert reloaded.complete(prompt="p", image_png=None, needs_vision=False)[1] == "groq"


def test_quota_resets_on_new_date(tmp_path):
    (tmp_path / "quota.json").write_text(
        json.dumps({"date": "2026-10-03", "counts": {"gemini": 99}})
    )
    providers = [make_provider("gemini", daily_limit=5)]
    router, _ = build_router(tmp_path, providers, FakeCaller({}))
    assert router.complete(prompt="p", image_png=None, needs_vision=False)[1] == "gemini"
    stored = json.loads((tmp_path / "quota.json").read_text())
    assert stored == {"date": "2026-10-04", "counts": {"gemini": 1}}


def test_quota_rolls_over_during_run(tmp_path):
    current_day = {"value": date(2026, 10, 4)}
    providers = [make_provider("gemini", daily_limit=1)]
    router = Router(
        providers,
        quota_path=tmp_path / "quota.json",
        call_function=FakeCaller({}),
        sleep=lambda seconds: None,
        today=lambda: current_day["value"],
    )
    router.complete(prompt="p", image_png=None, needs_vision=False)
    with pytest.raises(RouterExhausted):
        router.complete(prompt="p", image_png=None, needs_vision=False)
    current_day["value"] = date(2026, 10, 5)
    assert router.complete(prompt="p", image_png=None, needs_vision=False)[1] == "gemini"


def test_fallback_model_used_when_primary_unavailable(tmp_path):
    provider = Provider(
        name="gemini",
        client=None,
        text_model="lite",
        vision_model="flash",
        daily_limit=10,
        supports_vision=True,
        fallback_models=("lite",),
    )

    def caller(provider, *, prompt, image_png, model, json_mode):
        if model == "flash":
            raise StatusError(503)
        return "ok"

    router, _ = build_router(tmp_path, [provider], caller)
    assert router.complete(prompt="p", image_png=b"png", needs_vision=True) == (
        "ok",
        "gemini",
        "lite",
    )
    assert router.models_for(provider, needs_vision=False) == ["lite"]
