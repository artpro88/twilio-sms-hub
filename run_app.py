#!/usr/bin/env python3
"""
Direct runner for Twilio SMS Integration
This file can be run directly without import issues
"""

import os
import sys
import uuid
import logging
import re
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

# Add backend directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

# Import modules
from database import create_tables, get_db, SMSMessage, BulkSMSJob, WebhookLog
from models.sms import (
    SMSRequest, SMSResponse, BulkSMSRequest, BulkSMSResponse,
    SMSStatus, BulkSMSJobStatus, WebhookPayload, SMSStats
)
from pydantic import BaseModel, validator
from services.twilio_service import TwilioService
from services.csv_processor import CSVProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration models
class TwilioConfig(BaseModel):
    account_sid: str
    auth_token: str
    sender_type: str = "phone"  # "phone" or "alphanumeric"
    phone_number: Optional[str] = None
    sender_id: Optional[str] = None

    @validator('sender_type')
    def validate_sender_type(cls, v):
        if v not in ['phone', 'alphanumeric']:
            raise ValueError('sender_type must be either "phone" or "alphanumeric"')
        return v

    @validator('phone_number')
    def validate_phone_number(cls, v, values):
        if values.get('sender_type') == 'phone' and not v:
            raise ValueError('phone_number is required when sender_type is "phone"')
        return v

    @validator('sender_id')
    def validate_sender_id(cls, v, values):
        if values.get('sender_type') == 'alphanumeric':
            if not v:
                raise ValueError('sender_id is required when sender_type is "alphanumeric"')
            if len(v) > 11:
                raise ValueError('sender_id must be 11 characters or less')
            if not re.match(r'^[a-zA-Z0-9\s]+$', v):
                raise ValueError('sender_id can only contain letters, numbers, and spaces')
        return v

class ConfigResponse(BaseModel):
    success: bool
    message: str
    configured: Optional[bool] = None
    config: Optional[dict] = None
    balance: Optional[str] = None
    currency: Optional[str] = None

# Global configuration storage
current_config = {
    'account_sid': os.getenv('TWILIO_ACCOUNT_SID'),
    'auth_token': os.getenv('TWILIO_AUTH_TOKEN'),
    'sender_type': os.getenv('TWILIO_SENDER_TYPE', 'phone'),
    'phone_number': os.getenv('TWILIO_PHONE_NUMBER'),
    'sender_id': os.getenv('TWILIO_SENDER_ID')
}

# Create FastAPI app
app = FastAPI(
    title="Twilio SMS Integration",
    description="Web application for sending and receiving SMS messages via Twilio",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
import os
if os.path.exists("frontend/css"):
    app.mount("/css", StaticFiles(directory="frontend/css"), name="css")
if os.path.exists("frontend/js"):
    app.mount("/js", StaticFiles(directory="frontend/js"), name="js")
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Initialize services (will be reinitialized when config is updated)
twilio_service = None
csv_processor = None

def initialize_services():
    """Initialize Twilio services with current configuration"""
    global twilio_service, csv_processor

    # Update environment variables
    if current_config['account_sid']:
        os.environ['TWILIO_ACCOUNT_SID'] = current_config['account_sid']
    if current_config['auth_token']:
        os.environ['TWILIO_AUTH_TOKEN'] = current_config['auth_token']
    if current_config['sender_type']:
        os.environ['TWILIO_SENDER_TYPE'] = current_config['sender_type']
    if current_config['phone_number']:
        os.environ['TWILIO_PHONE_NUMBER'] = current_config['phone_number']
    if current_config['sender_id']:
        os.environ['TWILIO_SENDER_ID'] = current_config['sender_id']

    try:
        twilio_service = TwilioService()
        csv_processor = CSVProcessor()
        return True
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        return False

def is_configured():
    """Check if Twilio is properly configured"""
    has_credentials = all([
        current_config.get('account_sid'),
        current_config.get('auth_token')
    ])

    sender_type = current_config.get('sender_type', 'phone')
    if sender_type == 'phone':
        has_sender = bool(current_config.get('phone_number'))
    else:
        has_sender = bool(current_config.get('sender_id'))

    return has_credentials and has_sender

def get_from_number():
    """Get the appropriate 'from' number/ID based on configuration"""
    sender_type = current_config.get('sender_type', 'phone')
    if sender_type == 'phone':
        return current_config.get('phone_number')
    else:
        return current_config.get('sender_id')

# Try to initialize services on startup
initialize_services()

# Create database tables on startup
@app.on_event("startup")
async def startup_event():
    create_tables()
    
    # Create directories if they don't exist
    os.makedirs("uploads", exist_ok=True)
    os.makedirs("frontend", exist_ok=True)

# Root endpoint - serve the main application page
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main application page."""
    try:
        with open("frontend/index.html", "r") as f:
            return f.read()
    except FileNotFoundError:
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Twilio SMS Integration</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
        </head>
        <body>
            <h1>Twilio SMS Integration</h1>
            <p>Frontend files not found. Please ensure frontend files are in the 'frontend' directory.</p>
            <p>API Documentation: <a href="/docs">/docs</a></p>
        </body>
        </html>
        """

# Configuration Routes

@app.get("/api/config/status", response_model=ConfigResponse)
async def get_config_status():
    """Get current configuration status"""
    try:
        configured = is_configured()

        if configured and twilio_service:
            # Test connection
            balance_result = twilio_service.get_account_balance()
            if balance_result.get('success'):
                return ConfigResponse(
                    success=True,
                    message="Configuration is valid",
                    configured=True,
                    config={
                        'account_sid': current_config.get('account_sid', ''),
                        'phone_number': current_config.get('phone_number', '')
                        # Don't return auth_token for security
                    }
                )

        return ConfigResponse(
            success=True,
            message="Configuration required",
            configured=False
        )

    except Exception as e:
        return ConfigResponse(
            success=False,
            message=str(e),
            configured=False
        )

@app.post("/api/config/save", response_model=ConfigResponse)
async def save_config(config: TwilioConfig):
    """Save Twilio configuration"""
    try:
        # Update global configuration
        current_config['account_sid'] = config.account_sid
        current_config['auth_token'] = config.auth_token
        current_config['sender_type'] = config.sender_type

        if config.sender_type == 'phone':
            current_config['phone_number'] = config.phone_number
            current_config['sender_id'] = None
        else:
            current_config['sender_id'] = config.sender_id
            current_config['phone_number'] = None

        # Reinitialize services
        if initialize_services():
            return ConfigResponse(
                success=True,
                message="Configuration saved successfully"
            )
        else:
            return ConfigResponse(
                success=False,
                message="Failed to initialize Twilio services with provided configuration"
            )

    except Exception as e:
        return ConfigResponse(
            success=False,
            message=str(e)
        )

@app.post("/api/config/test", response_model=ConfigResponse)
async def test_config(config: TwilioConfig):
    """Test Twilio configuration without saving"""
    try:
        # Temporarily set environment variables
        old_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        old_token = os.environ.get('TWILIO_AUTH_TOKEN')
        old_sender_type = os.environ.get('TWILIO_SENDER_TYPE')
        old_phone = os.environ.get('TWILIO_PHONE_NUMBER')
        old_sender_id = os.environ.get('TWILIO_SENDER_ID')

        os.environ['TWILIO_ACCOUNT_SID'] = config.account_sid
        os.environ['TWILIO_AUTH_TOKEN'] = config.auth_token
        os.environ['TWILIO_SENDER_TYPE'] = config.sender_type

        if config.sender_type == 'phone':
            os.environ['TWILIO_PHONE_NUMBER'] = config.phone_number or ''
            os.environ['TWILIO_SENDER_ID'] = ''
        else:
            os.environ['TWILIO_SENDER_ID'] = config.sender_id or ''
            os.environ['TWILIO_PHONE_NUMBER'] = ''

        # Test connection
        test_service = TwilioService()
        balance_result = test_service.get_account_balance()

        # Restore original environment variables
        if old_sid:
            os.environ['TWILIO_ACCOUNT_SID'] = old_sid
        else:
            os.environ.pop('TWILIO_ACCOUNT_SID', None)

        if old_token:
            os.environ['TWILIO_AUTH_TOKEN'] = old_token
        else:
            os.environ.pop('TWILIO_AUTH_TOKEN', None)

        if old_sender_type:
            os.environ['TWILIO_SENDER_TYPE'] = old_sender_type
        else:
            os.environ.pop('TWILIO_SENDER_TYPE', None)

        if old_phone:
            os.environ['TWILIO_PHONE_NUMBER'] = old_phone
        else:
            os.environ.pop('TWILIO_PHONE_NUMBER', None)

        if old_sender_id:
            os.environ['TWILIO_SENDER_ID'] = old_sender_id
        else:
            os.environ.pop('TWILIO_SENDER_ID', None)

        if balance_result.get('success'):
            return ConfigResponse(
                success=True,
                message="Connection test successful",
                balance=balance_result.get('balance'),
                currency=balance_result.get('currency')
            )
        else:
            return ConfigResponse(
                success=False,
                message=balance_result.get('error_message', 'Connection test failed')
            )

    except Exception as e:
        return ConfigResponse(
            success=False,
            message=str(e)
        )

# API Routes

@app.post("/api/sms/send", response_model=SMSResponse)
async def send_sms(sms_request: SMSRequest, db: Session = Depends(get_db)):
    """Send a single SMS message"""
    try:
        # Check if Twilio is configured
        if not is_configured():
            logger.error("Twilio not configured - missing configuration")
            raise HTTPException(status_code=400, detail="Twilio not configured. Please configure Twilio credentials first.")

        if not twilio_service:
            logger.error("Twilio service not initialized")
            raise HTTPException(status_code=500, detail="Twilio service not available. Please restart the application.")

        logger.info(f"Sending SMS to {sms_request.to_number}")
        # Send SMS via Twilio
        result = twilio_service.send_sms(sms_request.to_number, sms_request.message_body)
        
        # Store in database
        sms_message = SMSMessage(
            message_sid=result.get("message_sid"),
            from_number=result.get("from_number", ""),
            to_number=sms_request.to_number,
            message_body=sms_request.message_body,
            status=result.get("status", "failed"),
            direction="outbound",
            cost=float(result.get("price", 0)) if result.get("price") else None,
            error_code=result.get("error_code"),
            error_message=result.get("error_message")
        )
        
        db.add(sms_message)
        db.commit()
        
        if result.get("success"):
            logger.info(f"SMS sent successfully. SID: {result.get('message_sid')}")
            return SMSResponse(
                success=True,
                message_sid=result["message_sid"],
                message="SMS sent successfully",
                cost=float(result.get("price", 0)) if result.get("price") else None
            )
        else:
            error_msg = result.get("error_message", "Failed to send SMS")
            logger.error(f"SMS sending failed: {error_msg}")
            return SMSResponse(
                success=False,
                message=error_msg
            )
            
    except Exception as e:
        logger.error(f"Error sending SMS: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sms/bulk", response_model=BulkSMSResponse)
async def send_bulk_sms(
    file: UploadFile = File(...),
    message_template: str = Form(...),
    db: Session = Depends(get_db)
):
    """Send bulk SMS from CSV file"""
    try:
        # Check if Twilio is configured
        if not is_configured() or not csv_processor:
            raise HTTPException(status_code=400, detail="Twilio not configured. Please configure Twilio credentials first.")
        # Validate file type
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="Only CSV files are allowed")
        
        # Save uploaded file
        file_path = f"uploads/{uuid.uuid4()}_{file.filename}"
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # Process bulk SMS
        result = await csv_processor.process_bulk_sms(file_path, message_template, db)
        
        if result["success"]:
            return BulkSMSResponse(
                success=True,
                job_id=result["job_id"],
                message=result["message"],
                total_count=result["total_count"]
            )
        else:
            # Clean up file if processing failed
            if os.path.exists(file_path):
                os.remove(file_path)
            
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to process bulk SMS"))
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing bulk SMS: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sms/history", response_model=List[SMSStatus])
async def get_sms_history(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Get SMS message history"""
    try:
        messages = db.query(SMSMessage).order_by(SMSMessage.created_at.desc()).offset(offset).limit(limit).all()
        
        return [
            SMSStatus(
                id=msg.id,
                message_sid=msg.message_sid or "",
                from_number=msg.from_number,
                to_number=msg.to_number,
                message_body=msg.message_body,
                status=msg.status,
                direction=msg.direction,
                cost=msg.cost,
                error_code=msg.error_code,
                error_message=msg.error_message,
                created_at=msg.created_at,
                updated_at=msg.updated_at
            )
            for msg in messages
        ]
        
    except Exception as e:
        logger.error(f"Error fetching SMS history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sms/jobs", response_model=List[BulkSMSJobStatus])
async def get_bulk_jobs(db: Session = Depends(get_db)):
    """Get bulk SMS job status"""
    try:
        jobs = db.query(BulkSMSJob).order_by(BulkSMSJob.created_at.desc()).all()
        
        return [
            BulkSMSJobStatus(
                id=job.id,
                job_id=job.job_id,
                filename=job.filename,
                total_count=job.total_count,
                sent_count=job.sent_count,
                failed_count=job.failed_count,
                status=job.status,
                message_template=job.message_template,
                created_at=job.created_at,
                completed_at=job.completed_at
            )
            for job in jobs
        ]
        
    except Exception as e:
        logger.error(f"Error fetching bulk SMS jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sms/stats", response_model=SMSStats)
async def get_sms_stats(db: Session = Depends(get_db)):
    """Get SMS statistics"""
    try:
        # Total statistics
        total_sent = db.query(func.count(SMSMessage.id)).filter(
            SMSMessage.direction == "outbound"
        ).scalar() or 0
        
        total_delivered = db.query(func.count(SMSMessage.id)).filter(
            and_(SMSMessage.direction == "outbound", SMSMessage.status == "delivered")
        ).scalar() or 0
        
        total_failed = db.query(func.count(SMSMessage.id)).filter(
            and_(SMSMessage.direction == "outbound", SMSMessage.status == "failed")
        ).scalar() or 0
        
        total_cost = db.query(func.sum(SMSMessage.cost)).filter(
            SMSMessage.direction == "outbound"
        ).scalar() or 0.0
        
        # Today's statistics
        today = datetime.utcnow().date()
        today_sent = db.query(func.count(SMSMessage.id)).filter(
            and_(
                SMSMessage.direction == "outbound",
                func.date(SMSMessage.created_at) == today
            )
        ).scalar() or 0
        
        # This month's statistics
        this_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        this_month_sent = db.query(func.count(SMSMessage.id)).filter(
            and_(
                SMSMessage.direction == "outbound",
                SMSMessage.created_at >= this_month_start
            )
        ).scalar() or 0
        
        return SMSStats(
            total_sent=total_sent,
            total_delivered=total_delivered,
            total_failed=total_failed,
            total_cost=float(total_cost),
            today_sent=today_sent,
            this_month_sent=this_month_sent
        )
        
    except Exception as e:
        logger.error(f"Error fetching SMS statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/webhooks/status")
async def webhook_status_callback(request: Request, db: Session = Depends(get_db)):
    """Handle Twilio status callback webhooks"""
    try:
        # Get form data from Twilio webhook
        form_data = await request.form()
        
        # Log webhook payload
        webhook_log = WebhookLog(
            message_sid=form_data.get("MessageSid"),
            webhook_type="status_callback",
            payload=str(dict(form_data)),
            processed=False
        )
        db.add(webhook_log)
        
        # Update SMS message status
        message_sid = form_data.get("MessageSid")
        if message_sid:
            sms_message = db.query(SMSMessage).filter(SMSMessage.message_sid == message_sid).first()
            if sms_message:
                sms_message.status = form_data.get("MessageStatus", sms_message.status)
                sms_message.error_code = form_data.get("ErrorCode")
                sms_message.error_message = form_data.get("ErrorMessage")
                sms_message.updated_at = datetime.utcnow()
                
                webhook_log.processed = True
        
        db.commit()
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error processing status webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/webhooks/incoming")
async def webhook_incoming_sms(request: Request, db: Session = Depends(get_db)):
    """Handle incoming SMS webhooks"""
    try:
        # Get form data from Twilio webhook
        form_data = await request.form()
        
        # Log webhook payload
        webhook_log = WebhookLog(
            message_sid=form_data.get("MessageSid"),
            webhook_type="incoming_message",
            payload=str(dict(form_data)),
            processed=False
        )
        db.add(webhook_log)
        
        # Store incoming SMS message
        sms_message = SMSMessage(
            message_sid=form_data.get("MessageSid"),
            from_number=form_data.get("From", ""),
            to_number=form_data.get("To", ""),
            message_body=form_data.get("Body", ""),
            status="received",
            direction="inbound"
        )
        
        db.add(sms_message)
        webhook_log.processed = True
        db.commit()
        
        # Return TwiML response (optional - for auto-reply)
        return HTMLResponse(
            content="""<?xml version="1.0" encoding="UTF-8"?>
            <Response>
                <Message>Thank you for your message. We have received it.</Message>
            </Response>""",
            media_type="application/xml"
        )
        
    except Exception as e:
        logger.error(f"Error processing incoming SMS webhook: {e}")
        return HTMLResponse(
            content="""<?xml version="1.0" encoding="UTF-8"?>
            <Response></Response>""",
            media_type="application/xml"
        )

@app.get("/api/account/balance")
async def get_account_balance():
    """Get Twilio account balance"""
    try:
        # Check if Twilio is configured
        if not is_configured() or not twilio_service:
            return {"success": False, "error_message": "Twilio not configured"}

        result = twilio_service.get_account_balance()
        return result

    except Exception as e:
        logger.error(f"Error fetching account balance: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn

    # Create necessary directories
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('frontend', exist_ok=True)

    # Get port from environment variable (for deployment) or default to 8000
    port = int(os.getenv("PORT", 8000))

    print("🚀 Starting Twilio SMS Integration Application")
    print("📱 Send and receive SMS messages via Twilio")
    print(f"📊 Access the application at: http://localhost:{port}")
    print(f"📚 API Documentation: http://localhost:{port}/docs")

    uvicorn.run(app, host="0.0.0.0", port=port)
