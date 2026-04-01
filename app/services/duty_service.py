from datetime import date, datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from calendar import Calendar

from app.models.user import User, UserRole, UserStatus
from app.models.duty_config import DutyConfig
from app.models.duty_schedule import DutySchedule, DutyScheduleStatus
from app.models.duty_report import DutyReport, DutyReportStatus
from app.models.duty_complaint import DutyComplaint, DutyComplaintStatus
from app.models.duty_rule import DutyRule
from app.models.duty_swap import DutySwap, DutySwapStatus


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
        自動生成駐店組長排班（按規則制：依星期幾指定人員）

        Args:
            start_date: 開始日期
            end_date: 結束日期

        Returns:
            生成的排班列表
        """
        config = self.get_or_create_leader_config()

        # 取得組長排班規則 {weekday: [user_id, ...]}
        rules = self.db.query(DutyRule).filter(
            DutyRule.rule_type == 'leader'
        ).all()
        rule_map = {}
        for rule in rules:
            rule_map.setdefault(rule.weekday, []).append(rule.user_id)

        if not rule_map:
            raise ValueError("尚未設定組長排班規則，請先到排班設定頁面設定每日組長")

        schedules = []
        current_date = start_date

        while current_date <= end_date:
            weekday = current_date.weekday()  # 0=Monday ~ 6=Sunday

            # 該天有規則才排班
            if weekday in rule_map:
                # 跳過已有排班的日期
                existing = self.db.query(DutySchedule).filter(
                    DutySchedule.config_id == config.id,
                    DutySchedule.duty_date == current_date
                ).first()

                if not existing:
                    for uid in rule_map[weekday]:
                        schedule = DutySchedule(
                            config_id=config.id,
                            user_id=uid,
                            duty_date=current_date
                        )
                        self.db.add(schedule)
                        schedules.append(schedule)

            current_date += timedelta(days=1)

        self.db.commit()
        return schedules

    # ===== 店家管理 =====

    def get_store_configs(self) -> list[DutyConfig]:
        """取得所有店家設定（排除「駐店組長」）"""
        return self.db.query(DutyConfig).filter(
            DutyConfig.name != '駐店組長'
        ).order_by(DutyConfig.created_at).all()

    def create_store_config(self, name: str) -> DutyConfig:
        """建立新店家"""
        config = DutyConfig(
            name=name,
            members_per_day=1,
            notify_time='08:00',
            is_active=True
        )
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def delete_store_config(self, config_id: int) -> bool:
        """刪除店家及其排班規則"""
        config = self.db.query(DutyConfig).filter(
            DutyConfig.id == config_id,
            DutyConfig.name != '駐店組長'
        ).first()
        if not config:
            return False
        # 刪除該店家的規則
        self.db.query(DutyRule).filter(
            DutyRule.config_id == config_id
        ).delete(synchronize_session=False)
        self.db.delete(config)
        self.db.commit()
        return True

    # ===== 排班規則管理 =====

    def get_rules(self, rule_type: str, config_id: int = None) -> dict:
        """取得指定類型所有規則，回傳 {weekday: [user, ...]} 的 dict"""
        query = self.db.query(DutyRule).filter(
            DutyRule.rule_type == rule_type
        )
        if config_id is not None:
            query = query.filter(DutyRule.config_id == config_id)
        else:
            query = query.filter(DutyRule.config_id.is_(None))
        rules = query.all()
        result = {}
        for rule in rules:
            result.setdefault(rule.weekday, []).append(rule.user)
        return result

    def save_rules(self, rule_type: str, weekday_user_map: dict, config_id: int = None) -> None:
        """整批儲存規則（刪除舊規則 + 新增），每個 weekday 對應一個 user_id 列表"""
        query = self.db.query(DutyRule).filter(
            DutyRule.rule_type == rule_type
        )
        if config_id is not None:
            query = query.filter(DutyRule.config_id == config_id)
        else:
            query = query.filter(DutyRule.config_id.is_(None))
        query.delete(synchronize_session=False)

        for weekday, user_ids in weekday_user_map.items():
            if not user_ids:
                continue
            if not isinstance(user_ids, list):
                user_ids = [user_ids]
            for uid in user_ids:
                if uid:
                    rule = DutyRule(
                        rule_type=rule_type,
                        weekday=int(weekday),
                        user_id=int(uid),
                        config_id=config_id
                    )
                    self.db.add(rule)

        self.db.commit()

    def get_eligible_users(self, rule_type: str) -> list[User]:
        """取得可選人員（Active 且有 real_name）"""
        query = self.db.query(User).filter(
            User.status == UserStatus.ACTIVE.value,
            User.real_name.isnot(None),
            User.real_name != ""
        )
        if rule_type == 'leader':
            query = query.filter(User.position == '組長')
        return query.order_by(User.real_name).all()

    # ===== 排班管理 =====

    def auto_generate_schedule(
        self,
        config_id: int,
        start_date: date,
        end_date: date
    ) -> list[DutySchedule]:
        """
        自動生成排班（按規則制：依星期幾指定人員）

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

        # 取得值日生排班規則 {weekday: [user_id, ...]}（按 config_id 篩選）
        rule_query = self.db.query(DutyRule).filter(
            DutyRule.rule_type == 'duty'
        )
        if config_id:
            rule_query = rule_query.filter(DutyRule.config_id == config_id)
        else:
            rule_query = rule_query.filter(DutyRule.config_id.is_(None))
        rules = rule_query.all()
        rule_map = {}
        for rule in rules:
            rule_map.setdefault(rule.weekday, []).append(rule.user_id)

        if not rule_map:
            raise ValueError("尚未設定值日生排班規則，請先到排班設定頁面設定每日值日生")

        schedules = []
        current_date = start_date

        while current_date <= end_date:
            weekday = current_date.weekday()  # 0=Monday ~ 6=Sunday

            # 該天有規則才排班
            if weekday in rule_map:
                # 查詢該日期已存在排班的 user_id 集合
                existing_user_ids = set(
                    uid for (uid,) in self.db.query(DutySchedule.user_id).filter(
                        DutySchedule.config_id == config_id,
                        DutySchedule.duty_date == current_date
                    ).all()
                )

                # 只為規則中有但尚未排班的人員新增排班
                for uid in rule_map[weekday]:
                    if uid not in existing_user_ids:
                        schedule = DutySchedule(
                            config_id=config_id,
                            user_id=uid,
                            duty_date=current_date
                        )
                        self.db.add(schedule)
                        schedules.append(schedule)

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

    # ===== 換班申請管理 =====

    def create_swap_request(
        self,
        requester_id: int,
        schedule_id: int,
        target_user_id: int,
        reason: str = None
    ) -> dict:
        """
        建立換班申請

        Returns:
            {"success": True, "swap": DutySwap} 或 {"success": False, "error": str, "conflict": bool}
        """
        # 驗證排班存在且屬於申請者、狀態為 SCHEDULED
        schedule = self.db.query(DutySchedule).filter(
            DutySchedule.id == schedule_id,
            DutySchedule.user_id == requester_id,
            DutySchedule.status == DutyScheduleStatus.SCHEDULED.value
        ).first()
        if not schedule:
            return {"success": False, "error": "找不到該排班或無法換班"}

        # 驗證排班日期在未來
        if schedule.duty_date <= date.today():
            return {"success": False, "error": "只能申請未來日期的換班"}

        # 驗證對方存在
        target_user = self.db.query(User).filter(User.id == target_user_id).first()
        if not target_user:
            return {"success": False, "error": "找不到換班對象"}

        # 不能跟自己換
        if requester_id == target_user_id:
            return {"success": False, "error": "不能跟自己換班"}

        # 檢查是否已有相同的 pending 申請
        existing = self.db.query(DutySwap).filter(
            DutySwap.schedule_id == schedule_id,
            DutySwap.target_user_id == target_user_id,
            DutySwap.status == DutySwapStatus.PENDING.value
        ).first()
        if existing:
            return {"success": False, "error": "已有相同的換班申請正在等待審核"}

        # 檢查衝突：對方當天是否已有排班
        conflict = self.check_swap_conflict(target_user_id, schedule.duty_date, schedule.config_id)

        # 建立換班申請
        swap = DutySwap(
            requester_id=requester_id,
            target_user_id=target_user_id,
            schedule_id=schedule_id,
            reason=reason,
            status=DutySwapStatus.PENDING.value
        )
        self.db.add(swap)
        self.db.commit()
        self.db.refresh(swap)

        # 發送 LINE 通知給對方
        self._notify_swap_request(swap, schedule)

        return {"success": True, "swap": swap, "conflict": conflict}

    def respond_swap(
        self,
        swap_id: int,
        responder_id: int,
        approved: bool,
        note: str = None
    ) -> dict:
        """
        對方回應換班申請（同意/拒絕）

        Returns:
            {"success": True, "swap": DutySwap} 或 {"success": False, "error": str}
        """
        swap = self.db.query(DutySwap).filter(DutySwap.id == swap_id).first()
        if not swap:
            return {"success": False, "error": "找不到該換班申請"}

        if swap.status != DutySwapStatus.PENDING.value:
            return {"success": False, "error": f"該申請已{swap.status_display}，無法操作"}

        if swap.target_user_id != responder_id:
            return {"success": False, "error": "只有被請求的對象才能回應"}

        # 驗證排班仍然有效
        schedule = self.db.query(DutySchedule).filter(
            DutySchedule.id == swap.schedule_id
        ).first()
        if not schedule:
            return {"success": False, "error": "原排班已不存在"}

        if approved:
            # 驗證排班仍屬於申請者且狀態為 SCHEDULED
            if schedule.user_id != swap.requester_id:
                return {"success": False, "error": "原排班已被變更，無法換班"}
            if schedule.status != DutyScheduleStatus.SCHEDULED.value:
                return {"success": False, "error": "原排班狀態已變更，無法換班"}

            # 執行換班：將排班的 user_id 改為對方
            schedule.user_id = swap.target_user_id
            swap.status = DutySwapStatus.APPROVED.value
        else:
            swap.status = DutySwapStatus.REJECTED.value

        swap.responded_at = datetime.now()
        swap.response_note = note
        self.db.commit()
        self.db.refresh(swap)

        # 發送 LINE 通知給申請者
        self._notify_swap_response(swap, schedule)

        return {"success": True, "swap": swap}

    def cancel_swap(self, swap_id: int, requester_id: int) -> dict:
        """申請者取消待審核的換班申請"""
        swap = self.db.query(DutySwap).filter(DutySwap.id == swap_id).first()
        if not swap:
            return {"success": False, "error": "找不到該換班申請"}

        if swap.requester_id != requester_id:
            return {"success": False, "error": "只有申請者才能取消"}

        if swap.status != DutySwapStatus.PENDING.value:
            return {"success": False, "error": f"該申請已{swap.status_display}，無法取消"}

        swap.status = DutySwapStatus.CANCELLED.value
        swap.responded_at = datetime.now()
        self.db.commit()
        self.db.refresh(swap)

        # 通知對方申請已取消
        self._notify_swap_cancelled(swap)

        return {"success": True, "swap": swap}

    def get_pending_swaps_for_user(self, user_id: int) -> list[DutySwap]:
        """取得某用戶待回應的換班申請（別人申請換給我的）"""
        return self.db.query(DutySwap).filter(
            DutySwap.target_user_id == user_id,
            DutySwap.status == DutySwapStatus.PENDING.value
        ).order_by(DutySwap.created_at.desc()).all()

    def get_my_swap_requests(self, user_id: int) -> list[DutySwap]:
        """取得我發起的所有換班申請"""
        return self.db.query(DutySwap).filter(
            DutySwap.requester_id == user_id
        ).order_by(DutySwap.created_at.desc()).all()

    def get_swap_by_id(self, swap_id: int) -> Optional[DutySwap]:
        """取得單一換班申請"""
        return self.db.query(DutySwap).filter(DutySwap.id == swap_id).first()

    def get_all_swaps(self, status: str = None) -> list[DutySwap]:
        """取得所有換班申請（後台管理用）"""
        query = self.db.query(DutySwap)
        if status:
            query = query.filter(DutySwap.status == status)
        return query.order_by(DutySwap.created_at.desc()).all()

    def admin_force_swap(self, swap_id: int, approved: bool, note: str = None) -> dict:
        """管理員強制核准/拒絕換班申請"""
        swap = self.db.query(DutySwap).filter(DutySwap.id == swap_id).first()
        if not swap:
            return {"success": False, "error": "找不到該換班申請"}

        if swap.status != DutySwapStatus.PENDING.value:
            return {"success": False, "error": f"該申請已{swap.status_display}，無法操作"}

        schedule = self.db.query(DutySchedule).filter(
            DutySchedule.id == swap.schedule_id
        ).first()
        if not schedule:
            return {"success": False, "error": "原排班已不存在"}

        if approved:
            if schedule.status != DutyScheduleStatus.SCHEDULED.value:
                return {"success": False, "error": "原排班狀態已變更，無法換班"}
            schedule.user_id = swap.target_user_id
            swap.status = DutySwapStatus.APPROVED.value
        else:
            swap.status = DutySwapStatus.REJECTED.value

        swap.responded_at = datetime.now()
        swap.response_note = note or "（管理員操作）"
        self.db.commit()
        self.db.refresh(swap)

        # 通知雙方
        self._notify_swap_response(swap, schedule)

        return {"success": True, "swap": swap}

    def check_swap_conflict(self, target_user_id: int, duty_date: date, config_id: int) -> bool:
        """檢查對方當天是否已有排班（衝突檢查）"""
        existing = self.db.query(DutySchedule).filter(
            DutySchedule.user_id == target_user_id,
            DutySchedule.duty_date == duty_date,
            DutySchedule.config_id == config_id,
            DutySchedule.status == DutyScheduleStatus.SCHEDULED.value
        ).first()
        return existing is not None

    def get_user_swap_history(self, user_id: int) -> list[DutySwap]:
        """取得用戶相關的換班歷史（發起的 + 收到的）"""
        return self.db.query(DutySwap).filter(
            (DutySwap.requester_id == user_id) | (DutySwap.target_user_id == user_id)
        ).order_by(DutySwap.created_at.desc()).all()

    # ===== 換班 LINE 通知 =====

    def _get_push_service(self):
        """取得 LINE 推送服務"""
        try:
            from linebot.v3.messaging import (
                Configuration, ApiClient, MessagingApi,
                PushMessageRequest, TextMessage,
            )
            from app.config import get_settings
            settings = get_settings()
            config = Configuration(access_token=settings.line_channel_access_token)
            return config, settings
        except Exception:
            return None, None

    def _send_line_message(self, line_user_id: str, message: str) -> None:
        """發送 LINE 推送訊息"""
        try:
            from linebot.v3.messaging import (
                Configuration, ApiClient, MessagingApi,
                PushMessageRequest, TextMessage,
            )
            config, settings = self._get_push_service()
            if not config or not line_user_id:
                return
            with ApiClient(config) as api_client:
                messaging_api = MessagingApi(api_client)
                messaging_api.push_message(
                    PushMessageRequest(
                        to=line_user_id,
                        messages=[TextMessage(text=message)]
                    )
                )
        except Exception as e:
            print(f"LINE 通知發送失敗: {e}")

    def _notify_swap_request(self, swap: DutySwap, schedule: DutySchedule) -> None:
        """通知對方有新的換班申請"""
        requester = self.db.query(User).filter(User.id == swap.requester_id).first()
        target = self.db.query(User).filter(User.id == swap.target_user_id).first()
        if not requester or not target or not target.line_user_id:
            return

        requester_name = requester.real_name or requester.display_name or "同事"
        weekday_names = ['一', '二', '三', '四', '五', '六', '日']
        weekday = f"星期{weekday_names[schedule.duty_date.weekday()]}"
        date_str = schedule.duty_date.strftime("%m/%d")

        reason_text = f"\n原因：{swap.reason}" if swap.reason else ""

        try:
            from app.config import get_settings
            settings = get_settings()
            liff_id = (settings.liff_id_duty or "") if settings else ""
            respond_url = f"https://liff.line.me/{liff_id}/duty/my/swap/respond?swap_id={swap.id}" if liff_id else ""
            link_text = f"\n\n👉 點擊查看並回應：\n{respond_url}" if respond_url else ""
        except Exception:
            link_text = ""

        message = (
            f"📋 換班申請通知\n\n"
            f"{requester_name} 申請將 {date_str}（{weekday}）的值日班換給你。{reason_text}"
            f"{link_text}"
        )
        self._send_line_message(target.line_user_id, message)

    def _notify_swap_response(self, swap: DutySwap, schedule: DutySchedule) -> None:
        """通知申請者換班結果"""
        requester = self.db.query(User).filter(User.id == swap.requester_id).first()
        target = self.db.query(User).filter(User.id == swap.target_user_id).first()
        if not requester or not target or not requester.line_user_id:
            return

        target_name = target.real_name or target.display_name or "對方"
        weekday_names = ['一', '二', '三', '四', '五', '六', '日']
        weekday = f"星期{weekday_names[schedule.duty_date.weekday()]}"
        date_str = schedule.duty_date.strftime("%m/%d")

        if swap.status == DutySwapStatus.APPROVED.value:
            note_text = f"\n備註：{swap.response_note}" if swap.response_note and swap.response_note != "（管理員操作）" else ""
            message = (
                f"✅ 換班申請已通過\n\n"
                f"{target_name} 已同意你 {date_str}（{weekday}）的換班申請。\n"
                f"該日值日已更新為 {target_name}。{note_text}"
            )
        else:
            note_text = f"\n拒絕原因：{swap.response_note}" if swap.response_note else ""
            message = (
                f"❌ 換班申請已拒絕\n\n"
                f"{target_name} 已拒絕你 {date_str}（{weekday}）的換班申請。{note_text}"
            )
        self._send_line_message(requester.line_user_id, message)

    def _notify_swap_cancelled(self, swap: DutySwap) -> None:
        """通知對方換班申請已取消"""
        requester = self.db.query(User).filter(User.id == swap.requester_id).first()
        target = self.db.query(User).filter(User.id == swap.target_user_id).first()
        if not requester or not target or not target.line_user_id:
            return

        schedule = self.db.query(DutySchedule).filter(
            DutySchedule.id == swap.schedule_id
        ).first()
        if not schedule:
            return

        requester_name = requester.real_name or requester.display_name or "同事"
        date_str = schedule.duty_date.strftime("%m/%d")

        message = (
            f"📋 換班申請已取消\n\n"
            f"{requester_name} 已取消 {date_str} 的換班申請。"
        )
        self._send_line_message(target.line_user_id, message)
