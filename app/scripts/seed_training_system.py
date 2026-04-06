"""
AI 教練訓練系統種子資料

建立預設模擬人設 + 四面向評分維度
執行方式：python -m app.scripts.seed_training_system
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database import SessionLocal, init_db
from app.models.scenario_persona import ScenarioPersona
from app.models.scoring_rubric import ScoringRubric
from app.models.course import Course


# ==================== 預設模擬人設 ====================

DEFAULT_PERSONAS = [
    {
        "name": "無經驗型（原 Persona A）",
        "code": "inexperienced",
        "description": """## 你要扮演的角色：無經驗的女生
- 年齡約 18-20 歲，第一次接觸這個行業
- 對行業有誤解，擔心危險或色情
- 語氣比較害羞、猶豫、會問很多基本問題
- 可能會問到薪水相關問題""",
        "behavior_traits": ["害羞猶豫", "問基本問題", "擔心安全", "對行業有誤解"],
        "opening_templates": ["我覺得這行聽起來很亂，也有點可怕", "請問你們是做什麼的？我有點緊張"],
        "difficulty_level": 1,
    },
    {
        "name": "有經驗型（原 Persona B）",
        "code": "experienced",
        "description": """## 你要扮演的角色：有經驗的女生
- 年齡約 21-24 歲，曾在類似行業工作過
- 了解一些術語，可能會比較公司差異
- 語氣比較直接、會問實際問題
- 可能會問到薪水、制度相關問題""",
        "behavior_traits": ["語氣直接", "會比較公司", "問實際問題", "了解行業術語"],
        "opening_templates": ["你們是不是都講得很好聽？", "我之前在別家做過，你們這邊制度怎樣？"],
        "difficulty_level": 2,
    },
    {
        "name": "好奇型",
        "code": "curious",
        "description": """## 你要扮演的角色：好奇型女生
- 年齡約 20-22 歲，對什麼都好奇
- 覺得這工作聽起來很酷、很新鮮
- 會主動追問細節，但不是來鬧的
- 語氣輕鬆、開朗，容易聊開""",
        "behavior_traits": ["會主動追問", "語氣輕鬆", "對新事物好奇", "容易聊開"],
        "opening_templates": ["真的假的，聽起來很酷欸", "你們那邊是做什麼的啊？感覺蠻特別的"],
        "difficulty_level": 1,
    },
    {
        "name": "恐懼型",
        "code": "scared",
        "description": """## 你要扮演的角色：恐懼型女生
- 年齡約 19-21 歲，非常擔心安全問題
- 聽過很多負面新聞，害怕被騙或被強迫
- 語氣緊張、不安，會反覆確認安全
- 需要很多安全感才願意繼續聊""",
        "behavior_traits": ["非常擔心安全", "會反覆確認", "語氣緊張", "害怕被騙"],
        "opening_templates": ["會不會很危險啊？我看新聞都說…", "我朋友說這種工作很可怕，是真的嗎？"],
        "difficulty_level": 2,
    },
    {
        "name": "半開玩笑型",
        "code": "joking",
        "description": """## 你要扮演的角色：半開玩笑型女生
- 年齡約 20-23 歲，性格大辣辣
- 會用戲謔的方式問問題，但其實有在認真聽
- 語氣帶點玩笑，但不是惡意
- 會測試新人的反應能力""",
        "behavior_traits": ["語氣戲謔", "會開玩笑", "其實有在聽", "測試反應"],
        "opening_templates": ["你是拉妹的喔？哈哈", "所以你是那種什麼都講得很好聽的經紀人嗎？"],
        "difficulty_level": 2,
    },
    {
        "name": "懷疑型",
        "code": "skeptical",
        "description": """## 你要扮演的角色：懷疑型女生
- 年齡約 22-25 歲，社會經驗比較豐富
- 對經紀人有戒心，覺得都在畫大餅
- 會故意問一些刁鑽的問題來試探
- 需要很具體的數據和制度才會信""",
        "behavior_traits": ["有戒心", "問刁鑽問題", "要具體數據", "不容易相信"],
        "opening_templates": ["你們是不是都講得很好聽，到最後都不一樣？", "每個經紀人都說自己最好，你跟別人有什麼不同？"],
        "difficulty_level": 3,
    },
    {
        "name": "家人壓力型",
        "code": "family_concern",
        "description": """## 你要扮演的角色：有家人壓力的女生
- 年齡約 20-24 歲，自己有興趣但怕家人知道
- 主要擔心：家人反對、社會眼光、朋友知道
- 語氣猶豫，在「想做」和「不敢做」之間搖擺
- 會問很多關於隱私保護的問題""",
        "behavior_traits": ["怕家人知道", "在猶豫中", "問隱私問題", "擔心社會眼光"],
        "opening_templates": ["我怕家人知道怎麼辦？", "如果被認識的人看到怎麼辦？"],
        "difficulty_level": 2,
    },
    {
        "name": "強勢型",
        "code": "aggressive",
        "description": """## 你要扮演的角色：強勢型女生
- 年齡約 23-26 歲，個性很強、不好惹
- 說話直接、不拐彎抹角
- 會直接挑戰新人的說法，追問到底
- 新人需要保持冷靜、不卑不亢""",
        "behavior_traits": ["說話直接", "會挑戰說法", "追問到底", "個性強勢"],
        "opening_templates": ["你直接說重點，不要跟我繞", "我時間不多，你快說你們條件是什麼"],
        "difficulty_level": 3,
    },
    {
        "name": "來鬧的",
        "code": "troll",
        "description": """## 你要扮演的角色：來鬧的人
- 不是真的想來工作，純粹好奇或無聊
- 可能會問一些故意刁難或不正經的問題
- 語氣可能輕浮、不認真
- 新人需要判斷這種人不值得花時間，禮貌收尾""",
        "behavior_traits": ["故意刁難", "語氣輕浮", "不認真", "浪費時間"],
        "opening_templates": ["欸你們是不是那種很色的地方啊哈哈", "我朋友叫我來問問看，其實我也不知道要問什麼"],
        "difficulty_level": 3,
    },
]


# ==================== 預設四面向評分維度 ====================

DEFAULT_RUBRIC_DIMENSIONS = [
    {
        "dimension": "process_completeness",
        "dimension_label": "流程完整性",
        "description": "新人有沒有照標準流程走：開場→自介→篩選→問意願→導 IG/小葵",
        "sort_order": 0,
        "tiers": [
            {"score": 25, "criteria": "流程步驟完整、順序合理，沒有長時間卡在閒聊，也沒有直接跳過中間步驟"},
            {"score": 20, "criteria": "少一個小步驟（例如忘記問出勤），但整體方向正確"},
            {"score": 10, "criteria": "有亂跳流程，例如直接推小葵/工作，幾乎沒篩選"},
            {"score": 0, "criteria": "完全看不出流程，只是在碎聊或硬推銷"},
        ],
    },
    {
        "dimension": "script_accuracy",
        "dimension_label": "話術到位度",
        "description": "說的內容是不是符合公司標準話術和觀念",
        "sort_order": 1,
        "tiers": [
            {"score": 25, "criteria": "關鍵資訊都有，句子口語自然，沒有奇怪專有名詞或太硬的銷售字眼"},
            {"score": 20, "criteria": "多數關鍵點有講到，但少 1-2 個細節（例如忘了說不違法）"},
            {"score": 10, "criteria": "有明顯缺漏，或用詞容易讓人誤會（例如「真的很好賺」「保證如何」等誇大語）"},
            {"score": 0, "criteria": "話術嚴重偏離公司規範（例如暗示違法內容、講到「包到底」之類）"},
        ],
    },
    {
        "dimension": "emotional_control",
        "dimension_label": "情緒風險控制",
        "description": "新人有沒有穩住對方情緒、避免被檢舉、避免壓迫感",
        "sort_order": 2,
        "tiers": [
            {"score": 25, "criteria": "遇到拒絕或擔心時，先「理解+緩和」，再補制度資訊，語氣冷靜、不吵架"},
            {"score": 20, "criteria": "基本上有安撫，但有小地方稍微太硬（例如回覆有點急躁、解釋太多）"},
            {"score": 10, "criteria": "略帶爭辯、反駁語氣，讓對方可能更防備"},
            {"score": 0, "criteria": "明顯有情緒或恐嚇、威脅意味，或使用高壓話語"},
        ],
    },
    {
        "dimension": "action_orientation",
        "dimension_label": "行動結果導向",
        "description": "新人有沒有帶到下一步（要 IG / 導小葵），而不是只聊爽",
        "sort_order": 3,
        "tiers": [
            {"score": 25, "criteria": "在合理時機提出下一步（要 IG / 導小葵），說得清楚、不勉強"},
            {"score": 20, "criteria": "有提出 CTA，但時機稍微太早或太晚"},
            {"score": 10, "criteria": "聊了很多，但最後沒有任何下一步，只是停在「之後再聊」"},
            {"score": 0, "criteria": "完全沒有意識到需要下一步，或 CTA 完全不清楚"},
        ],
    },
]


def seed_personas(course_version: str = "v1", force: bool = False):
    """建立預設模擬人設"""
    init_db()
    db = SessionLocal()

    try:
        existing = db.query(ScenarioPersona).filter(
            ScenarioPersona.course_version == course_version
        ).count()

        if existing > 0 and not force:
            print(f"版本 {course_version} 已有 {existing} 個人設，跳過（使用 --force 覆蓋）")
            return False

        if force and existing > 0:
            db.query(ScenarioPersona).filter(
                ScenarioPersona.course_version == course_version
            ).delete()
            db.commit()
            print(f"已刪除版本 {course_version} 的 {existing} 個舊人設")

        for i, p in enumerate(DEFAULT_PERSONAS):
            persona = ScenarioPersona(
                course_version=course_version,
                name=p["name"],
                code=p["code"],
                description=p["description"],
                behavior_traits=json.dumps(p["behavior_traits"], ensure_ascii=False),
                opening_templates=json.dumps(p["opening_templates"], ensure_ascii=False),
                difficulty_level=p["difficulty_level"],
                sort_order=i,
                is_active=True,
            )
            db.add(persona)
            print(f"  {p['name']} ({p['code']}) - 難度 {p['difficulty_level']}")

        db.commit()
        print(f"\n成功建立 {len(DEFAULT_PERSONAS)} 個模擬人設")
        return True

    except Exception as e:
        db.rollback()
        print(f"建立失敗: {e}")
        return False
    finally:
        db.close()


def seed_rubrics(course_version: str = "v1", force: bool = False):
    """為每個課程建立四面向評分維度"""
    init_db()
    db = SessionLocal()

    try:
        courses = db.query(Course).filter(
            Course.course_version == course_version,
            Course.type != "teaching",
        ).order_by(Course.day).all()

        if not courses:
            print(f"版本 {course_version} 沒有考核型課程，請先執行 seed_courses")
            return False

        created = 0
        for course in courses:
            existing = db.query(ScoringRubric).filter(
                ScoringRubric.course_id == course.id
            ).count()

            if existing > 0 and not force:
                print(f"  Day {course.day} 已有 {existing} 個評分維度，跳過")
                continue

            if force and existing > 0:
                db.query(ScoringRubric).filter(
                    ScoringRubric.course_id == course.id
                ).delete()

            for dim in DEFAULT_RUBRIC_DIMENSIONS:
                rubric = ScoringRubric(
                    course_id=course.id,
                    dimension=dim["dimension"],
                    dimension_label=dim["dimension_label"],
                    description=dim["description"],
                    sort_order=dim["sort_order"],
                    tiers=json.dumps(dim["tiers"], ensure_ascii=False),
                )
                db.add(rubric)
                created += 1

            print(f"  Day {course.day}: {course.title} - 4 個維度")

        db.commit()
        print(f"\n成功建立 {created} 個評分維度")
        return True

    except Exception as e:
        db.rollback()
        print(f"建立失敗: {e}")
        return False
    finally:
        db.close()


def seed_all(course_version: str = "v1", force: bool = False):
    """建立所有種子資料"""
    print("=" * 50)
    print(f"建立 AI 教練訓練系統種子資料（版本：{course_version}）")
    print("=" * 50)

    print("\n--- 建立模擬人設 ---")
    seed_personas(course_version, force)

    print("\n--- 建立評分維度 ---")
    seed_rubrics(course_version, force)

    print("\n" + "=" * 50)
    print("完成！")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI 教練訓練系統種子資料")
    parser.add_argument("action", choices=["all", "personas", "rubrics"], help="執行動作")
    parser.add_argument("--version", "-v", default="v1", help="課程版本 (預設: v1)")
    parser.add_argument("--force", "-f", action="store_true", help="強制覆蓋已存在的資料")

    args = parser.parse_args()

    if args.action == "all":
        seed_all(args.version, args.force)
    elif args.action == "personas":
        seed_personas(args.version, args.force)
    elif args.action == "rubrics":
        seed_rubrics(args.version, args.force)
