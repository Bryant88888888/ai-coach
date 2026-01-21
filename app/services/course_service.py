from sqlalchemy.orm import Session
from sqlalchemy import and_, func, Integer
from sqlalchemy.sql.expression import cast
from typing import Optional, List

from app.models.course import Course


class CourseService:
    """課程管理服務"""

    def __init__(self, db: Session):
        self.db = db

    # ========== 課程 CRUD ==========

    def create_course(
        self,
        day: int,
        title: str,
        course_version: str = "v1",
        goal: str = None,
        type: str = "assessment",
        opening_a: str = None,
        opening_b: str = None,
        criteria: str = None,
        min_rounds: int = 3,
        max_rounds: int = 5,
        teaching_content: str = None,
        lesson_content: str = None,
        system_prompt: str = None
    ) -> Course:
        """建立新課程"""
        course = Course(
            course_version=course_version,
            day=day,
            title=title,
            goal=goal,
            type=type,
            opening_a=opening_a,
            opening_b=opening_b,
            criteria=criteria,
            min_rounds=min_rounds,
            max_rounds=max_rounds,
            teaching_content=teaching_content,
            lesson_content=lesson_content,
            system_prompt=system_prompt,
            is_active=True
        )
        self.db.add(course)
        self.db.commit()
        self.db.refresh(course)
        return course

    def get_course(self, course_id: int) -> Optional[Course]:
        """取得指定課程"""
        return self.db.query(Course).filter(Course.id == course_id).first()

    def get_course_by_day(self, day: int, course_version: str = "v1") -> Optional[Course]:
        """取得指定版本的某天課程"""
        return self.db.query(Course).filter(
            and_(
                Course.course_version == course_version,
                Course.day == day,
                Course.is_active == True
            )
        ).first()

    def get_all_courses(self, course_version: str = None, active_only: bool = True) -> List[Course]:
        """取得所有課程"""
        query = self.db.query(Course)
        if course_version:
            query = query.filter(Course.course_version == course_version)
        if active_only:
            query = query.filter(Course.is_active == True)
        return query.order_by(Course.course_version, Course.day).all()

    def get_courses_by_version(self, course_version: str) -> List[Course]:
        """取得指定版本的所有課程"""
        return self.db.query(Course).filter(
            and_(
                Course.course_version == course_version,
                Course.is_active == True
            )
        ).order_by(Course.day).all()

    def get_course_versions(self) -> List[str]:
        """取得所有課程版本"""
        result = self.db.query(Course.course_version).distinct().all()
        return [r[0] for r in result]

    def update_course(
        self,
        course_id: int,
        **kwargs
    ) -> Optional[Course]:
        """更新課程"""
        course = self.get_course(course_id)
        if not course:
            return None

        for key, value in kwargs.items():
            if hasattr(course, key) and value is not None:
                setattr(course, key, value)

        self.db.commit()
        self.db.refresh(course)
        return course

    def delete_course(self, course_id: int) -> bool:
        """刪除課程（軟刪除）"""
        course = self.get_course(course_id)
        if course:
            course.is_active = False
            self.db.commit()
            return True
        return False

    def hard_delete_course(self, course_id: int) -> bool:
        """永久刪除課程"""
        course = self.get_course(course_id)
        if course:
            self.db.delete(course)
            self.db.commit()
            return True
        return False

    # ========== 版本管理 ==========

    def duplicate_version(self, from_version: str, to_version: str) -> List[Course]:
        """複製課程版本"""
        # 檢查目標版本是否已存在
        existing = self.db.query(Course).filter(Course.course_version == to_version).first()
        if existing:
            raise ValueError(f"版本 {to_version} 已存在")

        # 複製所有課程
        source_courses = self.get_courses_by_version(from_version)
        new_courses = []

        for course in source_courses:
            new_course = Course(
                course_version=to_version,
                day=course.day,
                title=course.title,
                goal=course.goal,
                type=course.type,
                opening_a=course.opening_a,
                opening_b=course.opening_b,
                criteria=course.criteria,
                min_rounds=course.min_rounds,
                max_rounds=course.max_rounds,
                teaching_content=course.teaching_content,
                lesson_content=course.lesson_content,
                system_prompt=course.system_prompt,
                is_active=True
            )
            self.db.add(new_course)
            new_courses.append(new_course)

        self.db.commit()
        return new_courses

    def get_version_stats(self) -> List[dict]:
        """取得各版本統計"""
        result = self.db.query(
            Course.course_version,
            func.count(Course.id).label('total'),
            func.sum(cast(Course.is_active, Integer)).label('active')
        ).group_by(Course.course_version).all()

        return [
            {
                "version": r[0],
                "total": r[1],
                "active": r[2] or 0
            }
            for r in result
        ]

    # ========== 課程資料轉換 ==========

    def get_day_data(self, day: int, course_version: str = "v1") -> Optional[dict]:
        """取得當日課程資料（相容舊格式）"""
        course = self.get_course_by_day(day, course_version)
        if course:
            return course.to_dict()
        return None

    def get_all_days(self, course_version: str = "v1") -> List[dict]:
        """取得所有課程資料（相容舊格式）"""
        courses = self.get_courses_by_version(course_version)
        return [{"day": c.day, "title": c.title} for c in courses]


# 為了向後相容，提供一個從資料庫或靜態資料取得課程的函數
def get_course_data(db: Session, day: int, course_version: str = "v1") -> Optional[dict]:
    """
    取得課程資料（優先從資料庫讀取，若無則從靜態資料讀取）
    """
    service = CourseService(db)
    course_data = service.get_day_data(day, course_version)

    if course_data:
        return course_data

    # 若資料庫沒有，嘗試從靜態資料讀取（向後相容）
    from app.data.days_data import get_day_data as get_static_day_data
    return get_static_day_data(day)
