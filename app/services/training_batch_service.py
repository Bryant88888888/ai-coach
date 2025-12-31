from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime
from typing import Optional, List

from app.models.training_batch import TrainingBatch
from app.models.user_training import UserTraining, TrainingStatus
from app.models.user import User


class TrainingBatchService:
    """訓練批次管理服務"""

    def __init__(self, db: Session):
        self.db = db

    # ========== 批次管理 ==========

    def create_batch(
        self,
        name: str,
        description: str = None,
        course_version: str = "v1",
        total_days: int = 14
    ) -> TrainingBatch:
        """建立新的訓練批次"""
        batch = TrainingBatch(
            name=name,
            description=description,
            course_version=course_version,
            total_days=total_days,
            is_active=True
        )
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def get_batch(self, batch_id: int) -> Optional[TrainingBatch]:
        """取得指定批次"""
        return self.db.query(TrainingBatch).filter(TrainingBatch.id == batch_id).first()

    def get_all_batches(self, active_only: bool = False) -> List[TrainingBatch]:
        """取得所有批次"""
        query = self.db.query(TrainingBatch)
        if active_only:
            query = query.filter(TrainingBatch.is_active == True)
        return query.order_by(TrainingBatch.created_at.desc()).all()

    def update_batch(
        self,
        batch_id: int,
        name: str = None,
        description: str = None,
        is_active: bool = None
    ) -> Optional[TrainingBatch]:
        """更新批次資訊"""
        batch = self.get_batch(batch_id)
        if not batch:
            return None

        if name is not None:
            batch.name = name
        if description is not None:
            batch.description = description
        if is_active is not None:
            batch.is_active = is_active

        self.db.commit()
        self.db.refresh(batch)
        return batch

    def get_batch_stats(self, batch_id: int) -> dict:
        """取得批次統計資料"""
        batch = self.get_batch(batch_id)
        if not batch:
            return {}

        trainings = self.db.query(UserTraining).filter(
            UserTraining.batch_id == batch_id
        ).all()

        stats = {
            "total": len(trainings),
            "pending": 0,
            "active": 0,
            "paused": 0,
            "completed": 0
        }

        for t in trainings:
            if t.status == TrainingStatus.PENDING.value:
                stats["pending"] += 1
            elif t.status == TrainingStatus.ACTIVE.value:
                stats["active"] += 1
            elif t.status == TrainingStatus.PAUSED.value:
                stats["paused"] += 1
            elif t.status == TrainingStatus.COMPLETED.value:
                stats["completed"] += 1

        return stats

    # ========== 用戶訓練管理 ==========

    def add_user_to_batch(
        self,
        user_id: int,
        batch_id: int,
        auto_start: bool = False
    ) -> UserTraining:
        """將用戶加入訓練批次"""
        # 檢查是否已經在此批次中
        existing = self.db.query(UserTraining).filter(
            and_(
                UserTraining.user_id == user_id,
                UserTraining.batch_id == batch_id
            )
        ).first()

        if existing:
            return existing

        user_training = UserTraining(
            user_id=user_id,
            batch_id=batch_id,
            current_day=0,
            current_round=0,
            status=TrainingStatus.ACTIVE.value if auto_start else TrainingStatus.PENDING.value,
            started_at=datetime.now() if auto_start else None
        )
        self.db.add(user_training)
        self.db.commit()
        self.db.refresh(user_training)
        return user_training

    def get_user_training(self, user_id: int, batch_id: int) -> Optional[UserTraining]:
        """取得用戶在指定批次的訓練紀錄"""
        return self.db.query(UserTraining).filter(
            and_(
                UserTraining.user_id == user_id,
                UserTraining.batch_id == batch_id
            )
        ).first()

    def get_user_active_training(self, user_id: int) -> Optional[UserTraining]:
        """取得用戶目前進行中的訓練"""
        return self.db.query(UserTraining).filter(
            and_(
                UserTraining.user_id == user_id,
                UserTraining.status == TrainingStatus.ACTIVE.value
            )
        ).first()

    def get_all_active_trainings(self) -> List[UserTraining]:
        """取得所有進行中的訓練"""
        return self.db.query(UserTraining).filter(
            UserTraining.status == TrainingStatus.ACTIVE.value
        ).all()

    def start_training(self, user_training: UserTraining) -> UserTraining:
        """開始訓練"""
        # 如果用戶有其他進行中的訓練，先暫停
        other_active = self.db.query(UserTraining).filter(
            and_(
                UserTraining.user_id == user_training.user_id,
                UserTraining.id != user_training.id,
                UserTraining.status == TrainingStatus.ACTIVE.value
            )
        ).all()

        for other in other_active:
            other.status = TrainingStatus.PAUSED.value
            other.paused_at = datetime.now()

        # 開始此訓練
        user_training.status = TrainingStatus.ACTIVE.value
        user_training.started_at = user_training.started_at or datetime.now()
        user_training.paused_at = None

        self.db.commit()
        self.db.refresh(user_training)
        return user_training

    def pause_training(self, user_training: UserTraining) -> UserTraining:
        """暫停訓練"""
        user_training.status = TrainingStatus.PAUSED.value
        user_training.paused_at = datetime.now()

        self.db.commit()
        self.db.refresh(user_training)
        return user_training

    def resume_training(self, user_training: UserTraining) -> UserTraining:
        """恢復訓練"""
        return self.start_training(user_training)

    def restart_training(self, user_training: UserTraining) -> UserTraining:
        """重新開始訓練（重設進度）"""
        user_training.current_day = 0
        user_training.current_round = 0
        user_training.persona = None
        user_training.status = TrainingStatus.ACTIVE.value
        user_training.started_at = datetime.now()
        user_training.paused_at = None
        user_training.completed_at = None

        self.db.commit()
        self.db.refresh(user_training)
        return user_training

    def complete_training(self, user_training: UserTraining) -> UserTraining:
        """完成訓練"""
        user_training.status = TrainingStatus.COMPLETED.value
        user_training.completed_at = datetime.now()

        self.db.commit()
        self.db.refresh(user_training)
        return user_training

    def update_training_progress(
        self,
        user_training: UserTraining,
        current_day: int = None,
        current_round: int = None,
        persona: str = None
    ) -> UserTraining:
        """更新訓練進度"""
        if current_day is not None:
            user_training.current_day = current_day
        if current_round is not None:
            user_training.current_round = current_round
        if persona is not None:
            user_training.persona = persona

        self.db.commit()
        self.db.refresh(user_training)
        return user_training

    def get_batch_users(self, batch_id: int) -> List[UserTraining]:
        """取得批次中所有用戶的訓練紀錄"""
        return self.db.query(UserTraining).filter(
            UserTraining.batch_id == batch_id
        ).order_by(UserTraining.created_at.desc()).all()

    def remove_user_from_batch(self, user_id: int, batch_id: int) -> bool:
        """將用戶從批次中移除"""
        user_training = self.get_user_training(user_id, batch_id)
        if user_training:
            self.db.delete(user_training)
            self.db.commit()
            return True
        return False
