import json
import re
from anthropic import Anthropic
from app.config import get_settings
from app.schemas.ai_response import AIResponse
from app.data.days_data import get_exam_prompt, get_day_data


class AIService:
    """AI 服務（Claude 串接與評分）"""

    def __init__(self):
        settings = get_settings()
        self.client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model

    def generate_response(
        self,
        day: int,
        persona: str,
        user_message: str,
        round_count: int = 0,
        conversation_history: list[dict] | None = None,
    ) -> AIResponse:
        """
        產生 AI 回覆（多輪對話）

        Args:
            day: 訓練天數
            persona: "A" 或 "B"
            user_message: 用戶輸入的訊息
            round_count: 目前對話輪數
            conversation_history: 對話歷史

        Returns:
            AIResponse: 包含 reply, is_final, pass_, score, reason
        """
        day_data = get_day_data(day)
        if not day_data:
            return AIResponse(
                reply="課程資料不存在",
                is_final=True,
                pass_=False,
                score=0,
                reason="無效的訓練天數"
            )

        # Day 0 是純教學，不需要對話
        if day_data.get("type") == "teaching":
            return AIResponse(
                reply=day_data.get("teaching_content", ""),
                is_final=True,
                pass_=True,
                score=100,
                reason="教學內容已完成"
            )

        # 產生考核用的 Prompt
        system_prompt = get_exam_prompt(day_data, persona, round_count)

        # 建立訊息列表
        messages = []

        # 加入對話歷史
        if conversation_history:
            messages.extend(conversation_history)

        # 加入用戶訊息
        messages.append({"role": "user", "content": user_message})

        # 呼叫 Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            system=system_prompt,
            messages=messages,
        )

        # 解析回應
        content = response.content[0].text
        return self._parse_response(content)

    def generate_opening_message(self, day: int, persona: str) -> str:
        """
        取得當日訓練的固定開場白

        Args:
            day: 訓練天數
            persona: "A" 或 "B"

        Returns:
            開場白訊息
        """
        day_data = get_day_data(day)
        if not day_data:
            return "你好，準備開始今天的訓練了嗎？"

        # Day 0 是純教學
        if day_data.get("type") == "teaching":
            return day_data.get("teaching_content", "")

        # 取得對應 Persona 的開場白
        opening_key = f"opening_{persona.lower()}"
        opening = day_data.get(opening_key, "")

        if opening:
            return opening
        else:
            # 如果沒有對應的開場白，使用 A 版本
            return day_data.get("opening_a", "準備開始今天的訓練！")

    def _parse_response(self, content: str) -> AIResponse:
        """
        解析 AI 回應，提取 JSON 格式

        AI 回應格式應該包含：
        {
            "reply": "回覆內容",
            "is_final": true/false,
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

        # 嘗試解析整個回應
        try:
            data = json.loads(content)
            return AIResponse.from_dict(data)
        except json.JSONDecodeError:
            pass

        # 如果都失敗，返回預設值（將整個回應作為 reply，繼續對話）
        return AIResponse(
            reply=content,
            is_final=False,
            pass_=False,
            score=0,
            reason=""
        )

    def classify_persona(self, first_message: str) -> str:
        """
        根據第一則訊息分類用戶 Persona

        Args:
            first_message: 用戶的第一則訊息

        Returns:
            "A" 或 "B"
        """
        system_prompt = """你是一個用戶分類專家。根據新人的訊息，判斷她是：

A. 無經驗新人（特徵：擔心安全、害怕、問基本問題、對行業不了解、語氣緊張）
B. 有經驗新人（特徵：問待遇、抽成、比較其他店、使用行業術語、語氣直接）

請只回覆 "A" 或 "B"，不要有其他內容。
如果無法判斷，預設回覆 "A"。"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=10,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": f"新人的訊息：{first_message}"}
                ],
            )

            result = response.content[0].text.strip().upper()
            return "B" if "B" in result else "A"
        except Exception:
            return "A"  # 預設無經驗
