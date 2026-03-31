"""早會登記暨日報表服務"""
from datetime import date, datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func as sql_func
from collections import defaultdict

from app.models.user import User, UserStatus
from app.models.morning_report import MorningReport


class MorningReportService:
    """早會日報表服務"""

    def __init__(self, db: Session):
        self.db = db

    # ===== 組別管理 =====

    def get_all_leaders(self) -> list[User]:
        """取得所有組長（position='組長'且 Active）"""
        return self.db.query(User).filter(
            User.position == '組長',
            User.status == UserStatus.ACTIVE.value,
            User.real_name.isnot(None),
            User.real_name != "",
        ).order_by(User.real_name).all()

    def get_team_members(self, leader_id: int) -> list[User]:
        """取得指定組長的組員"""
        return self.db.query(User).filter(
            User.leader_id == leader_id,
            User.status == UserStatus.ACTIVE.value,
            User.real_name.isnot(None),
            User.real_name != "",
        ).order_by(User.real_name).all()

    def get_all_active_users(self) -> list[User]:
        """取得所有活躍且已註冊的員工"""
        return self.db.query(User).filter(
            User.status == UserStatus.ACTIVE.value,
            User.real_name.isnot(None),
            User.real_name != "",
        ).order_by(User.real_name).all()

    # ===== 日報表 CRUD =====

    def get_report(self, user_id: int, report_date: date) -> Optional[MorningReport]:
        """取得某人某天的報表"""
        return self.db.query(MorningReport).filter(
            MorningReport.user_id == user_id,
            MorningReport.report_date == report_date,
        ).first()

    def get_reports_by_date(self, report_date: date, leader_id: int = None) -> list[MorningReport]:
        """按日期取得報表（可按組別篩選）"""
        query = self.db.query(MorningReport).filter(
            MorningReport.report_date == report_date,
        )
        if leader_id:
            query = query.filter(MorningReport.leader_id == leader_id)
        return query.order_by(MorningReport.created_at).all()

    def submit_report(self, user_id: int, report_date: date, data: dict) -> MorningReport:
        """新增或更新日報表"""
        report = self.get_report(user_id, report_date)

        if not report:
            report = MorningReport(
                user_id=user_id,
                report_date=report_date,
            )
            self.db.add(report)

        # 更新欄位（包含 leader_id）
        for key, value in data.items():
            if hasattr(report, key) and key not in ('id', 'user_id', 'report_date', 'created_at'):
                setattr(report, key, value if value != '' else None)

        self.db.commit()
        self.db.refresh(report)
        return report

    # ===== 統計 =====

    def get_attendance_stats(self, report_date: date, leader_id: int = None) -> dict:
        """取得某天的出勤統計"""
        # 應到人數（該組或全部活躍員工）
        user_query = self.db.query(User).filter(
            User.status == UserStatus.ACTIVE.value,
            User.real_name.isnot(None),
            User.real_name != "",
        )
        if leader_id:
            user_query = user_query.filter(User.leader_id == leader_id)
        total_expected = user_query.count()

        # 實到人數（有填報表的人）
        report_query = self.db.query(MorningReport).filter(
            MorningReport.report_date == report_date,
        )
        if leader_id:
            report_query = report_query.filter(MorningReport.leader_id == leader_id)
        total_present = report_query.count()

        rate = round(total_present / total_expected * 100, 1) if total_expected > 0 else 0

        return {
            "date": report_date.isoformat(),
            "expected": total_expected,
            "present": total_present,
            "absent": total_expected - total_present,
            "rate": rate,
        }

    def get_monthly_stats(self, year: int, month: int, leader_id: int = None) -> dict:
        """取得月度統計"""
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        start = date(year, month, 1)
        end = date(year, month, last_day)

        # 每日統計
        daily_stats = []
        current = start
        total_expected = 0
        total_present = 0
        from datetime import timedelta
        while current <= end and current <= date.today():
            stats = self.get_attendance_stats(current, leader_id)
            if stats["expected"] > 0:
                daily_stats.append(stats)
                total_expected += stats["expected"]
                total_present += stats["present"]
            current += timedelta(days=1)

        avg_rate = round(total_present / total_expected * 100, 1) if total_expected > 0 else 0
        working_days = len(daily_stats)

        return {
            "year": year,
            "month": month,
            "daily_stats": daily_stats,
            "working_days": working_days,
            "total_expected": total_expected,
            "total_present": total_present,
            "avg_rate": avg_rate,
        }

    def get_review_stats(self, year: int, month: int, leader_id: int = None) -> list[dict]:
        """取得問題檢討統計"""
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        start = date(year, month, 1)
        end = date(year, month, last_day)

        query = self.db.query(MorningReport).filter(
            MorningReport.report_date >= start,
            MorningReport.report_date <= end,
            MorningReport.review_category.isnot(None),
            MorningReport.review_category != "",
        )
        if leader_id:
            query = query.filter(MorningReport.leader_id == leader_id)
        reports = query.all()

        categories = defaultdict(lambda: {"total": 0, "resolved": 0, "in_progress": 0, "pending": 0})
        for r in reports:
            cat = r.review_category
            categories[cat]["total"] += 1
            if r.review_status == "已改善":
                categories[cat]["resolved"] += 1
            elif r.review_status == "進行中":
                categories[cat]["in_progress"] += 1
            else:
                categories[cat]["pending"] += 1

        result = []
        for cat, stats in categories.items():
            rate = round(stats["resolved"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0
            result.append({"category": cat, **stats, "rate": rate})
        return result

    def get_share_stats(self, year: int, month: int, leader_id: int = None) -> list[dict]:
        """取得經驗分享統計"""
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        start = date(year, month, 1)
        end = date(year, month, last_day)

        query = self.db.query(MorningReport).filter(
            MorningReport.report_date >= start,
            MorningReport.report_date <= end,
            MorningReport.share_category.isnot(None),
            MorningReport.share_category != "",
        )
        if leader_id:
            query = query.filter(MorningReport.leader_id == leader_id)
        reports = query.all()

        categories = defaultdict(lambda: {"count": 0, "ratings": []})
        for r in reports:
            cat = r.share_category
            categories[cat]["count"] += 1
            if r.share_rating:
                categories[cat]["ratings"].append(r.share_rating)

        result = []
        for cat, stats in categories.items():
            ratings = stats["ratings"]
            avg = round(sum(ratings) / len(ratings), 1) if ratings else 0
            highest = max(ratings) if ratings else 0
            lowest = min(ratings) if ratings else 0
            result.append({
                "category": cat,
                "count": stats["count"],
                "avg_rating": avg,
                "highest": highest,
                "lowest": lowest,
            })
        return result
