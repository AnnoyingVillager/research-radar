from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import Settings

SYSTEM_PROMPT = """你是气动声学、计算声学和流体力学方向的研究助理。
只根据用户提供的论文标题、期刊和摘要进行总结，不得补充摘要中没有的事实。
输出严格 JSON，不要输出 Markdown。字段如下：
{
  "title_zh": "准确的中文标题",
  "problem": "研究要解决的问题，1-2句",
  "method": "使用的方法，1-2句",
  "key_results": ["关键结果1", "关键结果2"],
  "limitations": "摘要明确体现或可以合理判断的局限；无法判断时写‘摘要未说明’",
  "relevance": "与气动声学/流体/计算方法的联系",
  "read_reason": "建议阅读的一句话理由",
  "novelty_score": 0.0
}
novelty_score 取 0 到 1。不要因为论文暂时没有引用就给出低分。"""


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.llm_enabled
            and self.settings.llm_base_url
            and self.settings.llm_model
        )

    async def summarize(self, paper: dict[str, Any]) -> dict[str, Any] | None:
        abstract = (paper.get("abstract") or "").strip()
        if not self.configured or len(abstract) < 120:
            return None

        user_prompt = (
            f"期刊：{paper.get('venue_name', '')}\n"
            f"英文标题：{paper.get('title', '')}\n"
            f"摘要：{abstract[:9000]}"
        )
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        endpoint = self.settings.llm_base_url.rstrip("/") + "/chat/completions"

        async with httpx.AsyncClient(timeout=120, trust_env=True) as client:
            try:
                response = await client.post(endpoint, headers=headers, json=payload)
                if response.status_code == 400:
                    payload.pop("response_format", None)
                    response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return parse_json_object(content)
            except Exception:
                return None


def parse_json_object(content: str) -> dict[str, Any] | None:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None

    results = data.get("key_results", [])
    if isinstance(results, list):
        data["key_results"] = "；".join(str(item).strip() for item in results if item)
    else:
        data["key_results"] = str(results)
    try:
        data["novelty_score"] = max(0.0, min(1.0, float(data.get("novelty_score", 0.5))))
    except (TypeError, ValueError):
        data["novelty_score"] = 0.5
    return data

