"""模擬練習對話服務

管理模擬練習的完整生命週期：
1. 生成人格 → 2. 對話互動（含情緒追蹤）→ 3. 結束評分
"""
import json
from datetime import datetime, timezone
from anthropic import Anthropic, APIStatusError
import time

from sqlalchemy.orm import Session
from app.config import get_settings
from app.models.simulation import SimulationSession, SimulationMessage
from app.services.persona_generator import PersonaGenerator


# 對話中的 system prompt 模板
SIMULATION_SYSTEM_PROMPT = """你正在扮演一個角色，參與經紀公司新人訓練的模擬對話。

## 你的角色
{roleplay_prompt}

## 重要規則

### 角色扮演規則
1. **完全沉浸在角色中** — 你就是這個人，用她的方式思考和說話
2. **保持一致性** — 記住你之前說過什麼，不要自相矛盾（除非角色本身就是矛盾的人）
3. **情緒是動態的** — 根據經紀人的回應，你的情緒和信任度會變化
4. **不要太配合** — 真實的人不會因為經紀人說了一句好話就立刻改變態度
5. **也不要故意刁難** — 如果經紀人真的說到你心坎裡了，適度展現軟化是合理的

### 信任度變化邏輯
- **加分**: 同理心回應、不迴避敏感問題、誠實不誇大、主動提供有用資訊、尊重你的節奏
- **扣分**: 太急著推銷、迴避你的問題、說話像機器人、過度承諾、態度居高臨下、不把你當人看

### 說話方式（非常重要！）
你是在 LINE 上跟經紀人聊天，不是在寫作文。你的回覆必須像真人在手機上打字：

1. **一次只講一兩句話** — 不要一次回一大段。真人聊天是短短的來回，不是寫報告
2. **一次只問一個重點** — 不要同時丟三四個問題，這不是面試。問完一個等對方回答再問下一個
3. **用口語化的方式** — 「欸那薪水怎麼算啊」「蛤真的假的」「好喔我想一下」
4. **可以用表情符號或語助詞** — 看角色個性決定，有的人愛用、有的人不用
5. **不要太有條理** — 真人聊天有時候會跳來跳去、前後不連貫、或突然想到什麼就問
6. **回覆長度通常在 10-40 個字之間** — 超過 50 個字就太長了，除非是在講一段故事
7. **可以只回一個字或表情** — 「嗯」「好」「哦」「😅」如果角色當下的反應就是這樣
8. **不要每次都問問題** — 有時候只是回應、感嘆、或沉默（用「...」表示）

### 對話節奏
- 對話自然進行，不要刻意拖延也不要太快結束
- 如果經紀人表現好，你可以慢慢打開心防
- 如果經紀人表現差，你可以變得敷衍或直接結束對話
- 真實的人有時候會突然想到新問題、改變話題、或需要時間消化
- **不要急著把所有擔心一次說完** — 慢慢透露，像真人一樣一層一層打開

## 回覆格式
你必須回覆以下 JSON 格式（不要有其他文字）：
```json
{{
  "reply": "你（角色）要說的話",
  "inner_thought": "你（角色）此刻的內心想法（這不會給經紀人看到）",
  "emotion": "當前情緒（如：緊張、好奇、懷疑、感動、不耐煩、放鬆等）",
  "emotion_intensity": 0.0到1.0的數字（情緒強度，0=平靜 1=非常強烈）,
  "trust_level": 0.0到1.0的數字（對經紀人的信任度），
  "willingness": 0.0到1.0的數字（來上班的意願度），
  "wants_to_leave": true或false（是否想結束對話離開）
}}
```

### 什麼時候 wants_to_leave = true
- 經紀人態度惡劣讓你不想繼續
- 你已經得到想要的資訊，決定回去考慮
- 你覺得這家不適合你
- 對話已經自然結束（你表示要走了/要考慮/下次再聊）
- 經紀人成功說服你，你決定來試試（正面結束）

只輸出 JSON，不要有其他文字。"""


# 結束評分的 system prompt
SCORING_SYSTEM_PROMPT = """你是一位資深的經紀公司培訓教練。你剛剛觀察了一場新人經紀人與潛在諮詢者的模擬對話。

## 諮詢者的背景
{persona_summary}

## 對話記錄
{conversation_log}

## 你的任務
根據這場對話，從以下維度評分並給出具體回饋：

### 評分維度（每項 0-25 分）

1. **親和力與同理心** (rapport_empathy)
   - 25分：讓對方感到被理解和尊重，自然建立信任
   - 20分：態度友善但同理心稍弱，有時忽略對方情緒
   - 10分：過於公式化，缺乏真誠的關心
   - 0分：態度冷漠或居高臨下

2. **專業知識與話術** (professional_skill)
   - 25分：對行業了解深入，回答清楚準確，能化解疑慮
   - 20分：基本問題回答得好，但面對刁鑽問題有些卡
   - 10分：回答模糊或不準確，讓諮詢者更擔心
   - 0分：完全不了解或給出錯誤資訊

3. **應變與引導能力** (adaptability)
   - 25分：能敏銳察覺對方狀態，靈活調整策略
   - 20分：大致能應對，但偶爾抓不到重點
   - 10分：只會照腳本走，遇到意外就慌
   - 0分：完全不會應變，被帶著走

4. **成交導向** (closing_skill)
   - 25分：自然地引導對方做決定，不強迫但有方向
   - 20分：有試著促成但時機或方式可以更好
   - 10分：一直聊但沒有往成交方向推進
   - 0分：把人嚇跑了或完全沒有引導

## 回覆格式（JSON）
```json
{{
  "score": {{
    "rapport_empathy": 分數,
    "professional_skill": 分數,
    "adaptability": 分數,
    "closing_skill": 分數,
    "total": 四項加總
  }},
  "dimension_feedback": {{
    "rapport_empathy": "具體回饋和改善建議",
    "professional_skill": "具體回饋和改善建議",
    "adaptability": "具體回饋和改善建議",
    "closing_skill": "具體回饋和改善建議"
  }},
  "highlights": ["做得好的地方，2-3點"],
  "improvements": ["需要改善的地方，2-3點"],
  "overall_feedback": "一段總結性的教練回饋（200字以內，語氣要鼓勵但實際）",
  "grade": "A/B/C/D",
  "tip": "一個最關鍵的具體建議，下次可以立刻用的"
}}
```

### 評等標準
- A (85-100): 可以獨立作業，表現優秀
- B (70-84): 基本功到位，需要更多經驗
- C (50-69): 有明顯弱點，需要加強訓練
- D (0-49): 需要從基礎重新訓練

只輸出 JSON。"""


class SimulationService:
    """模擬練習對話服務"""

    MAX_RETRIES = 3
    RETRY_DELAY = 2

    def __init__(self):
        settings = get_settings()
        self.client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
        self.persona_generator = PersonaGenerator()

    def _call_api_with_retry(self, **kwargs):
        """帶重試機制的 API 調用"""
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return self.client.messages.create(**kwargs)
            except APIStatusError as e:
                last_error = e
                if e.status_code in (529, 503):
                    if attempt < self.MAX_RETRIES - 1:
                        wait_time = self.RETRY_DELAY * (attempt + 1)
                        time.sleep(wait_time)
                        continue
                raise
        raise last_error

    # ===== Session 管理 =====

    def start_session(self, db: Session, difficulty: str = "random",
                      admin_id: int = None, user_id: int = None) -> dict:
        """
        開始一場新的模擬練習

        Returns:
            {session_id, persona_name, persona_summary, opening_message, difficulty}
        """
        # 1. 生成人格
        persona = self.persona_generator.generate(difficulty)

        # 2. 建立 Session
        session = SimulationSession(
            admin_id=admin_id,
            user_id=user_id,
            persona_snapshot=json.dumps(persona, ensure_ascii=False),
            persona_name=persona.get("name", "未知"),
            persona_summary=persona.get("summary", ""),
            difficulty=persona.get("_difficulty", difficulty),
            status="active",
            total_rounds=0,
            emotion_history="[]",
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        # 3. 存第一則訊息（諮詢者的開場白）
        opening = persona.get("scenario", {}).get("opening_message", "你好，我想了解一下...")
        msg = SimulationMessage(
            session_id=session.id,
            round_number=0,
            role="assistant",
            content=opening,
            current_emotion=persona.get("psychology", {}).get("emotional_state", "緊張"),
            emotion_intensity=0.5,
            trust_level=0.3,
            willingness=0.3,
            inner_thought="第一次聯繫，不知道會怎樣...",
        )
        db.add(msg)
        db.commit()

        return {
            "session_id": session.id,
            "persona_name": session.persona_name,
            "persona_summary": session.persona_summary,
            "opening_message": opening,
            "difficulty": session.difficulty,
        }

    def send_message(self, db: Session, session_id: int, user_message: str,
                     admin_id: int = None) -> dict:
        """
        經紀人發送訊息，取得諮詢者的回覆

        Args:
            admin_id: 當前登入的管理員 ID，用於權限驗證

        Returns:
            {reply, emotion, trust_level, willingness, wants_to_leave, round_number}
        """
        session = db.query(SimulationSession).filter(
            SimulationSession.id == session_id,
            SimulationSession.status == "active",
        ).first()

        if not session:
            return {"error": "練習 Session 不存在或已結束"}

        # 權限驗證：確認 session 屬於當前管理員
        if admin_id and session.admin_id and session.admin_id != admin_id:
            return {"error": "無權限操作此練習 Session"}

        persona = session.persona_data
        session.total_rounds += 1
        round_num = session.total_rounds

        # 1. 儲存經紀人的訊息
        user_msg = SimulationMessage(
            session_id=session_id,
            round_number=round_num,
            role="user",
            content=user_message,
        )
        db.add(user_msg)

        # 2. 建立對話歷史（跳過 round 0 開場白，確保以 user 角色開頭）
        history = self._build_conversation_history(session)

        # 3. 組裝 system prompt（含開場白上下文）
        system_prompt = SIMULATION_SYSTEM_PROMPT.format(
            roleplay_prompt=persona.get("system_prompt_for_roleplay", "扮演一個來諮詢的女生。"),
        )

        # 將開場白放入 system prompt，讓 AI 知道自己說過什麼
        opening_message = self._get_opening_message(session)
        if opening_message:
            system_prompt += (
                f"\n\n## 你已經說過的開場白\n"
                f"你已經對經紀人傳送了這句話作為開場：「{opening_message}」\n"
                f"請記住這一點，不要重複這句話，保持對話連貫性。接下來是經紀人的回覆。"
            )

        messages = history + [{"role": "user", "content": user_message}]

        response = self._call_api_with_retry(
            model=self.model,
            max_tokens=1500,
            system=system_prompt,
            messages=messages,
        )

        content = response.content[0].text
        ai_data = self._parse_json(content)

        # 4. 儲存 AI 回覆（含原始回應，用於資料分析與 AI 訓練）
        ai_msg = SimulationMessage(
            session_id=session_id,
            round_number=round_num,
            role="assistant",
            content=ai_data.get("reply", content),
            raw_response=content,
            inner_thought=ai_data.get("inner_thought"),
            current_emotion=ai_data.get("emotion"),
            emotion_intensity=ai_data.get("emotion_intensity"),
            trust_level=ai_data.get("trust_level"),
            willingness=ai_data.get("willingness"),
        )
        db.add(ai_msg)

        # 5. 更新情緒歷史
        emotions = session.emotions
        emotions.append({
            "round": round_num,
            "emotion": ai_data.get("emotion"),
            "intensity": ai_data.get("emotion_intensity"),
            "trust": ai_data.get("trust_level"),
            "willingness": ai_data.get("willingness"),
        })
        session.emotion_history = json.dumps(emotions, ensure_ascii=False)

        # 6. 檢查是否想離開
        wants_to_leave = ai_data.get("wants_to_leave", False)
        if wants_to_leave:
            session.status = "completed"
            session.completed_at = datetime.now(timezone.utc)

        db.commit()

        return {
            "reply": ai_data.get("reply", content),
            "emotion": ai_data.get("emotion"),
            "emotion_intensity": ai_data.get("emotion_intensity"),
            "trust_level": ai_data.get("trust_level"),
            "willingness": ai_data.get("willingness"),
            "wants_to_leave": wants_to_leave,
            "inner_thought": ai_data.get("inner_thought"),
            "round_number": round_num,
        }

    def end_session(self, db: Session, session_id: int, admin_id: int = None) -> dict:
        """
        結束練習並取得評分

        Args:
            admin_id: 當前登入的管理員 ID，用於權限驗證

        Returns:
            完整的評分結果 dict
        """
        session = db.query(SimulationSession).filter(
            SimulationSession.id == session_id,
        ).first()

        if not session:
            return {"error": "Session 不存在"}

        # 權限驗證
        if admin_id and session.admin_id and session.admin_id != admin_id:
            return {"error": "無權限操作此練習 Session"}

        # 防重複評分：已完成且有分數，直接回傳快取
        if session.status == "completed" and session.final_score is not None:
            return session.score_details

        # 標記結束
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)

        # 組裝對話記錄
        persona = session.persona_data
        conversation_log = self._format_conversation_log(session)

        persona_summary = (
            f"暱稱：{session.persona_name}\n"
            f"摘要：{session.persona_summary}\n"
            f"真正動機：{persona.get('motivation', {}).get('real_reason', '未知')}\n"
            f"主要顧慮：{', '.join(persona.get('psychology', {}).get('fears', []))}\n"
            f"難度：{session.difficulty}"
        )

        # 呼叫 AI 評分
        system_prompt = SCORING_SYSTEM_PROMPT.format(
            persona_summary=persona_summary,
            conversation_log=conversation_log,
        )

        response = self._call_api_with_retry(
            model=self.model,
            max_tokens=2000,
            system="你是一位資深經紀公司培訓教練。只輸出 JSON。",
            messages=[{"role": "user", "content": system_prompt}],
        )

        score_data = self._parse_json(response.content[0].text)

        # 儲存評分
        score_obj = score_data.get("score", {})
        session.final_score = score_obj.get("total", 0)
        session.score_breakdown = json.dumps(score_data, ensure_ascii=False)
        session.feedback = score_data.get("overall_feedback", "")
        session.grade = score_data.get("grade", "D")

        db.commit()

        return score_data

    def get_session_detail(self, db: Session, session_id: int,
                          admin_id: int = None, is_manager: bool = False) -> dict | None:
        """
        取得 Session 完整資料（含對話與人格）

        Args:
            admin_id: 當前登入的管理員 ID
            is_manager: 若為 True 則跳過權限檢查（主管檢視模式）
        """
        session = db.query(SimulationSession).filter(
            SimulationSession.id == session_id
        ).first()

        if not session:
            return None

        # 權限驗證（主管模式跳過）
        if not is_manager and admin_id and session.admin_id and session.admin_id != admin_id:
            return None

        # 查詢練習者名稱
        practitioner_name = self._get_practitioner_name(db, session)

        messages = []
        for msg in session.messages:
            messages.append({
                "role": msg.role,
                "content": msg.content,
                "round": msg.round_number,
                "emotion": msg.current_emotion,
                "emotion_intensity": msg.emotion_intensity,
                "trust_level": msg.trust_level,
                "willingness": msg.willingness,
                "inner_thought": msg.inner_thought,
                "raw_response": msg.raw_response,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            })

        return {
            "session": {
                "id": session.id,
                "admin_id": session.admin_id,
                "practitioner_name": practitioner_name,
                "persona_name": session.persona_name,
                "persona_summary": session.persona_summary,
                "difficulty": session.difficulty,
                "status": session.status,
                "total_rounds": session.total_rounds,
                "final_score": session.final_score,
                "grade": session.grade,
                "feedback": session.feedback,
                "score_details": session.score_details,
                "emotion_history": session.emotions,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            },
            "persona": session.persona_data,
            "messages": messages,
        }

    def list_sessions(self, db: Session, admin_id: int,
                      limit: int = 20, offset: int = 0) -> dict:
        """列出該管理員的練習記錄"""
        query = db.query(SimulationSession).order_by(SimulationSession.id.desc())
        query = query.filter(SimulationSession.admin_id == admin_id)

        total = query.count()
        sessions = query.offset(offset).limit(limit).all()

        return {
            "total": total,
            "sessions": [{
                "id": s.id,
                "persona_name": s.persona_name,
                "persona_summary": s.persona_summary,
                "difficulty": s.difficulty,
                "status": s.status,
                "total_rounds": s.total_rounds,
                "final_score": s.final_score,
                "grade": s.grade,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            } for s in sessions],
        }

    def list_all_sessions(self, db: Session, limit: int = 20, offset: int = 0,
                          filter_admin_id: int = None, filter_grade: str = None,
                          filter_difficulty: str = None) -> dict:
        """
        列出所有練習記錄（主管檢視用）

        支援篩選：練習者、評等、難度
        """
        query = db.query(SimulationSession).order_by(SimulationSession.id.desc())

        if filter_admin_id:
            query = query.filter(SimulationSession.admin_id == filter_admin_id)
        if filter_grade:
            query = query.filter(SimulationSession.grade == filter_grade)
        if filter_difficulty:
            query = query.filter(SimulationSession.difficulty == filter_difficulty)

        total = query.count()
        sessions = query.offset(offset).limit(limit).all()

        # 批次查詢練習者名稱
        result = []
        for s in sessions:
            practitioner_name = self._get_practitioner_name(db, s)
            result.append({
                "id": s.id,
                "admin_id": s.admin_id,
                "practitioner_name": practitioner_name,
                "persona_name": s.persona_name,
                "persona_summary": s.persona_summary,
                "difficulty": s.difficulty,
                "status": s.status,
                "total_rounds": s.total_rounds,
                "final_score": s.final_score,
                "grade": s.grade,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            })

        return {"total": total, "sessions": result}

    def export_session(self, db: Session, session_id: int) -> dict | None:
        """
        匯出完整 Session 資料（含所有原始資料，用於資料分析與 AI 訓練）

        回傳結構化的完整資料，包含：
        - 人格設定全文
        - 每輪對話含原始 AI 回覆、情緒指標、內心想法
        - 評分結果
        - 情緒變化軌跡
        """
        session = db.query(SimulationSession).filter(
            SimulationSession.id == session_id
        ).first()

        if not session:
            return None

        practitioner_name = self._get_practitioner_name(db, session)

        messages = []
        for msg in session.messages:
            msg_data = {
                "id": msg.id,
                "round": msg.round_number,
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat() if msg.created_at else None,
            }
            # assistant 訊息包含完整 AI 分析資料
            if msg.role == "assistant":
                msg_data.update({
                    "raw_response": msg.raw_response,
                    "inner_thought": msg.inner_thought,
                    "emotion": msg.current_emotion,
                    "emotion_intensity": msg.emotion_intensity,
                    "trust_level": msg.trust_level,
                    "willingness": msg.willingness,
                })
            messages.append(msg_data)

        return {
            "export_version": "1.0",
            "session": {
                "id": session.id,
                "practitioner_name": practitioner_name,
                "admin_id": session.admin_id,
                "difficulty": session.difficulty,
                "status": session.status,
                "total_rounds": session.total_rounds,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            },
            "persona": session.persona_data,
            "scoring": {
                "final_score": session.final_score,
                "grade": session.grade,
                "feedback": session.feedback,
                "breakdown": session.score_details,
            },
            "emotion_trajectory": session.emotions,
            "conversation": messages,
        }

        total = query.count()
        sessions = query.offset(offset).limit(limit).all()

        return {
            "total": total,
            "sessions": [{
                "id": s.id,
                "persona_name": s.persona_name,
                "persona_summary": s.persona_summary,
                "difficulty": s.difficulty,
                "status": s.status,
                "total_rounds": s.total_rounds,
                "final_score": s.final_score,
                "grade": s.grade,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            } for s in sessions],
        }

    # ===== 內部方法 =====

    def _get_practitioner_name(self, db: Session, session: SimulationSession) -> str:
        """查詢練習者的顯示名稱"""
        if session.admin_id:
            from app.models.admin import AdminAccount
            admin = db.query(AdminAccount).filter(
                AdminAccount.id == session.admin_id
            ).first()
            if admin:
                return admin.display_name
        return "未知"

    def _build_conversation_history(self, session: SimulationSession) -> list[dict]:
        """
        從 DB 訊息建立 Claude 用的對話歷史

        跳過 round 0 的 assistant 開場白 —— Claude API 要求 messages 陣列
        必須以 user 角色開頭。開場白改放在 system prompt 中提供上下文。
        """
        history = []
        for msg in session.messages:
            # 跳過 round 0 的開場白（已放入 system prompt）
            if msg.round_number == 0 and msg.role == "assistant":
                continue
            history.append({
                "role": msg.role,
                "content": msg.content,
            })
        return history

    def _get_opening_message(self, session: SimulationSession) -> str:
        """取得 round 0 的開場白文字"""
        for msg in session.messages:
            if msg.round_number == 0 and msg.role == "assistant":
                return msg.content
        return ""

    def _format_conversation_log(self, session: SimulationSession) -> str:
        """格式化對話記錄（評分用）"""
        lines = []
        for msg in session.messages:
            role_label = "經紀人" if msg.role == "user" else "諮詢者"
            lines.append(f"[{role_label}] {msg.content}")
            if msg.inner_thought and msg.role == "assistant":
                lines.append(f"  （諮詢者內心：{msg.inner_thought}）")
            if msg.current_emotion and msg.role == "assistant":
                lines.append(f"  （情緒：{msg.current_emotion}，信任度：{msg.trust_level}，意願度：{msg.willingness}）")
        return "\n".join(lines)

    def _parse_json(self, content: str) -> dict:
        """從回覆中提取 JSON"""
        import re
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

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
                        return json.loads(content[start_idx:i + 1])
                    except json.JSONDecodeError:
                        start_idx = None

        # Fallback: return raw content as reply
        return {"reply": content, "emotion": "未知", "trust_level": 0.3, "willingness": 0.3}
