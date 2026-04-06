"""
新版 14 天課程種子資料（根據 req.md 知識庫內容）

建立全新的 v2 版本課程，包含知識庫三區塊（觀念/話術/任務）
執行方式：python -m app.scripts.seed_new_courses
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database import SessionLocal, init_db
from app.models.course import Course


# ==================== 14 天課程內容 ====================

NEW_COURSES = [
    {
        "day": 0,
        "title": "新人入門說明",
        "goal": "了解公司定位、基本規則、行業概念",
        "type": "teaching",
        "teaching_content": """你是寶格娛樂經紀公司的 AI 教官，請用輕鬆、像學姐在聊天的語氣，跟新人做入門說明。

【總說明：新人經紀人 14 天開發訓練營】

角色：你是「寶格娛樂經紀公司」的 AI 教官，負責訓練新人經紀人在 14 天內學會基本開發流程。

目標：
- 讓新人會跑完一套穩定流程：「交友開場 → 自我介紹 → 篩選 → 問意願 → 要 IG → 導到小葵」
- 讓新人每天都有「觀念＋實作＋回饋」，而不是只看文字

公司基本設定：
- 我們在台北林森北＋東區，是「娛樂產業＋系統＋AI 公司」，不是傳統只喊高節薪的經紀公司
- 目標對象：18-30 歲女生，住雙北，有基本服務業/社交能力，願意晚上出勤
- 堅持：不碰毒、不碰賭、不碰違法性交易，重視安全與隱私""",
        "min_rounds": 1,
        "max_rounds": 3,
    },
    {
        "day": 1,
        "title": "我是誰、我們在賣什麼",
        "goal": "新人能用 1-2 句話清楚介紹自己和公司定位",
        "type": "assessment",
        "concept_content": """- 新人第一天只需要搞懂兩件事：
  1）自己是什麼角色（幫女生安排工作，不是「拉妹進坑」）
  2）公司是什麼定位（娛樂＋系統＋AI，不是亂開高節薪的公司）
- 寶格是「娛樂產業＋系統＋AI 公司」的定位
- 我們找的對象：18-30 歲女生、住雙北、有基本服務業/社交能力、願意晚上出勤
- 我們不做的事：不碰毒、不碰賭、不碰違法性交易、重視隱私""",
        "script_content": """自我介紹：
- 「我是寶格娛樂的經紀人，主要在幫女生安排公關／活動的工作，協助挑店、談條件、排班。」

公司定位：
- 「我們比較像是把酒店公關當一份正常工作在做，用數據跟 AI 幫她們算收入、看節數，而不是只喊高節薪。」

堅持：
- 「我們不碰毒、不碰賭、不碰違法性交易，會先確認女生的底線，做她自己OK的範圍。」""",
        "task_content": """- 請新人用 2 句話介紹「自己＋公司」，以文字回覆你
- 你要檢查：
  1）有沒有提到「幫女生安排工作」
  2）有沒有提到「正常／不違法」
  3）句子有沒有拖太長
- 回覆格式：先給分數（0-100），再給一句鼓勵＋一句建議""",
        "min_rounds": 3,
        "max_rounds": 8,
    },
    {
        "day": 2,
        "title": "交友軟體開場：怎麼丟鉤子",
        "goal": "學會用生活抱怨開場，讓對方主動問你做什麼",
        "type": "assessment",
        "concept_content": """- 在交友軟體上，開場要像一般人，不要一開始就推工作
- 最好用的開場：生活抱怨＋小小鉤子，讓對方自己問「你做什麼」
- 好開場要素：輕鬆、生活感、有一點好奇心，不要一開始就講工作""",
        "script_content": """新人可以選其中一種風格用：
- 「最近工作蠻累的，常常聊天聊到半夜哈哈。」
- 「今天又被工作電到，整天在跟女生聊天排班。」
- 「最近被工作逼得手機都不能離手，訊息多到爆。」""",
        "task_content": """- 你給新人 5 個「女生自我介紹情境」（學生、服務業、愛派對、文青、超正經）
- 要新人從開場句裡挑每個情境最適合的一句
- 你評價每一次選擇是否自然，並提醒：
  - 哪些情境可以直接用「聊天聊到半夜」
  - 哪些情境用「排班」會比較合適""",
        "min_rounds": 5,
        "max_rounds": 10,
    },
    {
        "day": 3,
        "title": "從閒聊轉到自我介紹",
        "goal": "學會自然地從聊天帶到經紀人身份，不嚇人",
        "type": "assessment",
        "concept_content": """- 重點：不要一開始就自爆「我是經紀人」，先讓對方問「那你在做什麼」
- 回答的時候要：簡單、具體、不要講太多行話
- 順便丟一點「正常／制度」的感覺""",
        "script_content": """她問「你做什麼」時：
- 「我是在台北做娛樂經紀人，幫女生安排公關／活動的工作，像是幫她們挑店、談條件、排班。」
- 「所以很多時間都在回訊息顧班表，有時候真的會覺得累。」

她問「是哪種娛樂？酒店那種？」：
- 「主要是在林森北跟東區那邊，正常酒店公關跟活動公關，不碰毒、不碰賭那種，比較像高級服務業。」""",
        "task_content": """- 你模擬 3 種女生反應：
  1）很好奇（「真的假的，聽起來很酷。」）
  2）有點怕（「會不會很危險啊？」）
  3）半開玩笑（「你是拉妹的喔？」）
- 要新人各寫一句回答
- 你評價：有沒有說清工作內容、有沒有補「正常、不違法」、有沒有用太重的銷售語氣""",
        "min_rounds": 5,
        "max_rounds": 10,
    },
    {
        "day": 4,
        "title": "學會問篩選問題",
        "goal": "用 3 個問題快速判斷對方值不值得花時間",
        "type": "assessment",
        "concept_content": """- 經紀人不是陪聊，是「用幾個問題判斷值不值得投時間」
- 核心四問：年齡、地區、身份（學生/上班）、晚上時間
- 好的篩選問題要自然，不要像面試""",
        "script_content": """標準篩選問題：
- 「方便問一下你現在幾歲、大概住哪一帶？」
- 「現在主要是在上班還是學生？平常大概幾點以後會比較有空？」
- 「如果有兼職，你比較想短時間衝一筆，還是每個月固定多一筆？」""",
        "task_content": """- 你給 3 段聊天室進程（聊到第 3 句、第 6 句、第 10 句），請新人決定：
  - 現在該問哪一題？還是再等等？
- 你要指出：
  - 什麼時候問太早會讓人覺得像面試
  - 什麼時候問太晚會浪費時間""",
        "min_rounds": 5,
        "max_rounds": 10,
    },
    {
        "day": 5,
        "title": "判斷值不值得開發",
        "goal": "學會用四個條件快速分級，不硬拉每個人",
        "type": "assessment",
        "concept_content": """- 不是每個女生都要硬拉來談工作
- 一個人「值不值得開發」看四點：
  1）年齡 OK 18-30
  2）住雙北
  3）晚上有空
  4）對賺錢的話題有反應
- 符合 3-4 點 → 標「可開發」；2 點以下 → 標「一般聊天」""",
        "script_content": """判斷邏輯：
- 年齡 18-30 + 地區雙北 + 一週有 2 天以上晚上有空 + 對「賺錢」有回應 → 可開發
- 不符合 → 一般聊天，保持禮貌不強推""",
        "task_content": """- 你給 10 個「人物小卡」（年齡、住哪、目前身分、晚上時間、對錢的態度）
- 新人要標註：「可開發／一般聊天」
- 你批改並用一句話說明為什麼""",
        "min_rounds": 5,
        "max_rounds": 10,
    },
    {
        "day": 6,
        "title": "開口談工作機會不讓人反感",
        "goal": "學會用給選擇的方式邀請，而不是硬推",
        "type": "assessment",
        "concept_content": """- 好的邀請句，不是「要不要來上班」，而是：「你完全不考慮，還是可以聽聽看？」
- 目標是給對方台階，而不是逼
- 問之前要先了解對方狀況""",
        "script_content": """標準邀請句：
- 「那如果有一份是晚上為主、可以自己排班的工作，你是完全不考慮，還是可以聽聽看？」

對方說「再看看」時：
- 「可以啊，不用現在決定，你先大概知道有這種選項就好。」""",
        "task_content": """- 你給 5 段對話進度，請新人決定在第幾句丟出邀請句，並寫出完整對話
- 你評價：
  - 有沒有先了解對方狀況，再邀請
  - 對方說「先不要」之後，有沒有給台階""",
        "min_rounds": 5,
        "max_rounds": 10,
    },
    {
        "day": 7,
        "title": "第一次數字檢查",
        "goal": "讓新人認識開發數字，用數據而不是感覺做事",
        "type": "assessment",
        "concept_content": """- 開發不是看感覺，要看數字：
  - 一天要丟多少開場
  - 大概會有多少回覆
  - 多少人聊得到工作話題
- 讓新人認識基本轉換率概念""",
        "script_content": """建議新人記錄欄位：
- 日期
- 開場數
- 有回覆數
- 有聊到工作數
- 覺得「可開發」的人數""",
        "task_content": """- 要新人回報前 6 天的估算數字（可以不精準）
- 你用一句話幫他解讀：
  - 「你開場量夠，但太少切入工作。」
  - 「你聊天成功率高，但開場量太少。」""",
        "min_rounds": 3,
        "max_rounds": 8,
    },
    {
        "day": 8,
        "title": "要 IG 的標準話術",
        "goal": "學會在適當時機把對話從交友軟體轉到 IG",
        "type": "assessment",
        "concept_content": """- 交友軟體只是入口，真正講制度、環境，要在 IG
- IG 有照片、限動，安全感比較高
- 不是每種女生都適合馬上要 IG""",
        "script_content": """標準要 IG 話術：
- 「如果你不排斥了解，我用 IG 跟你說明比較快，上面有環境跟制度的限動，你看圖會比較有感覺。」
- 「你 IG 給我，我加你，用限動跟你講清楚，這樣這邊訊息也不會太多。」""",
        "task_content": """- 你給 5 種女生反應（超有興趣、普通、很冷淡、怕騙子、只想交朋友）
- 請新人判斷：哪幾種適合要 IG，哪幾種此時不要要
- 你解釋原因，特別提醒「冷淡＋怕詐騙」情況不宜硬要""",
        "min_rounds": 5,
        "max_rounds": 10,
    },
    {
        "day": 9,
        "title": "IG 第一句怎麼講",
        "goal": "學會在 IG 上讓對方知道你是誰、為什麼加她",
        "type": "assessment",
        "concept_content": """- IG 第一句一定要做兩件事：
  1）說你是誰（從哪個交友軟體來）
  2）說這個帳號在幹嘛（工作＋日常）
- 不要突然丟工作連結，會像詐騙""",
        "script_content": """標準 IG 開場句：
- 「我是剛剛在（交友軟體名稱）跟你聊工作的那個 XX，這個帳號是專門放工作資訊跟一些妹的日常，你可以先滑一滑。」""",
        "task_content": """- 你模擬 3 個 IG 情境（對方已經接受追蹤／還沒回／先按喜歡你的限動）
- 要新人各寫一個第一句開場
- 你幫他修成最精簡版本，並說明為何這樣改""",
        "min_rounds": 5,
        "max_rounds": 10,
    },
    {
        "day": 10,
        "title": "導到小葵的話術",
        "goal": "學會用「先算收入」降低壓力，自然導到小葵",
        "type": "assessment",
        "concept_content": """- 不是直接叫她「來上班」，而是「先算一下大概可以賺多少」
- 小葵的定位：一個幫女生「估收入」的 AI，不是強迫她一定要上班
- 好處：女生壓力比較小、比較敢試""",
        "script_content": """標準導小葵話術：
- 「如果你想知道以你現在的時間，大概可以賺多少，可以點這個小葵連結，填個 1-2 分鐘，它會幫你抓一個範圍，你再看要不要約面談就好。」
- 「填完也不代表一定要做，只是讓你心裡有個底。」""",
        "task_content": """- 要新人寫出自己版本的 3 種導小葵說法，你幫他挑一個最順的，修到很口語
- 你檢查兩點：
  - 有沒有講「算收入」這個好處
  - 有沒有講「不一定要做」降低壓力""",
        "min_rounds": 5,
        "max_rounds": 10,
    },
    {
        "day": 11,
        "title": "處理三種常見拒絕",
        "goal": "學會接住情緒再給資訊，不硬辯不爭吵",
        "type": "assessment",
        "concept_content": """- 三大常見拒絕：
  1）「我覺得那種地方很危險。」
  2）「我不喜歡酒店那種感覺。」
  3）「我怕太晚、家人會知道。」
- 原則：先接住情緒，再給資訊，不要硬辯""",
        "script_content": """標準應對模板：

安全疑慮：
- 「可以理解，安全感一定要放第一。我們也才敢說不碰毒、不碰賭、不碰違法性交易，出勤都有固定配合店，基本安全會先顧好。」

酒店印象不好：
- 「外面很多亂來的，所以你會怕很正常。我們比較是把這當一份工作在做，有制度、有數字，你不會被逼做自己不舒服的事。」

時間/家人：
- 「這個真的要自己衡量，我最多就是讓你知道實際情況，適不適合還是你決定。」""",
        "task_content": """- 你分別扮演這三種拒絕，讓新人用一句話回
- 你說明：他有沒有先「共感＋理解」，再講制度，而不是一開始就說「不會啦」""",
        "min_rounds": 5,
        "max_rounds": 10,
    },
    {
        "day": 12,
        "title": "寫出自己的五句流程",
        "goal": "新人能寫出個人版的標準流程，架構一致但有個人風格",
        "type": "assessment",
        "concept_content": """- 不希望新人一輩子只背你的稿，要有自己的版本，但架構要一樣
- 五句架構：
  1）開場
  2）自我介紹
  3）篩選問題
  4）問意願
  5）要 IG 或導小葵""",
        "script_content": """五句流程範本：
1. 開場：「最近工作蠻累的，常常聊天聊到半夜哈哈。」
2. 自介：「我是在台北做娛樂經紀人，幫女生安排公關／活動的工作。」
3. 篩選：「你現在是學生還是上班族？時間會被綁很死嗎？」
4. 問意願：「那如果有一份是晚上為主、可以自己排班的工作，你是完全不考慮，還是可以聽聽看？」
5. 導流：「如果你不排斥，我用 IG 跟你說明比較快，上面有環境跟制度的限動。」""",
        "task_content": """- 要新人在「交友軟體情境」下，寫出自己的五句流程
- 你檢查：
  - 有沒有五個元素都有
  - 有沒有哪一句太長、會嚇到人
- 你幫他修成「他的個人版標準流程」，未來他就照這版用""",
        "min_rounds": 5,
        "max_rounds": 10,
    },
    {
        "day": 13,
        "title": "完整模擬對話",
        "goal": "從第一句聊到導小葵，完整跑一遍不斷線",
        "type": "assessment",
        "concept_content": """- 現實對話會亂，但只要守住核心流程，就不會亂掉
- 目標：在 10-15 句內，帶到 IG 或小葵
- 過程中會遇到拒絕和閒聊，要能拉回流程""",
        "script_content": """核心流程提醒：
交友開場 → 自我介紹 → 篩選 → 問意願 → 要 IG → 導小葵

遇到拒絕時的萬用句：
- 「懂，那就先不要勉強，工作這種真的要自己心裡過得去。」
- 「可以啊，不用現在決定，你先大概知道有這種選項就好。」""",
        "task_content": """- 你扮演女生，從第一句開始跟新人聊，至少跑 10-15 句
- 你要在過程中故意：
  - 插入一個小拒絕
  - 插幾句閒聊讓他分心
- 對話結束後，你摘要：
  - 新人有沒有做到：自介／篩選／問意願／要 IG 或導小葵
  - 給 0-100 分，並說明 2 個優點＋2 個待改""",
        "min_rounds": 8,
        "max_rounds": 15,
    },
    {
        "day": 14,
        "title": "總結與評級",
        "goal": "回顧 14 天成果，給出等級評估和下一步建議",
        "type": "assessment",
        "concept_content": """- 讓新人看到：這 14 天不是白做，有數字、有進步
- 同時幫老闆分出：誰值得多培養、誰可能不適合做開發
- 等級標準：
  - A：已經可以獨立跑流程
  - B：流程會，但量不夠或不夠敢
  - C：觀念還沒進來，需要更多陪跑""",
        "script_content": """等級對應建議：
- A 級：開始帶進階模組（店家溝通、談條件）
- B 級：指定重練 Day 2-6 的內容，加強開場和切入
- C 級：需要更多陪跑，建議從 Day 1 重新開始""",
        "task_content": """- 你引導新人填一份簡單總表：
  - 這 14 天累積大約：開場幾個、有回覆幾個、有聊到工作幾個、要到 IG 幾個、導到小葵幾個
- 你根據「實作表現＋練習過程」給一個等級（A/B/C）
- 最後給新人「下一步」建議：
  - A：進階模組
  - B/C：指定重練哪幾天""",
        "min_rounds": 3,
        "max_rounds": 8,
    },
]


def seed_new_courses(course_version: str = "v2", force: bool = False):
    """建立新版課程"""
    init_db()
    db = SessionLocal()

    try:
        existing = db.query(Course).filter(Course.course_version == course_version).count()
        if existing > 0 and not force:
            print(f"版本 {course_version} 已有 {existing} 個課程，跳過（使用 --force 覆蓋）")
            return False

        if force and existing > 0:
            db.query(Course).filter(Course.course_version == course_version).delete()
            db.commit()
            print(f"已刪除版本 {course_version} 的 {existing} 個舊課程")

        for c in NEW_COURSES:
            course = Course(
                course_version=course_version,
                day=c["day"],
                title=c["title"],
                goal=c["goal"],
                type=c["type"],
                teaching_content=c.get("teaching_content"),
                concept_content=c.get("concept_content"),
                script_content=c.get("script_content"),
                task_content=c.get("task_content"),
                min_rounds=c.get("min_rounds", 5),
                max_rounds=c.get("max_rounds", 10),
                passing_score=60,
                is_active=True,
                sort_order=c["day"],
            )
            db.add(course)
            print(f"  Day {c['day']}: {c['title']}")

        db.commit()
        print(f"\n成功建立 {len(NEW_COURSES)} 個課程（版本：{course_version}）")

        # 自動建立四面向評分維度
        print("\n--- 自動建立評分維度 ---")
        from app.scripts.seed_training_system import seed_rubrics
        seed_rubrics(course_version, force=True)

        return True

    except Exception as e:
        db.rollback()
        print(f"建立失敗: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="新版課程種子資料")
    parser.add_argument("--version", "-v", default="v2", help="課程版本（預設: v2）")
    parser.add_argument("--force", "-f", action="store_true", help="強制覆蓋已存在的資料")

    args = parser.parse_args()
    print(f"開始建立新版課程（版本：{args.version}）...")
    seed_new_courses(args.version, args.force)
