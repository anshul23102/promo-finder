"""One small client for every model provider.

A model is named as ``provider:model`` on the command line, for example
``gemini:gemini-flash-latest``, ``groq:openai/gpt-oss-120b`` or
``ollama:qwen3:4b``. Any OpenAI-compatible endpoint (including one Kuku
provides) works with ``openai-compatible:<model>`` plus PROMO_BASE_URL and
PROMO_API_KEY. Swapping models never touches pipeline code.

Every answer is validated against a JSON schema and cached by a hash of the
exact request, so re-runs are free and every raw reply is kept for audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import random
import re
import tempfile
import time
from urllib import error, request

PRESETS = {
    # name: (base URL, API key variable, default model, requests per minute)
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-3.5-flash-lite|gemini-3.1-flash-lite|gemini-flash-lite-latest", 12),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b", 25),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "openai/gpt-oss-120b:free", 15),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-5-mini", 60),
    "ollama": ("http://127.0.0.1:11434", None, "qwen3:4b", 600),
    "openai-compatible": (None, "PROMO_API_KEY", None, 30),
}


class ModelError(RuntimeError):
    pass


def load_dotenv(path: Path = Path(".env")) -> None:
    """Read KEY=value lines without overriding the real environment."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def canonical(data) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(handle.name, path)


def obj(**fields) -> dict:
    """A strict JSON-schema object where every field is required."""
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def string(*choices: str, **extra) -> dict:
    return {"type": "string", "enum": list(choices), **extra} if choices else {"type": "string", **extra}


def array(items: dict, **extra) -> dict:
    return {"type": "array", "items": items, **extra}


INTEGER = {"type": "integer"}


def check(value, schema, where="reply"):
    """Validate the subset of JSON schema used in this project."""
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{where}: expected object")
        for name in schema.get("required", []):
            if name not in value:
                raise ValueError(f"{where}: missing {name}")
        return {name: check(value[name], sub, f"{where}.{name}") for name, sub in schema["properties"].items() if name in value}
    if kind == "array":
        if not isinstance(value, list):
            raise ValueError(f"{where}: expected list")
        return [check(item, schema["items"], f"{where}[{i}]") for i, item in enumerate(value)]
    if kind == "integer":
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if type(value) is not int:
            raise ValueError(f"{where}: expected integer")
    elif kind == "number":
        if type(value) not in (int, float):
            raise ValueError(f"{where}: expected number")
    elif kind == "string":
        if not isinstance(value, str):
            raise ValueError(f"{where}: expected text")
        value = value.strip()
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{where}: {value!r} not one of {schema['enum']}")
    return value


def _loose_schema(schema):
    """Gemini's OpenAI layer rejects some keywords; validation still happens locally."""
    if isinstance(schema, dict):
        return {k: _loose_schema(v) for k, v in schema.items() if k != "additionalProperties"}
    if isinstance(schema, list):
        return [_loose_schema(v) for v in schema]
    return schema


def _json_from(text: str):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


@dataclass
class Model:
    spec: str
    cache: Path = Path("private/cache")
    key: str | None = None        # per-run key (e.g. typed in the web app); falls back to the environment
    base_url: str | None = None   # per-run endpoint override for openai-compatible
    provider: str = field(init=False)
    name: str = field(init=False)
    calls: int = 0
    hits: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    _last: float = 0.0

    def __post_init__(self):
        provider, _, name = self.spec.partition(":")
        if provider not in PRESETS:
            raise ValueError(f"Unknown provider {provider!r}. Use one of: {', '.join(PRESETS)}")
        base, key_var, default, rpm = PRESETS[provider]
        self.names = [n.strip() for n in (name or default or "").split("|") if n.strip()]
        self.provider, self.name = provider, (self.names[0] if self.names else "")
        self.base = self.base_url or (os.environ.get("PROMO_BASE_URL") if provider == "openai-compatible" else base) or ""
        if provider == "ollama":
            self.base = os.environ.get("OLLAMA_HOST_URL", base)
        if not self.base or not self.name:
            raise ValueError("openai-compatible needs PROMO_BASE_URL and a model name")
        self.key = self.key or (os.environ.get(key_var) if key_var else None)
        if key_var and not self.key:
            raise ValueError(f"{self.spec} needs {key_var}. Put it in .env (see .env.example) or pick another --model.")
        self.interval = 60.0 / rpm
        self.base = self.base.rstrip("/")

    @property
    def label(self) -> str:
        """Provider and the model chain, e.g. gemini:a|b (the first that is up is used)."""
        return f"{self.provider}:{'|'.join(self.names)}"

    @property
    def local(self) -> bool:
        return self.provider == "ollama"

    def ask(self, stage: str, system: str, user: str, schema: dict, **kwargs) -> dict:
        """Try each model in the chain; fall through only on overload, rate limit or network errors."""
        last = None
        for name in self.names:
            self.name = name
            try:
                return self._ask(stage, system, user, schema, **kwargs)
            except ModelError as exc:
                last = exc
                if not re.search(r"HTTP (404|408|429|5\d\d)|could not reach|kept rate-limiting", str(exc)):
                    raise
        raise last

    def _ask(self, stage: str, system: str, user: str, schema: dict, *, temperature: float = 0.0,
             seed: int = 7, max_tokens: int = 4000) -> dict:
        """Return {'answer': validated JSON, 'raw': text, ...}; cached by exact request."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.local:
            url = self.base + "/api/chat"
            body = {"model": self.name, "stream": False, "format": schema, "messages": messages, "think": False,
                    "options": {"temperature": temperature, "seed": seed, "num_ctx": 8192, "num_predict": max_tokens}}
        else:
            url = self.base + "/chat/completions"
            fmt = _loose_schema(schema) if self.provider == "gemini" else schema
            body = {"model": self.name, "messages": messages, "temperature": temperature,
                    "response_format": {"type": "json_schema", "json_schema": {"name": stage, "schema": fmt, "strict": self.provider != "gemini"}}}
            if self.provider != "gemini":
                body["seed"] = seed
        digest = hashlib.sha256(canonical([f"{self.provider}:{self.name}", url, body]).encode()).hexdigest()
        path = self.cache / f"{digest}.json"
        if path.is_file():
            record = json.loads(path.read_text(encoding="utf-8"))
            self.hits += 1
            return record
        last_problem = ""
        for attempt in range(6):
            payload = self._post(url, body, stage)
            try:
                if self.local:
                    raw = payload["message"]["content"]
                    usage = (payload.get("prompt_eval_count", 0), payload.get("eval_count", 0))
                else:
                    raw = payload["choices"][0]["message"]["content"] or ""
                    u = payload.get("usage") or {}
                    usage = (u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
                answer = check(_json_from(raw), schema)
                break
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                last_problem = str(exc)[:200]
                body = {**body}
                if not self.local:
                    body["temperature"] = 0.3  # a fresh sample after an invalid reply
                else:
                    body["options"] = {**body["options"], "seed": seed + attempt + 1}
        else:
            raise ModelError(f"{stage}: {self.label} gave no valid structured reply ({last_problem})")
        self.calls += 1
        self.tokens_in += usage[0] or 0
        self.tokens_out += usage[1] or 0
        record = {"stage": stage, "model": f"{self.provider}:{self.name}", "answer": answer, "raw": raw, "tokens": list(usage),
                  "request_digest": digest}
        save_json(path, record)
        return record

    def _post(self, url, body, stage):
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        data = json.dumps(body).encode()
        for attempt in range(8):
            wait = self._last + self.interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                with request.urlopen(request.Request(url, data, headers), timeout=240) as response:
                    return json.load(response)
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                limit = 2 if exc.code in (500, 502, 503, 504) else 6  # overloaded: let the chain move on
                if exc.code in (408, 409, 429, 500, 502, 503, 504) and attempt < limit:
                    retry = exc.headers.get("retry-after")
                    pause = float(retry) if retry and retry.replace(".", "").isdigit() else min(90, 4 * 2 ** attempt)
                    time.sleep(pause + random.random())
                    continue
                raise ModelError(f"{stage}: {self.label} returned HTTP {exc.code}: {detail}") from exc
            except (OSError, ValueError) as exc:
                if attempt < 1:
                    time.sleep(3)
                    continue
                raise ModelError(f"{stage}: could not reach {self.label} ({type(exc).__name__}: {exc})") from exc
        raise ModelError(f"{stage}: {self.label} kept rate-limiting; cached answers are kept, re-run to resume")

    def usage(self) -> dict:
        return {"model": self.label, "calls": self.calls, "cache_hits": self.hits,
                "input_tokens": self.tokens_in, "output_tokens": self.tokens_out}
