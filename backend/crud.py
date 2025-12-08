from sqlalchemy.orm import Session, joinedload

import models
from models import Topic, Question, Assessment, AssessmentQuestion
from utils import normalize


def get_or_create_topic(db: Session, topic_name: str):
    topic_name = (topic_name or "").strip()
    topic = db.query(Topic).filter(Topic.name == topic_name).first()
    if not topic:
        topic = Topic(name=topic_name)
        db.add(topic)
        db.commit()
        db.refresh(topic)
    return topic


def add_question_if_not_exists(db: Session, topic_id: int, marks: int, question_text: str):
    normalized = normalize(question_text)
    existing = db.query(Question).filter(
        Question.topic_id == topic_id,
        Question.marks == marks,
        Question.question_text == normalized
    ).first()

    if existing:
        return existing, False

    new_q = Question(topic_id=topic_id, marks=marks, question_text=normalized)
    db.add(new_q)
    db.commit()
    db.refresh(new_q)
    return new_q, True


def create_assessment(db: Session, name: str):
    name = (name or "").strip()
    assessment = db.query(Assessment).filter(Assessment.name == name).first()
    if assessment:
        return assessment
    assessment = Assessment(name=name)
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment


def add_assessment_question(db: Session, assessment_id: int, topic_id: int, marks: int, question_text: str):
    norm = normalize(question_text)

    existing = (
        db.query(AssessmentQuestion)
        .filter(
            AssessmentQuestion.assessment_id == assessment_id,
            AssessmentQuestion.topic_id == topic_id,
            AssessmentQuestion.marks == marks,
            AssessmentQuestion.question_text == norm,
        )
        .first()
    )

    if existing:
        return existing, False

    aq = AssessmentQuestion(
        assessment_id=assessment_id,
        topic_id=topic_id,
        marks=marks,
        question_text=norm,
    )
    db.add(aq)
    db.commit()
    db.refresh(aq)
    return aq, True


def get_all_previous_questions(db: Session):
    records = db.query(AssessmentQuestion).all()
    return [r.question_text for r in records]


def get_all_previous_questions_with_assessment(db: Session):
    """
    Returns list of tuples: (question_text, assessment_name)
    """
    rows = (
        db.query(AssessmentQuestion.question_text, Assessment.name)
        .join(Assessment, Assessment.id == AssessmentQuestion.assessment_id)
        .all()
    )
    return [(q, a) for (q, a) in rows]


def get_all_assessments(db: Session):
    return db.query(Assessment).order_by(Assessment.id.desc()).all()


def get_assessment_by_id(db: Session, assessment_id: int):
    return db.query(Assessment).filter(Assessment.id == assessment_id).first()


def get_questions_by_assessment(db: Session, assessment_id: int):
    return (
        db.query(AssessmentQuestion)
        .options(joinedload(AssessmentQuestion.topic))
        .filter(AssessmentQuestion.assessment_id == assessment_id)
        .all()
    )


def delete_assessment(db: Session, assessment_id: int):
    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        return False

    db.delete(assessment)
    db.commit()
    return True
