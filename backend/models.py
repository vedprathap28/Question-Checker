from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


# ============================================================
# 🟦 TOPIC MODEL
# ============================================================

class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

    # One topic → many questions
    questions = relationship("Question", back_populates="topic")

    # One topic → many assessment questions
    assessment_questions = relationship("AssessmentQuestion", back_populates="topic")


# ============================================================
# 🟦 MASTER QUESTION MODEL (Stored in Master DB)
# ============================================================

class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("topics.id"))
    marks = Column(Integer, index=True)
    question_text = Column(Text, index=True)

    topic = relationship("Topic", back_populates="questions")


# ============================================================
# 🟦 ASSESSMENT MODEL (Each imported assessment)
# ============================================================

class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

    # One assessment → many assessment questions
    questions = relationship("AssessmentQuestion", back_populates="assessment")


# ============================================================
# 🟦 ASSESSMENT QUESTIONS MODEL
# (Questions imported from a specific assessment)
# ============================================================

class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"

    id = Column(Integer, primary_key=True, index=True)

    assessment_id = Column(Integer, ForeignKey("assessments.id"))
    topic_id = Column(Integer, ForeignKey("topics.id"))

    marks = Column(Integer, index=True)
    question_text = Column(Text, index=True)

    # Relationships
    assessment = relationship("Assessment", back_populates="questions")
    topic = relationship("Topic", back_populates="assessment_questions")
