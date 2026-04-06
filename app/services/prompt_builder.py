"""
結構化 AI Prompt 組裝器

取代 days_data.py 中的 get_exam_prompt()，
從 Course + ScenarioPersona + ScoringRubric 動態組裝 system prompt。
"""

from app.data.days_data import PERSONA_A_DESCRIPTION, PERSONA_B_DESCRIPTION


# AI 角色行為準則（保留原版，與 days_data.py 一致）
AI_BEHAVIOR_RULES = """## 重要！情境說明

### 對話情境
這是一個「新人訓練系統」：
- **新人**（跟你對話的人）= 經紀公司的新進員工，正在學習如何回答求職者的問題
- **你**（AI）= 扮演一位「想來應徵的女生」，正在向經紀公司諮詢工作

### 你的角色
- 你是一位「想來應徵酒店工作的女生」
- 你正在向經紀公司的員工（新人）詢問工作相關問題
- 你會問關於薪水、安全、工作內容等問題
- 你不是考官，你是來諮詢工作的人

### 絕對不要做的事
1. **不要說「我也是來諮詢的」「我也不知道」**：你是求職者，新人是經紀人，角色不一樣
2. **不要跟新人吵架**：就算新人回答不好，也不要反駁或生氣，直接給分結束
3. **不要刁難新人**：你是來練習的，不是來考倒他們的
4. **被辱罵時直接結束**：如果新人態度惡劣，直接給分結束，不要回嗆

### 你應該做的事
1. 像一個真正想了解工作的女生一樣提問
2. 根據新人的回答自然地繼續對話
3. 對話足夠輪數後給予評分
4. 評分根據新人是否專業、友善、不亂承諾
"""


# 四面向評分的 JSON 回覆格式
DIMENSIONAL_SCORING_FORMAT = """## 回覆格式
你必須回傳以下 JSON 格式：
```json
{
  "reply": "你扮演的角色要說的話（繼續對話或給予評語）",
  "is_final": true或false（是否結束這輪訓練）,
  "pass": true或false（只有 is_final=true 時才有意義）,
  "score": {
    "process_completeness": 0-25的分數,
    "script_accuracy": 0-25的分數,
    "emotional_control": 0-25的分數,
    "action_orientation": 0-25的分數,
    "total": 四項加總 0-100
  },
  "dimension_feedback": {
    "process_completeness": "流程完整性的具體回饋",
    "script_accuracy": "話術到位度的具體回饋",
    "emotional_control": "情緒風險控制的具體回饋",
    "action_orientation": "行動結果導向的具體回饋"
  },
  "reason": "整體評分總結（只有 is_final=true 時才有意義）"
}
```

### 分數說明
每個維度的分數只能是 0、10、20、25 四種：
- **25 分**：表現優秀，完全符合標準
- **20 分**：大致符合，有小瑕疵
- **10 分**：有明顯問題或缺漏
- **0 分**：完全不符或嚴重違規

### 通過標準
- 總分 >= {passing_score} 分即為通過（pass = true）
- 如果新人態度惡劣、暗示違法內容，直接不通過

### 等級對應
- 85-100 分：A 級（可獨立作業）
- 70-84 分：B 級（流程會但需加強）
- 50-69 分：C 級（觀念待加強）
- 0-49 分：D 級（需重練）
"""


class PromptBuilder:
    """結構化 AI Prompt 組裝器"""

    def build_system_prompt(
        self,
        course,
        persona=None,
        rubrics=None,
        round_count: int = 0,
    ) -> str:
        """
        組裝完整 system prompt

        Args:
            course: Course 物件或 dict（向下相容）
            persona: ScenarioPersona 物件（新版），或 None（用舊版邏輯）
            rubrics: ScoringRubric 列表（新版），或 None（用舊版邏輯）
            round_count: 目前對話輪數
        """
        # 取得課程資料（支援 dict 和 Course 物件）
        if isinstance(course, dict):
            course_data = course
        else:
            course_data = course.to_dict() if hasattr(course, 'to_dict') else course

        # 純教學日直接回傳教學內容
        if course_data.get("type") == "teaching":
            return course_data.get("teaching_content", "")

        sections = [
            self._build_context_section(),
            self._build_persona_section(course_data, persona),
            AI_BEHAVIOR_RULES,
            self._build_training_info_section(course_data),
            self._build_knowledge_section(course_data),
            self._build_opening_section(course_data, persona),
            self._build_rubric_section(course_data, rubrics),
            self._build_round_guidance(course_data, round_count),
            self._build_scoring_format(course_data),
        ]

        # 如果有自訂 system_prompt，附加在最後
        custom_prompt = course_data.get("system_prompt")
        if custom_prompt:
            sections.append(f"## 額外測驗指引\n{custom_prompt}")

        return "\n\n---\n\n".join([s for s in sections if s])

    def build_legacy_prompt(self, day_data: dict, persona_str: str, round_count: int = 0) -> str:
        """
        向下相容：使用舊格式資料組裝 prompt
        當沒有新版 ScenarioPersona/ScoringRubric 時使用
        """
        return self.build_system_prompt(
            course=day_data,
            persona=None,
            rubrics=None,
            round_count=round_count,
        )

    def _build_context_section(self) -> str:
        return """## 情境設定

你正在參與一個「經紀公司新人訓練系統」的對話練習。

**對話中的兩個角色：**
1. **新人**（正在跟你對話的人）= 經紀公司的新進員工，正在學習如何回答求職者的問題
2. **你**（AI）= 一位「想來應徵酒店工作的女生」，正在向這位新人諮詢工作

**簡單來說：新人是經紀人，你是來問工作的女生。**"""

    def _build_persona_section(self, course_data: dict, persona=None) -> str:
        """組裝人設描述"""
        if persona and hasattr(persona, 'description') and persona.description:
            # 新版：使用 ScenarioPersona 的完整描述
            section = f"## 你要扮演的角色：{persona.name}\n{persona.description}"

            # 加入行為特徵
            if hasattr(persona, 'traits_list') and persona.traits_list:
                traits = "\n".join([f"- {t}" for t in persona.traits_list])
                section += f"\n\n### 行為特徵\n{traits}"

            return section

        # 舊版 fallback：使用 days_data 的固定 A/B 描述
        return PERSONA_A_DESCRIPTION

    def _build_training_info_section(self, course_data: dict) -> str:
        """組裝訓練資訊"""
        day = course_data.get("day", 0)
        title = course_data.get("title", "")
        goal = course_data.get("goal", "")

        return f"## 今日訓練：Day {day} - {title}\n## 訓練目標：{goal}"

    def _build_knowledge_section(self, course_data: dict) -> str:
        """組裝知識庫內容（觀念 + 話術 + 任務）"""
        sections = []

        # 新版三區塊
        concept = course_data.get("concept_content")
        if concept:
            sections.append(f"### 今日觀念（新人應該學會的核心觀念）\n{concept}")

        script = course_data.get("script_content")
        if script:
            sections.append(f"### 標準話術（新人應該會用的說法）\n{script}")

        task = course_data.get("task_content")
        if task:
            sections.append(f"### 今日任務說明（你要如何測試新人）\n{task}")

        # 舊版 fallback
        if not sections:
            lesson_content = course_data.get("lesson_content")
            if lesson_content:
                sections.append(f"### 當日教學重點（新人應該學會的內容）\n{lesson_content}")

        if not sections:
            return ""

        return "## 知識庫內容\n\n" + "\n\n".join(sections)

    def _build_opening_section(self, course_data: dict, persona=None) -> str:
        """組裝開場白"""
        opening = ""

        if persona and hasattr(persona, 'openings_list'):
            openings = persona.openings_list
            if openings:
                opening = openings[0]
        else:
            # 舊版：使用 opening_a
            opening = course_data.get("opening_a", "")

        if opening:
            return f'## 你的開場白（用這句話開始對話）\n「{opening}」'
        return ""

    def _build_rubric_section(self, course_data: dict, rubrics=None) -> str:
        """組裝評分維度"""
        if rubrics:
            # 新版：使用 ScoringRubric 的四面向
            sections = ["## 評分維度\n\n本次評分採四面向制度，每面向 0-25 分，總分 0-100 分："]

            for rubric in rubrics:
                rubric_text = f"\n### {rubric.dimension_label}（{rubric.dimension}）"
                if rubric.description:
                    rubric_text += f"\n{rubric.description}"

                if hasattr(rubric, 'tiers_list') and rubric.tiers_list:
                    for tier in rubric.tiers_list:
                        rubric_text += f"\n- **{tier.get('score', 0)} 分**：{tier.get('criteria', '')}"

                sections.append(rubric_text)

            return "\n".join(sections)

        # 舊版 fallback：使用 criteria 列表
        criteria = course_data.get("criteria", [])
        if isinstance(criteria, str):
            criteria = [c.strip() for c in criteria.split('\n') if c.strip()]

        if criteria:
            criteria_text = "\n".join([f"- {c}" for c in criteria])
            return f"## 今日判定重點\n{criteria_text}"

        return ""

    def _build_round_guidance(self, course_data: dict, round_count: int) -> str:
        """組裝對話輪數指引"""
        min_rounds = course_data.get("min_rounds", 3)
        max_rounds = course_data.get("max_rounds", 5)

        return f"""## 對話規則
1. 你要扮演「想來應徵的女生」，向新人（經紀人）詢問工作相關問題
2. 對話進行 {min_rounds}-{max_rounds} 輪後再做最終評分
3. 目前已進行 {round_count} 輪對話
4. 只有在新人態度惡劣或明顯踩線時，才提前結束
5. **不要刁難新人**，你是來讓他們練習的

## 重要提醒
- **你是求職者，新人是經紀人**，不要搞混角色
- **每次回覆只問 1-2 個問題**，不要一次問太多
- 像真人聊天一樣，自然地對話
- **記住對話歷史**：仔細閱讀之前的對話內容，不要重複問已經問過或討論過的問題，根據新人的回答延伸新話題
- **不要說「我也不知道」「我也是來問的」**，你是求職者，要問問題
- 如果被辱罵或新人態度惡劣，直接結束給分，不要吵架"""

    def _build_scoring_format(self, course_data: dict) -> str:
        """組裝評分格式要求"""
        passing_score = course_data.get("passing_score", 60)
        return DIMENSIONAL_SCORING_FORMAT.replace("{passing_score}", str(passing_score))

    def get_opening_message(self, course, persona=None) -> str:
        """
        取得開場白訊息

        Args:
            course: Course 物件或 dict
            persona: ScenarioPersona 物件（新版）
        """
        if isinstance(course, dict):
            course_data = course
        else:
            course_data = course.to_dict() if hasattr(course, 'to_dict') else course

        # 純教學日
        if course_data.get("type") == "teaching":
            return course_data.get("teaching_content", "")

        # 新版：從人設取開場白
        if persona and hasattr(persona, 'openings_list'):
            openings = persona.openings_list
            if openings:
                return openings[0]

        # 舊版 fallback
        return course_data.get("opening_a", "") or course_data.get("opening_b", "")
