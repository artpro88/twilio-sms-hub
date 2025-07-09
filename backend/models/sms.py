"""
Pydantic models for SMS application
"""

from pydantic import BaseModel, validator, Field
from typing import Optional, List
from datetime import datetime
import phonenumbers
import re

class SMSRequest(BaseModel):
    """Model for single SMS request"""
    to_number: str = Field(..., description="Recipient phone number")
    message_body: str = Field(..., max_length=1600, description="SMS message content")
    
    @validator('to_number')
    def validate_phone_number(cls, v):
        """Validate phone number format"""
        try:
            # Remove any non-digit characters except +
            cleaned = re.sub(r'[^\d+]', '', v)
            
            # Parse the phone number
            parsed = phonenumbers.parse(cleaned, None)
            
            # Check if it's valid
            if not phonenumbers.is_valid_number(parsed):
                raise ValueError("Invalid phone number")
                
            # Return in E164 format
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except Exception:
            raise ValueError("Invalid phone number format")
    
    @validator('message_body')
    def validate_message_body(cls, v):
        """Validate message content"""
        if not v.strip():
            raise ValueError("Message body cannot be empty")
        return v.strip()

class BulkSMSRequest(BaseModel):
    """Model for bulk SMS request"""
    message_template: str = Field(..., max_length=1600, description="SMS message template")
    
    @validator('message_template')
    def validate_message_template(cls, v):
        """Validate message template"""
        if not v.strip():
            raise ValueError("Message template cannot be empty")
        return v.strip()

class SMSResponse(BaseModel):
    """Model for SMS response"""
    success: bool
    message_sid: Optional[str] = None
    message: str
    cost: Optional[float] = None

class BulkSMSResponse(BaseModel):
    """Model for bulk SMS response"""
    success: bool
    job_id: str
    message: str
    total_count: int

class SMSStatus(BaseModel):
    """Model for SMS status"""
    id: int
    message_sid: str
    from_number: str
    to_number: str
    message_body: str
    status: str
    direction: str
    cost: Optional[float]
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

class BulkSMSJobStatus(BaseModel):
    """Model for bulk SMS job status"""
    id: int
    job_id: str
    filename: str
    total_count: int
    sent_count: int
    failed_count: int
    status: str
    message_template: str
    created_at: datetime
    completed_at: Optional[datetime]

class WebhookPayload(BaseModel):
    """Model for Twilio webhook payload"""
    MessageSid: str
    MessageStatus: Optional[str] = None
    From: Optional[str] = None
    To: Optional[str] = None
    Body: Optional[str] = None
    ErrorCode: Optional[str] = None
    ErrorMessage: Optional[str] = None

class SMSStats(BaseModel):
    """Model for SMS statistics"""
    total_sent: int
    total_delivered: int
    total_failed: int
    total_cost: float
    today_sent: int
    this_month_sent: int
