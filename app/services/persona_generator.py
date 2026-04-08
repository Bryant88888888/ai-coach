"""動態人格生成引擎

每次呼叫都會生成一個完全不同的、極度真實的諮詢者人格。
不使用固定模板 — 讓 Claude 根據真實世界的多樣性自由發揮。
"""
import json
import random
from anthropic import Anthropic
from app.config import get_settings


# 生成用的 meta-prompt：指導 Claude 如何創造一個真實的人
PERSONA_GENERATION_PROMPT = """你是一個人格設計專家。你要為「酒店經紀公司的新人訓練系統」生成一個**極度真實的諮詢者角色**。

## 背景
經紀公司的工作是招募女生到酒店/KTV/夜總會等八大行業上班。會來諮詢的人形形色色、百百種，每個人的故事和動機都不一樣。

## 你要生成的角色
這個角色是一個「正在考慮要不要來做這行」的人，她會透過 LINE 或電話來詢問經紀人。

## 要求
1. **極度真實** — 這個人要像你在現實生活中會遇到的真人，有自己的故事、矛盾、情緒
2. **不可預測** — 不要寫出套路化的角色，真實的人是複雜的、有時候自相矛盾的
3. **有深度** — 她有說出來的話，也有沒說出來但影響她行為的心理因素
4. **自然語氣** — 她說話的方式要符合她的年齡、教育程度、情緒狀態（不要文謅謅）

## 難度說明
{difficulty_instruction}

## 隨機種子（用來增加變化性）
以下是隨機選取的元素，你可以自由組合或忽略，重點是創造一個連貫且真實的角色：
- 觸發元素：{seed_trigger}
- 性格傾向：{seed_personality}
- 生活壓力源：{seed_pressure}
- 溝通風格：{seed_communication}
- 特殊狀況：{seed_special}

## 輸出格式（JSON）
```json
{{
  "name": "她的暱稱或自稱（自然的，不要太戲劇化）",
  "age": 數字,
  "summary": "一句話描述這個人（給訓練管理員看的）",
  "background": {{
    "education": "學歷",
    "current_job": "目前的工作狀況",
    "family": "家庭狀況（簡潔）",
    "financial": "經濟狀況"
  }},
  "motivation": {{
    "stated_reason": "她會說出口的理由",
    "real_reason": "她真正的動機（可能跟說出口的不一樣）",
    "urgency": "low/medium/high — 她有多急"
  }},
  "psychology": {{
    "personality_traits": ["3-5個性格特徵"],
    "emotional_state": "現在的情緒狀態",
    "fears": ["她害怕或擔心的事情"],
    "dealbreakers": ["絕對不能接受的事情"],
    "hidden_concerns": ["她不會主動說但會影響她決定的事"]
  }},
  "communication": {{
    "style": "她的說話風格描述",
    "typical_phrases": ["她會用的口頭禪或慣用語，3-5個"],
    "text_style": "她打字的風格（用注音、很多表情符號、很簡短、會打錯字等）"
  }},
  "behavior": {{
    "initial_attitude": "一開始的態度（開放/防備/試探/急切等）",
    "trust_building": "什麼樣的回應會讓她更信任經紀人",
    "trust_breaking": "什麼樣的回應會讓她反感或不信任",
    "decision_pattern": "她做決定的方式（衝動/需要想很久/要問別人等）",
    "likely_objections": ["她可能會提出的反對意見或質疑"],
    "conversion_signals": ["如果她開始有興趣會出現的信號"]
  }},
  "scenario": {{
    "how_she_found_us": "她怎麼找到這間經紀公司的",
    "opening_message": "她的第一句話（要非常自然，像真的在 LINE 上打的）",
    "time_context": "她在什麼時間點聯絡的（半夜睡不著、上班偷滑手機等）"
  }},
  "system_prompt_for_roleplay": "（你要寫一段完整的 system prompt，指導 AI 如何扮演這個角色進行對話。要包含角色的說話方式、情緒反應邏輯、什麼時候會更信任或更防備、什麼時候會想離開對話等細節。這段 prompt 會直接用來驅動對話 AI。）"
}}
```

只輸出 JSON，不要有其他文字。"""


# 隨機元素池 — 增加生成多樣性
SEED_TRIGGERS = [
    "朋友介紹說這行很好賺", "在社群看到徵人廣告", "前男友欠錢跑了",
    "被家暴想離開", "失業兩個月了", "純粹好奇想了解", "想存一筆錢出國",
    "在酒吧打工覺得不如直接做", "離婚需要養小孩", "學貸壓力",
    "之前做過但休息一陣子", "姐妹在做想一起", "想買車需要頭期款",
    "大學剛畢業找不到工作", "媽媽生病需要醫藥費", "想整形需要錢",
    "跟家裡鬧翻需要搬出來", "男朋友不知道她來問", "其實是幫朋友問的",
    "之前在別家被騙過", "想兼職白天還有正職", "單親媽媽",
    "從南部上來人生地不熟", "原住民女生想打工", "越南新住民",
    "在醫美診所上班但薪水不夠", "網紅想賺外快", "模特兒經紀介紹來的",
    "酒促做膩了想轉型", "前公關想回來做", "在夜市擺攤賠錢",
    "爸爸賭博欠債", "房租快付不出來", "想環遊世界存旅費",
    "高中就在做但中斷了", "大學生想賺學費", "護理師想轉行",
]

SEED_PERSONALITIES = [
    "內向害羞但其實很有主見", "外向健談但內心很不安",
    "很直接講話不拐彎", "很會裝傻其實很精明",
    "情緒化容易哭", "冷靜理性像在面試",
    "很愛開玩笑用幽默掩飾不安", "防備心很重什麼都懷疑",
    "天真單純容易被影響", "老鳥態度很隨意",
    "很焦慮一直問問題", "慢熟一開始話很少",
    "很有禮貌但保持距離", "講話很衝但不是真的生氣",
    "優柔寡斷需要人推她一把", "自以為很懂但其實誤解很多",
    "很怕被看不起所以先嗆人", "溫柔但有自己的底線",
    "愛比較會一直拿別家比", "務實只看數字和條件",
]

SEED_PRESSURES = [
    "月底房租到期", "信用卡循環利息", "家人住院",
    "前夫追債", "養一個小孩", "弟弟的學費",
    "其實還好只是想多賺", "創業失敗的負債", "車貸",
    "整形分期付款", "男友的債她扛了", "獎學金沒了",
    "突然被資遣", "跟室友吵架要搬家", "手機壞了沒錢修",
    "想出國留學需要保證金", "毛小孩的醫療費", "被詐騙損失一筆錢",
]

SEED_COMMUNICATION = [
    "很會用表情符號", "打字很簡短像在發命令",
    "會打很長的訊息像在寫日記", "常常已讀不回過一陣子才回",
    "語音訊息比較多（用文字呈現口語感）", "會用很多「...」表示猶豫",
    "注音文夾雜", "像在審問一樣一個問題接一個",
    "會突然聊到別的話題", "常常打錯字但不修正",
    "很正式像在寫email", "很嗲很可愛的語氣",
    "粗獷直白偶爾爆粗口", "會一直說「嗯嗯」「好喔」很敷衍",
]

SEED_SPECIAL = [
    "其實她已經決定要做了只是想確認細節",
    "她根本不想做只是被朋友逼來問的",
    "她在同時問好幾家經紀公司在比較",
    "她之前在這行被客人騷擾過有陰影",
    "她其實未滿18歲但謊報年齡",
    "她的男朋友可能會突然介入對話",
    "她喝醉了在問",
    "她其實是同業來刺探的",
    "她有精神方面的困擾但不會說",
    "她很怕被認識的人發現",
    "她想做但又怕對不起爸媽",
    "她覺得這行的人都是騙子",
    "她只想做不喝酒不陪睡的類型",
    "她想知道能不能只做假日",
    "她之前在別家被扣了很多錢",
    "她朋友做這行出事了她很擔心",
    "她其實很漂亮但完全沒自信",
    "她是跨性別但不確定能不能做",
    "她帶小孩所以時間很不固定",
    "她是外籍配偶中文不太流利",
    "沒什麼特殊，就是一般來詢問的人",
    "她同時在考慮當直播主",
]

DIFFICULTY_INSTRUCTIONS = {
    "easy": """難度：簡單
生成一個**相對好溝通**的諮詢者：
- 態度比較開放，不會太防備
- 問題比較直接，不會繞彎子
- 動機明確，不會太矛盾
- 適合新手經紀人練習基本功""",

    "medium": """難度：中等
生成一個**有一定挑戰性**的諮詢者：
- 有些顧慮需要經紀人主動化解
- 可能會猶豫不決或提出質疑
- 有一些隱藏的擔憂不會主動說
- 需要經紀人展現一定的同理心和專業度""",

    "hard": """難度：困難
生成一個**非常有挑戰性**的諮詢者：
- 可能非常防備、懷疑、情緒化、或有複雜的個人狀況
- 有很深的隱藏顧慮，不容易打開心防
- 可能會突然改變態度、提出尖銳問題、或做出意外反應
- 需要經紀人有很強的應對能力和高 EQ
- 也可能是老鳥來比較條件，非常精明不容易被話術打動""",
}


class PersonaGenerator:
    """動態人格生成引擎"""

    def __init__(self):
        settings = get_settings()
        self.client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model

    def generate(self, difficulty: str = "random") -> dict:
        """
        生成一個全新的諮詢者人格

        Args:
            difficulty: easy / medium / hard / random

        Returns:
            完整的人格資料 dict
        """
        if difficulty == "random":
            difficulty = random.choice(["easy", "medium", "hard"])

        # 隨機抽取種子元素
        seeds = {
            "difficulty_instruction": DIFFICULTY_INSTRUCTIONS[difficulty],
            "seed_trigger": random.choice(SEED_TRIGGERS),
            "seed_personality": random.choice(SEED_PERSONALITIES),
            "seed_pressure": random.choice(SEED_PRESSURES),
            "seed_communication": random.choice(SEED_COMMUNICATION),
            "seed_special": random.choice(SEED_SPECIAL),
        }

        prompt = PERSONA_GENERATION_PROMPT.format(**seeds)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=3000,
            system="你是一個角色設計專家，擅長創造極度真實、有血有肉的人物。只輸出 JSON。",
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text

        # 解析 JSON
        persona = self._parse_json(content)

        # 驗證必要欄位（避免下游 KeyError）
        self._validate_persona(persona)

        persona["_difficulty"] = difficulty
        persona["_seeds"] = {
            "trigger": seeds["seed_trigger"],
            "personality": seeds["seed_personality"],
            "pressure": seeds["seed_pressure"],
            "communication": seeds["seed_communication"],
            "special": seeds["seed_special"],
        }

        return persona

    def _validate_persona(self, persona: dict):
        """驗證生成的人格包含所有必要欄位"""
        # 頂層必要欄位
        for field in ["name", "summary", "system_prompt_for_roleplay"]:
            if not persona.get(field):
                raise ValueError(f"生成的人格缺少必要欄位：{field}")

        # scenario.opening_message
        scenario = persona.get("scenario")
        if not isinstance(scenario, dict) or not scenario.get("opening_message"):
            raise ValueError("生成的人格缺少 scenario.opening_message")

        # psychology 區塊（情緒追蹤需要）
        if not isinstance(persona.get("psychology"), dict):
            raise ValueError("生成的人格缺少 psychology 區塊")

    def _parse_json(self, content: str) -> dict:
        """從 Claude 回覆中提取 JSON"""
        # 嘗試直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 嘗試找 JSON 區塊
        import re
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 嘗試找最外層 {}
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

        raise ValueError(f"無法從 AI 回覆中解析 JSON: {content[:200]}...")
