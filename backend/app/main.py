"""
Twilio SMS Integration FastAPI Application
"""

import os
import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

# Import local modules
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ..database import create_tables, get_db, SMSMessage, BulkSMSJob, WebhookLog
from ..models.sms import (
    SMSRequest, SMSResponse, BulkSMSRequest, BulkSMSResponse,
    SMSStatus, BulkSMSJobStatus, WebhookPayload, SMSStats
)
from ..services.twilio_service import TwilioService
from ..services.csv_processor import CSVProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
app.mount("/static", StaticFiles(directory="../../frontend"), name="static")

# Initialize services
twilio_service = TwilioService()
csv_processor = CSVProcessor()

# Create database tables on startup
@app.on_event("startup")
async def startup_event():
    create_tables()
    
    # Create directories if they don't exist
    os.makedirs("uploads", exist_ok=True)
    os.makedirs("../../frontend", exist_ok=True)

# Root endpoint - serve the main application page
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main application page."""
    try:
        with open("../../frontend/index.html", "r") as f:
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
            <p>Frontend files not found. Please create the frontend files.</p>
            <p>API Documentation: <a href="/docs">/docs</a></p>
        </body>
        </html>
        """

# API Routes

@app.post("/api/sms/send", response_model=SMSResponse)
async def send_sms(sms_request: SMSRequest, db: Session = Depends(get_db)):
    """Send a single SMS message"""
    try:
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
        
        if result["success"]:
            return SMSResponse(
                success=True,
                message_sid=result["message_sid"],
                message="SMS sent successfully",
                cost=float(result.get("price", 0)) if result.get("price") else None
            )
        else:
            return SMSResponse(
                success=False,
                message=result.get("error_message", "Failed to send SMS")
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

@app.get("/api/validate-csv")
async def validate_csv_file(file: UploadFile = File(...)):
    """Validate CSV file format"""
    try:
        # Save temporary file
        temp_file_path = f"uploads/temp_{uuid.uuid4()}_{file.filename}"
        with open(temp_file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        # Validate CSV
        result = csv_processor.validate_csv_file(temp_file_path)

        # Clean up temporary file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        return result

    except Exception as e:
        logger.error(f"Error validating CSV file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/account/balance")
async def get_account_balance():
    """Get Twilio account balance"""
    try:
        result = twilio_service.get_account_balance()
        return result

    except Exception as e:
        logger.error(f"Error fetching account balance: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn

    # Create necessary directories
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('../../frontend', exist_ok=True)

    print("🚀 Starting Twilio SMS Integration Application")
    print("📱 Send and receive SMS messages via Twilio")
    print("📊 Access the application at: http://localhost:8000")
    print("📚 API Documentation: http://localhost:8000/docs")

    uvicorn.run(app, host="0.0.0.0", port=8000)
