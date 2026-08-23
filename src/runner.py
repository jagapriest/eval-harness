"""Cached, concurrency-capped async runner for extraction calls.

Cache key is sha256 over (document, prompt, model, and every request parameter that
can change the output). Re-running a scored config must be free, or you will not
iterate. Every raw request and response is written to `results/raw/` -- when a
number looks wrong, you need the transcript, not a summary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "results" / "cache"
RAW_DIR = ROOT / "results" / "raw"

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
MAX_RETRIES = 5


@dataclass
class RunConfig:
    id: str
    model: str
    prompt_template: str
    effort: str | None = None
    structured_output: bool = False
    thinking: bool = False
    max_tokens: int = 8000
    input_per_mtok: float = 5.00
    output_per_mtok: float = 25.00
    cache_read_per_mtok: float = 0.50
    cache_write_per_mtok: float = 6.25

    def request_signature(self) -> dict[str, Any]:
        """Everything that can change the output. Cache key derives from this."""
        return {
            "model": self.model,
            "effort": self.effort,
            "structured_output": self.structured_output,
            "thinking": self.thinking,
            "max_tokens": self.max_tokens,
            "prompt_template": self.prompt_template,
        }


@dataclass
class CallResult:
    case_id: str
    config_id: str
    raw_text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_s: float = 0.0
    stop_reason: str | None = None
    model_version: str = ""
    from_cache: bool = False
    error: str | None = None
    attempts: int = 1

    def cost(self, cfg: RunConfig) -> float:
        return (
            self.input_tokens * cfg.input_per_mtok
            + self.output_tokens * cfg.output_per_mtok
            + self.cache_read_tokens * cfg.cache_read_per_mtok
            + self.cache_write_tokens * cfg.cache_write_per_mtok
        ) / 1_000_000

    def to_dict(self, cfg: RunConfig) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items()}
        d["cost_usd"] = round(self.cost(cfg), 6)
        return d


def cache_key(document: str, cfg: RunConfig) -> str:
    payload = json.dumps(
        {"document": document, **cfg.request_signature()}, sort_keys=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def read_cache(key: str) -> dict[str, Any] | None:
    p = _cache_path(key)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return None
    return None


def write_cache(key: str, payload: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(key).write_text(json.dumps(payload, indent=2))


def build_request(document: str, cfg: RunConfig) -> dict[str, Any]:
    from .schema import EXTRACTION_JSON_SCHEMA

    prompt = cfg.prompt_template.replace("{{DOCUMENT}}", document)
    req: dict[str, Any] = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    output_config: dict[str, Any] = {}
    if cfg.effort:
        output_config["effort"] = cfg.effort
    if cfg.structured_output:
        output_config["format"] = {
            "type": "json_schema",
            "schema": EXTRACTION_JSON_SCHEMA,
        }
    if output_config:
        req["output_config"] = output_config
    if cfg.thinking:
        req["thinking"] = {"type": "adaptive"}
    return req


async def run_one(
    client: anthropic.AsyncAnthropic,
    case_id: str,
    document: str,
    cfg: RunConfig,
    sem: asyncio.Semaphore,
    use_cache: bool = True,
) -> CallResult:
    key = cache_key(document, cfg)

    if use_cache:
        cached = read_cache(key)
        if cached is not None:
            return CallResult(
                case_id=case_id, config_id=cfg.id, from_cache=True,
                **{k: v for k, v in cached.items()
                   if k in CallResult.__dataclass_fields__
                   and k not in ("case_id", "config_id", "from_cache")},
            )

    req = build_request(document, cfg)

    async with sem:
        delay = 1.0
        last_error: str | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            started = time.monotonic()
            try:
                resp = await client.messages.create(**req)
                elapsed = time.monotonic() - started
                text = "".join(
                    b.text for b in resp.content if getattr(b, "type", "") == "text"
                )
                usage = resp.usage
                result = CallResult(
                    case_id=case_id,
                    config_id=cfg.id,
                    raw_text=text,
                    input_tokens=getattr(usage, "input_tokens", 0) or 0,
                    output_tokens=getattr(usage, "output_tokens", 0) or 0,
                    cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                    cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                    latency_s=round(elapsed, 3),
                    stop_reason=resp.stop_reason,
                    model_version=resp.model,
                    attempts=attempt,
                )
                RAW_DIR.mkdir(parents=True, exist_ok=True)
                (RAW_DIR / f"{cfg.id}__{case_id}.json").write_text(
                    json.dumps(
                        {"request": req, "response": resp.model_dump(mode="json")},
                        indent=2, default=str,
                    )
                )
                payload = {k: v for k, v in result.__dict__.items()
                           if k not in ("case_id", "config_id", "from_cache")}
                write_cache(key, payload)
                return result

            except anthropic.APIStatusError as exc:
                last_error = f"{exc.status_code}: {exc.message}"
                if exc.status_code not in RETRY_STATUS or attempt == MAX_RETRIES:
                    break
                await asyncio.sleep(delay)
                delay *= 2
            except anthropic.APIConnectionError as exc:
                last_error = f"connection: {exc}"
                if attempt == MAX_RETRIES:
                    break
                await asyncio.sleep(delay)
                delay *= 2

    return CallResult(
        case_id=case_id, config_id=cfg.id, raw_text="", error=last_error,
        attempts=MAX_RETRIES,
    )


async def run_all(
    cases: list[tuple[str, str]],
    cfg: RunConfig,
    concurrency: int = 4,
    use_cache: bool = True,
) -> list[CallResult]:
    client = anthropic.AsyncAnthropic()
    sem = asyncio.Semaphore(concurrency)
    tasks = [
        run_one(client, case_id, doc, cfg, sem, use_cache)
        for case_id, doc in cases
    ]
    return await asyncio.gather(*tasks)
