from datetime import date, datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from calendar import Calendar

from app.models.user import User, UserRole
from app.models.duty_config import DutyConfig
from app.models.duty_schedule import DutySchedule, DutyScheduleStatus
from app.models.duty_report import DutyReport, DutyReportStatus
from app.models.duty_complaint import DutyComplaint, DutyComplaintStatus


class DutyService:
    """值日生管理服務"""

    def __init__(self, db: Session):
        self.db = db

    # ===== 設定管理 =====

    def get_config(self, config_id: int = None) -> Optional[DutyConfig]:
        """取得排班設定（預設取第一個活躍的一般設定，排除駐店組長）"""
        if config_id:
            return self.db.query(DutyConfig).filter(DutyConfig.id == config_id).first()
        return self.db.query(DutyConfig).filter(
            DutyConfig.is_active == True,
            DutyConfig.name != '駐店組長'
        ).first()

    def get_all_configs(self) -> list[DutyConfig]:
        """取得所有排班設定"""
        return self.db.query(DutyConfig).order_by(DutyConfig.created_at.desc()).all()

    def create_config(
        self,
        name: str,
        members_per_day: int = 1,
        tasks: list[str] = None,
        notify_time: str = "08:00"
    ) -> DutyConfig:
        """建立排班設定"""
        config = DutyConfig(
            name=name,
            members_per_day=members_per_day,
            notify_time=notify_time
        )
        if tasks:
            config.set_tasks(tasks)
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_config(
        self,
        config_id: int,
        name: str = None,
        members_per_day: int = None,
        tasks: list[str] = None,
        notify_time: str = None,
        is_active: bool = None
    ) -> Optional[DutyConfig]:
        """更新排班設定"""
        config = self.get_config(config_id)
        if not config:
            return None

        if name is not None:
            config.name = name
        if members_per_day is not None:
            config.members_per_day = members_per_day
        if tasks is not None:
            config.set_tasks(tasks)
        if notify_time is not None:
            config.notify_time = notify_time
        if is_active is not None:
            config.is_active = is_active

        self.db.commit()
        return config

    # ===== 值日生名單管理 =====

    def get_duty_members(self) -> list[User]:
        """取得所有值日生（有 duty_member 角色且已填寫員工資料的用戶）"""
        return self.db.query(User).filter(
            User.roles.contains('"duty_member"'),
            User.real_name.isnot(None),
            User.real_name != ""
        ).order_by(User.real_name).all()

    def add_duty_member(self, user_id: int) -> Optional[User]:
        """將用戶設為值日生"""
        user = self.db.query(User).filter(User.id == user_id).first()
        if user and not user.has_role(UserRole.DUTY_MEMBER.value):
            user.add_role(UserRole.DUTY_MEMBER.value)
            self.db.commit()
        return user

    def remove_duty_member(self, user_id: int) -> Optional[User]:
        """移除用戶的值日生角色"""
        user = self.db.query(User).filter(User.id == user_id).first()
        if user and user.has_role(UserRole.DUTY_MEMBER.value):
            user.remove_role(UserRole.DUTY_MEMBER.value)
            self.db.commit()
        return user

    # ===== 組長名單管理 =====

    def get_leader_members(self) -> list[User]:
        """取得所有職位為「組長」且已填寫員工資料的用戶"""
        return self.db.query(User).filter(
            User.position == '組長',
            User.real_name.isnot(None),
            User.real_name != ""
        ).order_by(User.real_name).all()

    def get_or_create_leader_config(self) -> DutyConfig:
        """取得或建立「駐店組長」排班設定"""
        config = self.db.query(DutyConfig).filter(
            DutyConfig.name == '駐店組長'
        ).first()
        if not config:
            config = DutyConfig(
                name='駐店組長',
                members_per_day=1,
                notify_time='08:00',
                is_active=True
            )
            self.db.add(config)
            self.db.commit()
            self.db.refresh(config)
        return config

    def auto_generate_leader_schedule(
        self,
        start_date: date,
        end_date: date
    ) -> list[DutySchedule]:
        """
        自動生成駐店組長排班（輪替制）

        Args:
            start_date: 開始日期
            end_date: 結束日期

        Returns:
            生成的排班列表
        """
        config = self.get_or_create_leader_config()
        leader_members = self.get_leader_members()
        if not leader_members:
            raise ValueError("沒有職位為「組長」的員工可排班")

        schedules = []
        current_date = start_date
        member_index = 0

        while current_date <= end_date:
            # 跳過已有排班的日期
            existing = self.db.query(DutySchedule).filter(
                DutySchedule.config_id == config.id,
                DutySchedule.duty_date == current_date
            ).first()

            if not existing:
                for i in range(config.members_per_day):
                    member = leader_members[member_index % len(leader_members)]
                    schedule = DutySchedule(
                        config_id=config.id,
                        user_id=member.id,
                        duty_date=current_date
                    )
                    self.db.add(schedule)
                    schedules.append(schedule)
                    member_index += 1

            current_date += timedelta(days=1)

        self.db.commit()
        return schedules

    # ===== 排班管理 =====

    def auto_generate_schedule(
        self,
        config_id: int,
        start_date: date,
        end_date: date
    ) -> list[DutySchedule]:
        """
        自動生成排班（輪替制）

        Args:
            config_id: 排班設定 ID
            start_date: 開始日期
            end_date: 結束日期

        Returns:
            生成的排班列表
        """
        config = self.get_config(config_id)
        if not config:
            raise ValueError("找不到排班設定")

        duty_members = self.get_duty_members()
        if not duty_members:
            raise ValueError("沒有值日生可排班")

        schedules = []
        current_date = start_date
        member_index = 0

        while current_date <= end_date:
            # 跳過已有排班的日期
            existing = self.db.query(DutySchedule).filter(
                DutySchedule.config_id == config_id,
                DutySchedule.duty_date == current_date
            ).first()

            if not existing:
                # 為每天排 members_per_day 個人
                for i in range(config.members_per_day):
                    member = duty_members[member_index % len(duty_members)]
                    schedule = DutySchedule(
                        config_id=config_id,
                        user_id=member.id,
                        duty_date=current_date
                    )
                    self.db.add(schedule)
                    schedules.append(schedule)
                    member_index += 1

            current_date += timedelta(days=1)

        self.db.commit()
        return schedules

    def get_schedule_by_date(
        self,
        duty_date: date,
        config_id: int = None
    ) -> list[DutySchedule]:
        """取得指定日期的排班"""
        query = self.db.query(DutySchedule).filter(
            DutySchedule.duty_date == duty_date
        )
        if config_id:
            query = query.filter(DutySchedule.config_id == config_id)
        return query.all()

    def get_today_duty(self, config_id: int = None) -> list[DutySchedule]:
        """取得今日值日生"""
        return self.get_schedule_by_date(date.today(), config_id)

    def get_month_schedule(
        self,
        year: int,
        month: int,
        config_id: int = None
    ) -> dict:
        """
        取得月曆排班資料

        Returns:
            {
                "calendar": [[周日, 周一, ..., 周六], ...],
                "schedules": {日期: [排班列表], ...}
            }
        """
        # 使用 Calendar 實例，設定週日為一週的第一天（6 = Sunday）
        # 這樣不會影響全域設定，且閏年等邊界情況由 Python 標準庫處理
        sunday_first_cal = Calendar(firstweekday=6)
        cal = sunday_first_cal.monthdayscalendar(year, month)

        # 取得該月所有排班
        first_day = date(year, month, 1)
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)

        query = self.db.query(DutySchedule).filter(
            DutySchedule.duty_date >= first_day,
            DutySchedule.duty_date <= last_day
        )
        if config_id:
            query = query.filter(DutySchedule.config_id == config_id)

        schedules = query.all()

        # 按日期分組
        schedule_map = {}
        for schedule in schedules:
            day = schedule.duty_date.day
            if day not in schedule_map:
                schedule_map[day] = []
            schedule_map[day].append(schedule)

        return {
            "calendar": cal,
            "schedules": schedule_map,
            "year": year,
            "month": month
        }

    def update_schedule(
        self,
        schedule_id: int,
        user_id: int = None,
        duty_date: date = None,
        status: str = None
    ) -> Optional[DutySchedule]:
        """手動更新排班"""
        schedule = self.db.query(DutySchedule).filter(
            DutySchedule.id == schedule_id
        ).first()
        if not schedule:
            return None

        if user_id is not None:
            schedule.user_id = user_id
        if duty_date is not None:
            schedule.duty_date = duty_date
        if status is not None:
            schedule.status = status

        self.db.commit()
        self.db.refresh(schedule)
        return schedule

    def delete_schedule(self, schedule_id: int) -> bool:
        """刪除排班"""
        schedule = self.db.query(DutySchedule).filter(
            DutySchedule.id == schedule_id
        ).first()
        if schedule:
            self.db.delete(schedule)
            self.db.commit()
            return True
        return False

    def clear_schedules(
        self,
        start_date: date,
        end_date: date,
        config_id: int = None
    ) -> int:
        """
        清除指定日期範圍的排班

        Args:
            start_date: 開始日期
            end_date: 結束日期
            config_id: 排班設定 ID（可選，不指定則清除所有設定的排班）

        Returns:
            刪除的排班數量
        """
        query = self.db.query(DutySchedule).filter(
            DutySchedule.duty_date >= start_date,
            DutySchedule.duty_date <= end_date,
            # 只清除「已排班」狀態的，保留已回報/已審核的
            DutySchedule.status == DutyScheduleStatus.SCHEDULED.value
        )

        if config_id:
            query = query.filter(DutySchedule.config_id == config_id)

        count = query.count()
        query.delete(synchronize_session=False)
        self.db.commit()
        return count

    # ===== 回報管理 =====

    def submit_report(
        self,
        schedule_id: int,
        user_id: int,
        report_text: str = None,
        photo_urls: list[str] = None
    ) -> DutyReport:
        """提交值日回報"""
        # 檢查是否已有回報
        existing = self.db.query(DutyReport).filter(
            DutyReport.schedule_id == schedule_id
        ).first()
        if existing:
            raise ValueError("此排班已有回報記錄")

        report = DutyReport(
            schedule_id=schedule_id,
            user_id=user_id,
            report_text=report_text
        )
        if photo_urls:
            report.set_photo_urls(photo_urls)

        self.db.add(report)

        # 更新排班狀態
        schedule = self.db.query(DutySchedule).filter(
            DutySchedule.id == schedule_id
        ).first()
        if schedule:
            schedule.status = DutyScheduleStatus.REPORTED.value

        self.db.commit()
        self.db.refresh(report)
        return report

    def get_pending_reports(self) -> list[DutyReport]:
        """取得待審核回報"""
        return self.db.query(DutyReport).filter(
            DutyReport.status == DutyReportStatus.PENDING.value
        ).order_by(DutyReport.created_at.desc()).all()

    def get_report(self, report_id: int) -> Optional[DutyReport]:
        """取得回報詳情"""
        return self.db.query(DutyReport).filter(DutyReport.id == report_id).first()

    def review_report(
        self,
        report_id: int,
        reviewer_id: int,
        status: str,
        note: str = None
    ) -> Optional[DutyReport]:
        """審核回報"""
        report = self.get_report(report_id)
        if not report:
            return None

        report.status = status
        report.reviewer_id = reviewer_id
        report.reviewer_note = note
        report.reviewed_at = datetime.now()

        # 更新排班狀態
        if status == DutyReportStatus.APPROVED.value:
            report.schedule.status = DutyScheduleStatus.APPROVED.value
        elif status == DutyReportStatus.REJECTED.value:
            report.schedule.status = DutyScheduleStatus.REJECTED.value

        self.db.commit()
        return report

    # ===== 檢舉管理 =====

    def submit_complaint(
        self,
        schedule_id: int,
        reporter_id: int,
        reported_user_id: int,
        complaint_text: str,
        photo_urls: list[str] = None
    ) -> DutyComplaint:
        """提交檢舉"""
        complaint = DutyComplaint(
            schedule_id=schedule_id,
            reporter_id=reporter_id,
            reported_user_id=reported_user_id,
            complaint_text=complaint_text
        )
        if photo_urls:
            complaint.set_photo_urls(photo_urls)

        self.db.add(complaint)
        self.db.commit()
        self.db.refresh(complaint)
        return complaint

    def get_pending_complaints(self) -> list[DutyComplaint]:
        """取得待處理檢舉"""
        return self.db.query(DutyComplaint).filter(
            DutyComplaint.status == DutyComplaintStatus.PENDING.value
        ).order_by(DutyComplaint.created_at.desc()).all()

    def get_complaint(self, complaint_id: int) -> Optional[DutyComplaint]:
        """取得檢舉詳情"""
        return self.db.query(DutyComplaint).filter(
            DutyComplaint.id == complaint_id
        ).first()

    def handle_complaint(
        self,
        complaint_id: int,
        handler_id: int,
        status: str,
        note: str = None
    ) -> Optional[DutyComplaint]:
        """處理檢舉"""
        complaint = self.get_complaint(complaint_id)
        if not complaint:
            return None

        complaint.status = status
        complaint.handler_id = handler_id
        complaint.handler_note = note
        complaint.handled_at = datetime.now()

        self.db.commit()
        return complaint

    # ===== 統計 =====

    def get_duty_stats(self, config_id: int = None) -> dict:
        """取得值日統計"""
        query = self.db.query(DutySchedule)
        if config_id:
            query = query.filter(DutySchedule.config_id == config_id)

        schedules = query.all()

        stats = {
            "total": len(schedules),
            "scheduled": 0,
            "reported": 0,
            "approved": 0,
            "rejected": 0,
            "missed": 0
        }

        for schedule in schedules:
            status = schedule.status
            if status in stats:
                stats[status] += 1

        # 待審核回報數
        stats["pending_reports"] = self.db.query(DutyReport).filter(
            DutyReport.status == DutyReportStatus.PENDING.value
        ).count()

        # 待處理檢舉數
        stats["pending_complaints"] = self.db.query(DutyComplaint).filter(
            DutyComplaint.status == DutyComplaintStatus.PENDING.value
        ).count()

        return stats

    def get_user_duty_history(
        self,
        user_id: int,
        limit: int = 30
    ) -> list[DutySchedule]:
        """取得用戶的值日歷史"""
        return self.db.query(DutySchedule).filter(
            DutySchedule.user_id == user_id
        ).order_by(DutySchedule.duty_date.desc()).limit(limit).all()

    # ===== LINE 通知相關 =====

    def get_schedules_to_notify(self, notify_time: str = None) -> list[DutySchedule]:
        """取得需要發送提醒的排班"""
        today = date.today()

        query = self.db.query(DutySchedule).filter(
            DutySchedule.duty_date == today,
            DutySchedule.status == DutyScheduleStatus.SCHEDULED.value,
            DutySchedule.notified_at == None
        )

        if notify_time:
            # 只取指定時間設定的排班
            query = query.join(DutyConfig).filter(
                DutyConfig.notify_time == notify_time,
                DutyConfig.is_active == True
            )

        return query.all()

    def mark_as_notified(self, schedule_id: int) -> None:
        """標記為已發送提醒"""
        schedule = self.db.query(DutySchedule).filter(
            DutySchedule.id == schedule_id
        ).first()
        if schedule:
            schedule.notified_at = datetime.now()
            self.db.commit()

    def mark_missed_schedules(self) -> int:
        """標記過期未回報的排班為 missed"""
        yesterday = date.today() - timedelta(days=1)

        schedules = self.db.query(DutySchedule).filter(
            DutySchedule.duty_date < date.today(),
            DutySchedule.status == DutyScheduleStatus.SCHEDULED.value
        ).all()

        count = 0
        for schedule in schedules:
            schedule.status = DutyScheduleStatus.MISSED.value
            count += 1

        if count > 0:
            self.db.commit()

        return count
