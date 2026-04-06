import json
import random
import re
import time
from anthropic import Anthropic, APIStatusError
from app.config import get_settings
from app.schemas.ai_response import AIResponse
from app.data.days_data import get_exam_prompt, get_day_data
from app.services.prompt_builder import PromptBuilder


class AIService:
    """AI 服務（Claude 串接與評分）"""

    # 重試設定
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # 秒

    def __init__(self):
        settings = get_settings()
        self.client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
        self.prompt_builder = PromptBuilder()

    def _call_api_with_retry(self, **kwargs) -> any:
        """
        帶重試機制的 API 調用

        處理 529 (Overloaded) 和其他暫時性錯誤
        """
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return self.client.messages.create(**kwargs)
            except APIStatusError as e:
                last_error = e
                # 529 = Overloaded, 503 = Service Unavailable
                if e.status_code in (529, 503):
                    if attempt < self.MAX_RETRIES - 1:
                        wait_time = self.RETRY_DELAY * (attempt + 1)
                        print(f"⚠️ API 過載 (嘗試 {attempt + 1}/{self.MAX_RETRIES})，{wait_time}秒後重試...")
                        time.sleep(wait_time)
                        continue
                raise
        raise last_error

    def generate_response(
        self,
        day: int,
        persona: str,
        user_message: str,
        round_count: int = 0,
        conversation_history: list[dict] | None = None,
        course=None,
        scenario_persona=None,
        rubrics=None,
    ) -> AIResponse:
        """
        產生 AI 回覆（多輪對話）

        Args:
            day: 訓練天數
            persona: "A" 或 "B"（舊版）
            user_message: 用戶輸入的訊息
            round_count: 目前對話輪數
            conversation_history: 對話歷史
            course: Course 物件（新版，優先使用）
            scenario_persona: ScenarioPersona 物件（新版）
            rubrics: ScoringRubric 列表（新版）

        Returns:
            AIResponse: 包含 reply, is_final, pass_, score, reason, dimensional_score
        """
        # 取得課程資料
        if course:
            course_data = course.to_dict() if hasattr(course, 'to_dict') else course
        else:
            course_data = get_day_data(day)

        if not course_data:
            return AIResponse(
                reply="課程資料不存在",
                is_final=True,
                pass_=False,
                score=0,
                reason="無效的訓練天數"
            )

        # Day 0 是純教學，不需要對話
        if course_data.get("type") == "teaching":
            return AIResponse(
                reply=course_data.get("teaching_content", ""),
                is_final=True,
                pass_=True,
                score=100,
                reason="教學內容已完成"
            )

        # 組裝 system prompt
        if scenario_persona or rubrics or course_data.get("concept_content"):
            # 新版：使用 PromptBuilder
            system_prompt = self.prompt_builder.build_system_prompt(
                course=course_data,
                persona=scenario_persona,
                rubrics=rubrics,
                round_count=round_count,
            )
        else:
            # 舊版 fallback：使用 get_exam_prompt
            system_prompt = get_exam_prompt(course_data, persona, round_count)

        # 建立訊息列表
        messages = []

        # 加入對話歷史
        if conversation_history:
            messages.extend(conversation_history)

        # 加入用戶訊息
        messages.append({"role": "user", "content": user_message})

        # 呼叫 Claude（帶重試機制）
        response = self._call_api_with_retry(
            model=self.model,
            max_tokens=1500,
            system=system_prompt,
            messages=messages,
        )

        # 解析回應
        content = response.content[0].text
        return self._parse_response(content)

    def generate_opening_message(
        self,
        day: int,
        persona: str,
        course=None,
        scenario_persona=None,
    ) -> str:
        """
        取得當日訓練的開場白

        Args:
            day: 訓練天數
            persona: "A" 或 "B"（舊版）
            course: Course 物件（新版）
            scenario_persona: ScenarioPersona 物件（新版）

        Returns:
            開場白訊息
        """
        # 新版：使用 PromptBuilder
        if course or scenario_persona:
            course_data = course if isinstance(course, dict) else (course.to_dict() if course else get_day_data(day))
            return self.prompt_builder.get_opening_message(course_data, scenario_persona)

        # 舊版 fallback
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
            return day_data.get("opening_a", "準備開始今天的訓練！")

    def select_persona(self, db, course_id: int):
        """
        根據課程的人設指派，隨機選取一個模擬人設

        Args:
            db: 資料庫 session
            course_id: 課程 ID

        Returns:
            ScenarioPersona 物件，或 None
        """
        from app.models.course_scenario import CourseScenario
        from app.models.scenario_persona import ScenarioPersona

        assignments = (
            db.query(CourseScenario)
            .join(ScenarioPersona)
            .filter(
                CourseScenario.course_id == course_id,
                ScenarioPersona.is_active == True,
            )
            .all()
        )

        if not assignments:
            return None

        # 根據權重隨機選取
        weights = [a.weight for a in assignments]
        selected = random.choices(assignments, weights=weights, k=1)[0]

        persona = db.query(ScenarioPersona).filter(ScenarioPersona.id == selected.persona_id).first()

        # 如果有開場白覆蓋，動態設定
        if selected.opening_override and persona:
            # 暫存覆蓋的開場白（不寫入 DB）
            persona._opening_override = selected.opening_override

        return persona

    def _parse_response(self, content: str) -> AIResponse:
        """
        解析 AI 回應，提取 JSON 格式

        支援新版（nested score object）和舊版（int score）格式
        """
        # 嘗試找到 JSON 區塊
        json_match = re.search(r'\{[\s\S]*?"reply"[\s\S]*?\}(?:\s*\})*', content)

        if json_match:
            try:
                json_str = json_match.group()
                # 處理可能被截斷的 JSON：嘗試修復括號
                data = json.loads(json_str)
                return AIResponse.from_dict(data)
            except json.JSONDecodeError:
                # 嘗試更寬鬆的匹配
                pass

        # 嘗試找到最外層的 JSON 物件（處理 nested score）
        brace_count = 0
        start_idx = None
        for i, char in enumerate(content):
            if char == '{':
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx is not None:
                    try:
                        json_str = content[start_idx:i + 1]
                        data = json.loads(json_str)
                        if "reply" in data:
                            return AIResponse.from_dict(data)
                    except json.JSONDecodeError:
                        start_idx = None
                        continue

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
            response = self._call_api_with_retry(
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
