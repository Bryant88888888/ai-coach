from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class Quiz(Base):
    """測驗（每日小測驗）"""
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    passing_score = Column(Integer, default=60)          # 通過最低分數 %
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Quiz(course_id={self.course_id}, title={self.title})>"


class QuizQuestion(Base):
    """測驗題目"""
    __tablename__ = "quiz_questions"

    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"), nullable=False, index=True)
    question_type = Column(String(20), default="multiple_choice")  # "multiple_choice"/"true_false"
    question_text = Column(Text, nullable=False)
    # JSON: [{"text": "選項A", "is_correct": true}, {"text": "選項B", "is_correct": false}, ...]
    options = Column(Text, nullable=False)
    explanation = Column(Text, nullable=True)            # 答題後的解說
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<QuizQuestion(quiz_id={self.quiz_id}, type={self.question_type})>"


class QuizAttempt(Base):
    """測驗作答紀錄"""
    __tablename__ = "quiz_attempts"

    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    score = Column(Integer, default=0)
    passed = Column(Boolean, default=False)
    answers = Column(Text, nullable=True)                # JSON: 使用者的答案
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<QuizAttempt(quiz_id={self.quiz_id}, user_id={self.user_id}, score={self.score})>"
