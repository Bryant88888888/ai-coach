import json
import re
from openai import OpenAI
from app.config import get_settings
from app.schemas.ai_response import AIResponse
from app.models.user import Persona


class AIService:
    """AI 服務（GPT 串接與評分）"""

    def __init__(self):
        settings = get_settings()
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

    def generate_response(
        self,
        prompt: str,
        user_message: str,
        persona: Persona | None = None,
        conversation_history: list[dict] | None = None,
    ) -> AIResponse:
        """
        呼叫 GPT 產生回覆

        Args:
            prompt: 當天的訓練 prompt
            user_message: 用戶輸入的訊息
            persona: 用戶的 Persona（A/B）
            conversation_history: 對話歷史（選配）

        Returns:
            AIResponse: 包含 reply, pass_, score, reason
        """
        # 建立系統提示
        system_prompt = self._build_system_prompt(prompt, persona)

        # 建立訊息列表
        messages = [{"role": "system", "content": system_prompt}]

        # 加入對話歷史（如果有）
        if conversation_history:
            messages.extend(conversation_history)

        # 加入用戶訊息
        messages.append({"role": "user", "content": user_message})

        # 呼叫 GPT
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=1000,
        )

        # 解析回應
        content = response.choices[0].message.content
        return self._parse_response(content)

    def _build_system_prompt(self, prompt: str, persona: Persona | None) -> str:
        """建立系統提示"""
        persona_instruction = ""
        if persona == Persona.A_NO_EXPERIENCE:
            persona_instruction = "\n\n## 用戶類型：無經驗新人\n請用更溫柔、耐心的方式教學，多給予鼓勵。"
        elif persona == Persona.B_HAS_EXPERIENCE:
            persona_instruction = "\n\n## 用戶類型：有經驗新人\n請用專業、直接的方式溝通，可以使用行業術語。"

        return prompt + persona_instruction

    def _parse_response(self, content: str) -> AIResponse:
        """
        解析 AI 回應，提取 JSON 格式的評分資訊

        AI 回應格式應該包含：
        {
            "reply": "回覆內容",
            "pass": true/false,
            "score": 0-100,
            "reason": "評分原因"
        }
        """
        # 嘗試找到 JSON 區塊
        json_match = re.search(r'\{[\s\S]*?"reply"[\s\S]*?\}', content)

        if json_match:
            try:
                json_str = json_match.group()
                data = json.loads(json_str)
                return AIResponse.from_dict(data)
            except json.JSONDecodeError:
                pass

        # 如果找不到有效的 JSON，嘗試解析整個回應
        try:
            data = json.loads(content)
            return AIResponse.from_dict(data)
        except json.JSONDecodeError:
            pass

        # 如果都失敗，返回預設值（將整個回應作為 reply）
        return AIResponse(
            reply=content,
            pass_=False,
            score=0,
            reason="無法解析 AI 回應格式，請重試"
        )

    def classify_persona_by_ai(self, first_message: str) -> Persona:
        """
        使用 AI 分類用戶 Persona（更精準的分類方式）
        """
        prompt = """你是一個用戶分類專家。根據新人的第一句話，判斷他是：

A. 無經驗新人（特徵：擔心安全、害怕、問基本問題、對行業不了解）
B. 有經驗新人（特徵：問待遇、抽成、比較其他店、使用行業術語）

請只回覆 "A" 或 "B"，不要有其他內容。

新人的訊息："""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": first_message}
            ],
            temperature=0.3,
            max_tokens=10,
        )

        result = response.choices[0].message.content.strip().upper()

        if "B" in result:
            return Persona.B_HAS_EXPERIENCE
        return Persona.A_NO_EXPERIENCE
