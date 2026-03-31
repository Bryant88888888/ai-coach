"""早會登記暨日報表服務"""
from datetime import date, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from collections import defaultdict

from app.models.user import User, UserStatus
from app.models.morning_report import MorningReport


class MorningReportService:
    """早會日報表服務"""

    def __init__(self, db: Session):
        self.db = db

    # ===== 組別管理 =====

    def get_all_leaders(self) -> list[User]:
        return self.db.query(User).filter(
            User.position == '組長',
            User.status == UserStatus.ACTIVE.value,
            User.real_name.isnot(None),
            User.real_name != "",
        ).order_by(User.real_name).all()

    def get_team_members(self, leader_id: int) -> list[User]:
        return self.db.query(User).filter(
            User.leader_id == leader_id,
            User.status == UserStatus.ACTIVE.value,
            User.real_name.isnot(None),
            User.real_name != "",
        ).order_by(User.real_name).all()

    def get_all_active_users(self) -> list[User]:
        return self.db.query(User).filter(
            User.status == UserStatus.ACTIVE.value,
            User.real_name.isnot(None),
            User.real_name != "",
        ).order_by(User.real_name).all()

    # ===== 日報表 CRUD =====

    def get_report(self, user_id: int, report_date: date) -> Optional[MorningReport]:
        return self.db.query(MorningReport).filter(
            MorningReport.user_id == user_id,
            MorningReport.report_date == report_date,
        ).first()

    def get_reports_by_date(self, report_date: date, leader_id: int = None) -> list[MorningReport]:
        query = self.db.query(MorningReport).filter(
            MorningReport.report_date == report_date,
        )
        if leader_id:
            query = query.filter(MorningReport.leader_id == leader_id)
        return query.order_by(MorningReport.created_at).all()

    def submit_report(self, user_id: int, report_date: date,
                      leader_id: int = None,
                      reviews: list[dict] = None,
                      shares: list[dict] = None) -> MorningReport:
        """新增或更新日報表"""
        report = self.get_report(user_id, report_date)

        if not report:
            report = MorningReport(
                user_id=user_id,
                report_date=report_date,
                leader_id=leader_id,
            )
            self.db.add(report)
        else:
            if leader_id is not None:
                report.leader_id = leader_id

        if reviews is not None:
            # 過濾空的檢討項目
            valid_reviews = [r for r in reviews if r.get("category") or r.get("description")]
            report.set_reviews(valid_reviews)

        if shares is not None:
            # 過濾空的分享項目
            valid_shares = [s for s in shares if s.get("category") or s.get("situation")]
            report.set_shares(valid_shares)

        self.db.commit()
        self.db.refresh(report)
        return report

    # ===== 統計 =====

    def get_attendance_stats(self, report_date: date, leader_id: int = None) -> dict:
        user_query = self.db.query(User).filter(
            User.status == UserStatus.ACTIVE.value,
            User.real_name.isnot(None),
            User.real_name != "",
        )
        if leader_id:
            user_query = user_query.filter(User.leader_id == leader_id)
        total_expected = user_query.count()

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
            "absent": max(0, total_expected - total_present),
            "rate": rate,
        }

    def get_monthly_stats(self, year: int, month: int, leader_id: int = None) -> dict:
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        start = date(year, month, 1)
        end = date(year, month, last_day)

        daily_stats = []
        total_expected = 0
        total_present = 0
        current = start
        while current <= end and current <= date.today():
            stats = self.get_attendance_stats(current, leader_id)
            if stats["expected"] > 0:
                daily_stats.append(stats)
                total_expected += stats["expected"]
                total_present += stats["present"]
            current += timedelta(days=1)

        avg_rate = round(total_present / total_expected * 100, 1) if total_expected > 0 else 0

        return {
            "year": year, "month": month,
            "daily_stats": daily_stats,
            "working_days": len(daily_stats),
            "total_expected": total_expected,
            "total_present": total_present,
            "avg_rate": avg_rate,
        }

    def get_review_stats(self, year: int, month: int, leader_id: int = None) -> list[dict]:
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        start = date(year, month, 1)
        end = date(year, month, last_day)

        query = self.db.query(MorningReport).filter(
            MorningReport.report_date >= start,
            MorningReport.report_date <= end,
            MorningReport.reviews.isnot(None),
            MorningReport.reviews != "",
            MorningReport.reviews != "[]",
        )
        if leader_id:
            query = query.filter(MorningReport.leader_id == leader_id)

        categories = defaultdict(lambda: {"total": 0, "resolved": 0, "in_progress": 0, "pending": 0})
        for report in query.all():
            for r in report.get_reviews():
                cat = r.get("category", "其他")
                if not cat:
                    continue
                categories[cat]["total"] += 1
                status = r.get("status", "未處理")
                if status == "已改善":
                    categories[cat]["resolved"] += 1
                elif status == "進行中":
                    categories[cat]["in_progress"] += 1
                else:
                    categories[cat]["pending"] += 1

        result = []
        for cat, stats in categories.items():
            rate = round(stats["resolved"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0
            result.append({"category": cat, **stats, "rate": rate})
        return result

    def get_share_stats(self, year: int, month: int, leader_id: int = None) -> list[dict]:
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        start = date(year, month, 1)
        end = date(year, month, last_day)

        query = self.db.query(MorningReport).filter(
            MorningReport.report_date >= start,
            MorningReport.report_date <= end,
            MorningReport.shares.isnot(None),
            MorningReport.shares != "",
            MorningReport.shares != "[]",
        )
        if leader_id:
            query = query.filter(MorningReport.leader_id == leader_id)

        categories = defaultdict(lambda: {"count": 0, "ratings": []})
        for report in query.all():
            for s in report.get_shares():
                cat = s.get("category", "其他")
                if not cat:
                    continue
                categories[cat]["count"] += 1
                rating = s.get("rating")
                if rating:
                    try:
                        categories[cat]["ratings"].append(int(rating))
                    except (ValueError, TypeError):
                        pass

        result = []
        for cat, stats in categories.items():
            ratings = stats["ratings"]
            avg = round(sum(ratings) / len(ratings), 1) if ratings else 0
            result.append({
                "category": cat, "count": stats["count"],
                "avg_rating": avg,
                "highest": max(ratings) if ratings else 0,
                "lowest": min(ratings) if ratings else 0,
            })
        return result
