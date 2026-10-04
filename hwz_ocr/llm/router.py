import json
import logging
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, OpenAIError

from hwz_ocr.llm.providers import Provider, build_providers, call
from hwz_ocr.schema import QUOTA_PATH

logger = logging.getLogger(__name__)

TEXT_ORDER = ("gemini", "nvidia", "zai", "groq", "ollama")
VISION_ORDER = ("gemini", "groq", "zai")
DEFAULT_ORDER = TEXT_ORDER
MAX_ATTEMPTS_PER_PROVIDER = 3
BASE_BACKOFF_SECONDS = 2.0


class RouterExhausted(RuntimeError):
    pass


def is_retryable(error: Exception) -> bool:
    if isinstance(error, APIConnectionError):
        return True
    status_code = getattr(error, "status_code", None)
    return status_code == 429 or (isinstance(status_code, int) and status_code >= 500)


class QuotaLedger:
    def __init__(self, path: Path, today: Callable[[], date]):
        self.path = path
        self.today = today
        self.day = today().isoformat()
        self.counts: dict[str, int] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            stored = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        if stored.get("date") == self.day:
            self.counts = {name: int(count) for name, count in stored.get("counts", {}).items()}

    def roll_over_if_new_day(self) -> None:
        current_day = self.today().isoformat()
        if current_day != self.day:
            self.day = current_day
            self.counts = {}

    def used(self, name: str) -> int:
        self.roll_over_if_new_day()
        return self.counts.get(name, 0)

    def increment(self, name: str) -> None:
        self.roll_over_if_new_day()
        self.counts[name] = self.counts.get(name, 0) + 1
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"date": self.day, "counts": self.counts}, indent=2))


class Router:
    def __init__(
        self,
        providers: list[Provider],
        *,
        quota_path: Path = QUOTA_PATH,
        call_function: Callable[..., str] = call,
        sleep: Callable[[float], None] = time.sleep,
        today: Callable[[], date] = date.today,
        max_attempts: int = MAX_ATTEMPTS_PER_PROVIDER,
        base_backoff_seconds: float = BASE_BACKOFF_SECONDS,
    ):
        self.providers = {provider.name: provider for provider in providers}
        self.ledger = QuotaLedger(quota_path, today)
        self.call_function = call_function
        self.sleep = sleep
        self.max_attempts = max_attempts
        self.base_backoff_seconds = base_backoff_seconds

    @classmethod
    def from_env(cls, **options) -> "Router":
        load_dotenv()
        return cls(build_providers(), **options)

    def ordered_names(self, preferred: list[str] | None, needs_vision: bool = False) -> list[str]:
        base_order = VISION_ORDER if needs_vision else TEXT_ORDER
        names = list(preferred or []) + [
            name for name in base_order if name not in (preferred or [])
        ]
        names += [name for name in self.providers if name not in names]
        return [name for name in names if name in self.providers]

    def has_quota(self, provider: Provider) -> bool:
        return self.ledger.used(provider.name) < provider.daily_limit

    def candidates(self, needs_vision: bool, preferred: list[str] | None) -> list[Provider]:
        providers = [self.providers[name] for name in self.ordered_names(preferred, needs_vision)]
        if needs_vision:
            providers = [provider for provider in providers if provider.supports_vision]
        return providers

    def models_for(self, provider: Provider, needs_vision: bool) -> list[str]:
        primary = provider.vision_model if needs_vision else provider.text_model
        models = [primary, *provider.fallback_models]
        return list(dict.fromkeys(models))

    def try_provider(
        self, provider: Provider, *, prompt: str, image_png: bytes | None, model: str
    ) -> str | None:
        for attempt in range(self.max_attempts):
            if not self.has_quota(provider):
                return None
            self.ledger.increment(provider.name)
            try:
                return self.call_function(
                    provider, prompt=prompt, image_png=image_png, model=model, json_mode=True
                )
            except OpenAIError as error:
                logger.warning(
                    "%s/%s attempt %d failed: %s", provider.name, model, attempt + 1, error
                )
                if not is_retryable(error):
                    return None
                if attempt + 1 < self.max_attempts:
                    self.sleep(self.base_backoff_seconds * 2**attempt)
        return None

    def complete(
        self,
        *,
        prompt: str,
        image_png: bytes | None,
        needs_vision: bool,
        preferred: list[str] | None = None,
    ) -> tuple[str, str, str]:
        for provider in self.candidates(needs_vision, preferred):
            for model in self.models_for(provider, needs_vision):
                if not self.has_quota(provider):
                    break
                response = self.try_provider(
                    provider, prompt=prompt, image_png=image_png, model=model
                )
                if response is not None:
                    return response, provider.name, model
        raise RouterExhausted("no provider could complete the request")
