"""
課程種子資料腳本

將現有的 days_data.py 內容匯入資料庫
執行方式：python -m app.scripts.seed_courses
"""

import sys
import os

# 確保可以 import app 模組
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database import SessionLocal, init_db
from app.models.course import Course
from app.data.days_data import DAYS_DATA, DAY_0_TEACHING


def seed_courses(course_version: str = "v1", force: bool = False):
    """
    將課程資料寫入資料庫

    Args:
        course_version: 課程版本名稱
        force: 是否強制覆蓋已存在的資料
    """
    # 初始化資料庫
    init_db()

    db = SessionLocal()

    try:
        # 檢查是否已有該版本的課程
        existing = db.query(Course).filter(Course.course_version == course_version).first()
        if existing and not force:
            print(f"版本 {course_version} 的課程已存在，若要覆蓋請使用 --force 參數")
            return False

        # 如果 force 模式，先刪除舊資料
        if force and existing:
            db.query(Course).filter(Course.course_version == course_version).delete()
            db.commit()
            print(f"已刪除版本 {course_version} 的舊課程資料")

        # 寫入課程資料
        for day_data in DAYS_DATA:
            course = Course(
                course_version=course_version,
                day=day_data["day"],
                title=day_data["title"],
                goal=day_data.get("goal"),
                type="teaching" if day_data.get("type") == "teaching" else "assessment",
                opening_a=day_data.get("opening_a"),
                opening_b=day_data.get("opening_b"),
                criteria="\n".join(day_data.get("criteria", [])) if day_data.get("criteria") else None,
                min_rounds=day_data.get("min_rounds", 3),
                max_rounds=day_data.get("max_rounds", 5),
                teaching_content=day_data.get("teaching_content"),
                is_active=True,
                sort_order=day_data["day"]
            )
            db.add(course)
            print(f"  Day {day_data['day']}: {day_data['title']}")

        db.commit()
        print(f"\n成功匯入 {len(DAYS_DATA)} 個課程到版本 {course_version}")
        return True

    except Exception as e:
        db.rollback()
        print(f"匯入失敗: {e}")
        return False

    finally:
        db.close()


def list_courses():
    """列出資料庫中的所有課程"""
    db = SessionLocal()

    try:
        courses = db.query(Course).order_by(Course.course_version, Course.day).all()

        if not courses:
            print("資料庫中尚無課程資料")
            return

        current_version = None
        for course in courses:
            if course.course_version != current_version:
                current_version = course.course_version
                print(f"\n=== 版本 {current_version} ===")

            status = "啟用" if course.is_active else "停用"
            print(f"  Day {course.day}: {course.title} [{course.type}] ({status})")

    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="課程種子資料管理")
    parser.add_argument("action", choices=["seed", "list"], help="執行動作")
    parser.add_argument("--version", "-v", default="v1", help="課程版本 (預設: v1)")
    parser.add_argument("--force", "-f", action="store_true", help="強制覆蓋已存在的資料")

    args = parser.parse_args()

    if args.action == "seed":
        print(f"開始匯入課程資料到版本 {args.version}...")
        seed_courses(args.version, args.force)
    elif args.action == "list":
        list_courses()
