"""
LLM providers for the extraction stages.

    AnthropicProvider(api_key, model)   — real calls through the official SDK, forced tool use, disk cache
    MockProvider(replay_dir)            — replays canned tool inputs from <replay_dir>/<stage>[__<sheet>].json
                                          (tests, CI, demos; no network)

Every call returns a CallResult(data=<tool input dict>, usage={...}, cached=bool, model=str).
The cache key covers model + system + the message content (images by SHA-256) + the tool schema, so a re-run
of the same job on the same drawings costs nothing, and an edited prompt or a revised sheet re-runs only the
affected stage.
"""
from __future__ import annotations
import base64, hashlib, json, os, time
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-opus-5-5"
MODEL_CHOICES = ["claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
# $ per million tokens — EDIT in Settings when prices change; used only for the running cost estimate in the log
DEFAULT_RATES = {"claude-fable-5-1": (15.0, 75.0), "claude-opus-5-5": (15.0, 75.0), "claude-sonnet-5-5": (3.0, 15.0), "claude-haiku-5-5": (1.0, 5.0)}


@dataclass
class CallResult:
    data: dict
    usage: dict = field(default_factory=dict)
    cached: bool = False
    model: str = ""
    elapsed: float = 0.0

    def cost(self, rates: dict | None = None) -> float:
        r = (rates or DEFAULT_RATES).get(self.model)
        if not r or self.cached:
            return 0.0
        return (self.usage.get("input_tokens", 0) * r[0] + self.usage.get("output_tokens", 0) * r[1]) / 1e6


def image_block(png_bytes: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png_bytes).decode("ascii")}}


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def _fingerprint(model: str, system: str, blocks: list[dict], tool: dict) -> str:
    h = hashlib.sha256()
    h.update(model.encode()); h.update(system.encode()); h.update(json.dumps(tool, sort_keys=True).encode())
    for b in blocks:
        if b.get("type") == "image":
            h.update(b"img:" + hashlib.sha256(b["source"]["data"].encode()).digest())
        else:
            h.update(b"txt:" + b.get("text", "").encode())
    return h.hexdigest()[:24]


class DiskCache:
    def __init__(self, cache_dir: str | None):
        self.dir = cache_dir
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def get(self, stage: str, key: str) -> dict | None:
        if not self.dir:
            return None
        p = os.path.join(self.dir, f"{stage}_{key}.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        return None

    def put(self, stage: str, key: str, payload: dict) -> None:
        if not self.dir:
            return
        with open(os.path.join(self.dir, f"{stage}_{key}.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1)


class AnthropicProvider:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, cache_dir: str | None = None, max_tokens: int = 16000, max_retries: int = 4):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=max_retries)
        self.model = model
        self.cache = DiskCache(cache_dir)
        self.max_tokens = max_tokens

    def call(self, stage: str, system: str, blocks: list[dict], tool: dict, use_cache: bool = True, label: str = "") -> CallResult:
        key = _fingerprint(self.model, system, blocks, tool)
        if use_cache:
            hit = self.cache.get(stage, key)
            if hit:
                return CallResult(data=hit["data"], usage=hit.get("usage", {}), cached=True, model=self.model)
        t0 = time.time()
        resp = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system,
            messages=[{"role": "user", "content": blocks}],
            tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
        )
        data = None
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use" and block.name == tool["name"]:
                data = block.input
                break
        if data is None:
            raise RuntimeError(f"{stage}: the model did not call the tool (stop_reason={resp.stop_reason})")
        usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        self.cache.put(stage, key, {"data": data, "usage": usage, "model": self.model, "label": label, "when": time.strftime("%Y-%m-%d %H:%M:%S")})
        return CallResult(data=data, usage=usage, cached=False, model=self.model, elapsed=time.time() - t0)


class MockProvider:
    """Replays <replay_dir>/<stage>.json or <replay_dir>/<stage>__<label>.json (label = sheet number)."""

    def __init__(self, replay_dir: str, model: str = "mock"):
        self.dir = replay_dir
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def call(self, stage: str, system: str, blocks: list[dict], tool: dict, use_cache: bool = True, label: str = "") -> CallResult:
        self.calls.append((stage, label))
        cands = [os.path.join(self.dir, f"{stage}__{label}.json"), os.path.join(self.dir, f"{stage}.json")] if label else [os.path.join(self.dir, f"{stage}.json")]
        for p in cands:
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as fh:
                    return CallResult(data=json.load(fh), usage={"input_tokens": 0, "output_tokens": 0}, cached=True, model=self.model)
        raise FileNotFoundError(f"mock response missing for stage '{stage}' label '{label}': looked for {cands}")
