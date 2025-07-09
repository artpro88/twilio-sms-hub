"""
Database configuration and models for Twilio SMS application
"""

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sms_app.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class SMSMessage(Base):
    """Model for storing SMS messages"""
    __tablename__ = "sms_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    message_sid = Column(String(50), unique=True, index=True)  # Twilio message SID
    from_number = Column(String(20), nullable=False)
    to_number = Column(String(20), nullable=False)
    message_body = Column(Text, nullable=False)
    status = Column(String(20), default="queued")  # queued, sent, delivered, failed, etc.
    direction = Column(String(10), nullable=False)  # inbound or outbound
    cost = Column(Float, nullable=True)  # Cost in USD
    error_code = Column(String(10), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class BulkSMSJob(Base):
    """Model for tracking bulk SMS jobs"""
    __tablename__ = "bulk_sms_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(50), unique=True, index=True)
    filename = Column(String(255), nullable=False)
    total_count = Column(Integer, nullable=False)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    status = Column(String(20), default="pending")  # pending, processing, completed, failed
    message_template = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

class WebhookLog(Base):
    """Model for storing webhook logs"""
    __tablename__ = "webhook_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    message_sid = Column(String(50), index=True)
    webhook_type = Column(String(20), nullable=False)  # status_callback, incoming_message
    payload = Column(Text, nullable=False)  # JSON payload
    processed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

def create_tables():
    """Create all database tables"""
    Base.metadata.create_all(bind=engine)

def get_db():
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
