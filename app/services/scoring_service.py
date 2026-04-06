"""評分結果管理服務"""

import json
from sqlalchemy.orm import Session
from app.models.scoring_result import ScoringResult
from app.models.scoring_rubric import ScoringRubric
from app.schemas.ai_response import DimensionalScore


class ScoringService:
    """評分結果管理"""

    def __init__(self, db: Session):
        self.db = db

    def create_scoring_result(
        self,
        message_id: int,
        user_id: int,
        training_day: int,
        dimensional_score: DimensionalScore,
        dimension_feedback: dict | None = None,
        summary: str = "",
        passing_score: int = 60,
    ) -> ScoringResult:
        """建立四面向評分結果"""
        total = dimensional_score.total
        passed = total >= passing_score
        grade = ScoringResult.calculate_grade(total)

        result = ScoringResult(
            message_id=message_id,
            user_id=user_id,
            training_day=training_day,
            process_completeness=dimensional_score.process_completeness,
            script_accuracy=dimensional_score.script_accuracy,
            emotional_control=dimensional_score.emotional_control,
            action_orientation=dimensional_score.action_orientation,
            total_score=total,
            dimension_feedback=json.dumps(dimension_feedback, ensure_ascii=False) if dimension_feedback else None,
            summary=summary,
            grade=grade,
            passed=passed,
        )
        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        return result

    def get_user_day_scores(self, user_id: int, training_day: int) -> list[ScoringResult]:
        """取得該天所有嘗試的分數"""
        return (
            self.db.query(ScoringResult)
            .filter(
                ScoringResult.user_id == user_id,
                ScoringResult.training_day == training_day,
            )
            .order_by(ScoringResult.created_at.desc())
            .all()
        )

    def get_user_best_scores(self, user_id: int) -> list[ScoringResult]:
        """取得每天最高分的評分結果"""
        from sqlalchemy import func
        subquery = (
            self.db.query(
                ScoringResult.training_day,
                func.max(ScoringResult.total_score).label("max_score"),
            )
            .filter(ScoringResult.user_id == user_id)
            .group_by(ScoringResult.training_day)
            .subquery()
        )

        return (
            self.db.query(ScoringResult)
            .join(
                subquery,
                (ScoringResult.training_day == subquery.c.training_day)
                & (ScoringResult.total_score == subquery.c.max_score),
            )
            .filter(ScoringResult.user_id == user_id)
            .order_by(ScoringResult.training_day)
            .all()
        )

    def get_user_progress_report(self, user_id: int) -> dict:
        """14 天整體進度報告"""
        best_scores = self.get_user_best_scores(user_id)

        if not best_scores:
            return {
                "total_days_completed": 0,
                "average_score": 0,
                "dimension_averages": {},
                "overall_grade": "D",
                "days": [],
            }

        total_score = sum(s.total_score for s in best_scores)
        avg_score = round(total_score / len(best_scores)) if best_scores else 0

        # 各維度平均
        dim_totals = {
            "process_completeness": 0,
            "script_accuracy": 0,
            "emotional_control": 0,
            "action_orientation": 0,
        }
        for s in best_scores:
            dim_totals["process_completeness"] += s.process_completeness
            dim_totals["script_accuracy"] += s.script_accuracy
            dim_totals["emotional_control"] += s.emotional_control
            dim_totals["action_orientation"] += s.action_orientation

        count = len(best_scores)
        dimension_averages = {k: round(v / count) for k, v in dim_totals.items()}

        return {
            "total_days_completed": len(best_scores),
            "average_score": avg_score,
            "dimension_averages": dimension_averages,
            "overall_grade": ScoringResult.calculate_grade(avg_score),
            "days": [
                {
                    "day": s.training_day,
                    "total_score": s.total_score,
                    "grade": s.grade,
                    "passed": s.passed,
                    "process_completeness": s.process_completeness,
                    "script_accuracy": s.script_accuracy,
                    "emotional_control": s.emotional_control,
                    "action_orientation": s.action_orientation,
                }
                for s in best_scores
            ],
        }

    def get_rubrics_for_course(self, course_id: int) -> list[ScoringRubric]:
        """取得課程的評分維度定義"""
        return (
            self.db.query(ScoringRubric)
            .filter(ScoringRubric.course_id == course_id)
            .order_by(ScoringRubric.sort_order)
            .all()
        )

    @staticmethod
    def calculate_grade(total_score: int) -> str:
        """根據總分計算等級"""
        return ScoringResult.calculate_grade(total_score)
