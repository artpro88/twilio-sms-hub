#!/usr/bin/env python3
"""
Direct runner for Twilio SMS Integration
This file can be run directly without import issues
"""

import os
import sys
import uuid
import json
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
try:
    from models.sms import (
        SMSRequest, SMSResponse, BulkSMSRequest, BulkSMSResponse,
        SMSStatus, BulkSMSJobStatus, WebhookPayload, SMSStats
    )
except ImportError as e:
    logger.error(f"Failed to import models: {e}")
    # Define minimal models as fallback
    from pydantic import BaseModel
    from typing import Optional

    class SMSResponse(BaseModel):
        success: bool
        message: str
        message_sid: Optional[str] = None
        cost: Optional[float] = None

    class BulkSMSResponse(BaseModel):
        success: bool
        message: str
        job_id: Optional[str] = None
        total_count: Optional[int] = None
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

# Configuration file path
CONFIG_FILE = "twilio_config.json"

def load_config():
    """Load configuration from file or environment variables"""
    config = {}

    # Try to load from file first
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            logger.info("Configuration loaded from file")
        except Exception as e:
            logger.warning(f"Failed to load config from file: {e}")

    # Fallback to environment variables if file doesn't exist or is empty
    if not config:
        config = {
            'account_sid': os.getenv('TWILIO_ACCOUNT_SID'),
            'auth_token': os.getenv('TWILIO_AUTH_TOKEN'),
            'sender_type': os.getenv('TWILIO_SENDER_TYPE', 'phone'),
            'phone_number': os.getenv('TWILIO_PHONE_NUMBER'),
            'sender_id': os.getenv('TWILIO_SENDER_ID')
        }
        logger.info("Configuration loaded from environment variables")

    return config

def save_config_to_file(config):
    """Save configuration to file"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info("Configuration saved to file")
    except Exception as e:
        logger.error(f"Failed to save config to file: {e}")

# Global configuration storage
current_config = load_config()

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

# Global request deduplication tracker
import time
_global_sms_requests = {}
ENABLE_APP_LEVEL_DEDUP = True  # Re-enabled to prevent bulk SMS duplicates

def is_duplicate_request(phone_number, message_body, source="unknown"):
    """Check if this is a duplicate SMS request from any source"""
    if not ENABLE_APP_LEVEL_DEDUP:
        logger.info(f"🔓 APP-LEVEL DEDUP DISABLED: Allowing request from {source}")
        return False

    request_key = f"{phone_number.lower()}:{message_body.lower()}"
    current_time = time.time()

    logger.info(f"🔍 CHECKING REQUEST: {phone_number}, source='{source}', message='{message_body[:30]}...', key='{request_key}'")
    logger.info(f"📊 Current requests in cache: {len(_global_sms_requests)}")

    # Check if we've processed this exact request recently (within 10 seconds)
    if request_key in _global_sms_requests:
        last_request_time, last_source = _global_sms_requests[request_key]
        time_diff = current_time - last_request_time
        if time_diff < 10:  # 10 second window
            logger.warning(f"🚫 DUPLICATE REQUEST BLOCKED: {phone_number}, message='{message_body[:30]}...', "
                         f"last_source='{last_source}', current_source='{source}', "
                         f"sent {time_diff:.2f} seconds ago")
            return True
        else:
            logger.info(f"⏰ Request allowed - previous request was {time_diff:.2f} seconds ago (>10s)")

    # Record this request
    _global_sms_requests[request_key] = (current_time, source)

    # Clean up old entries (older than 30 seconds) - but keep current one
    old_count = len(_global_sms_requests)
    _global_sms_requests = {k: v for k, v in _global_sms_requests.items() if current_time - v[0] < 30}
    new_count = len(_global_sms_requests)
    if old_count != new_count:
        logger.info(f"🧹 Cleaned up {old_count - new_count} old request entries")

    logger.info(f"✅ REQUEST ALLOWED: {phone_number}, source='{source}', message='{message_body[:30]}...', cache_size={len(_global_sms_requests)}")
    return False

def initialize_services():
    """Initialize Twilio services with current configuration"""
    global twilio_service, csv_processor

    # Update environment variables
    if current_config.get('account_sid'):
        os.environ['TWILIO_ACCOUNT_SID'] = current_config['account_sid']
    if current_config.get('auth_token'):
        os.environ['TWILIO_AUTH_TOKEN'] = current_config['auth_token']
    if current_config.get('sender_type'):
        os.environ['TWILIO_SENDER_TYPE'] = current_config['sender_type']

    # Clear both sender environment variables first
    os.environ.pop('TWILIO_PHONE_NUMBER', None)
    os.environ.pop('TWILIO_SENDER_ID', None)

    # Set the appropriate sender based on type
    if current_config.get('sender_type') == 'phone' and current_config.get('phone_number'):
        os.environ['TWILIO_PHONE_NUMBER'] = current_config['phone_number']
    elif current_config.get('sender_type') == 'alphanumeric' and current_config.get('sender_id'):
        os.environ['TWILIO_SENDER_ID'] = current_config['sender_id']

    try:
        twilio_service = TwilioService()
        csv_processor = CSVProcessor(twilio_service)
        return True
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        logger.exception("Service initialization error:")
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

        # Save configuration to file for persistence
        save_config_to_file(current_config)

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

@app.get("/api/config/status")
async def get_config_status():
    """Get current configuration status for debugging"""
    return {
        "is_configured": is_configured(),
        "has_twilio_service": twilio_service is not None,
        "config_file_exists": os.path.exists(CONFIG_FILE),
        "current_config": {
            "has_account_sid": bool(current_config.get('account_sid')),
            "has_auth_token": bool(current_config.get('auth_token')),
            "sender_type": current_config.get('sender_type'),
            "has_phone_number": bool(current_config.get('phone_number')),
            "has_sender_id": bool(current_config.get('sender_id')),
            "account_sid_preview": current_config.get('account_sid', '')[:8] + "..." if current_config.get('account_sid') else None,
        },
        "environment_vars": {
            "TWILIO_ACCOUNT_SID": bool(os.getenv('TWILIO_ACCOUNT_SID')),
            "TWILIO_AUTH_TOKEN": bool(os.getenv('TWILIO_AUTH_TOKEN')),
            "TWILIO_SENDER_TYPE": os.getenv('TWILIO_SENDER_TYPE'),
            "TWILIO_PHONE_NUMBER": bool(os.getenv('TWILIO_PHONE_NUMBER')),
            "TWILIO_SENDER_ID": bool(os.getenv('TWILIO_SENDER_ID')),
        }
    }

@app.get("/api/test/simple")
async def simple_test():
    """Simple test endpoint"""
    try:
        return {"status": "ok", "message": "API is working"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/config/reload")
async def reload_config():
    """Reload configuration from file and reinitialize services"""
    try:
        global current_config
        current_config = load_config()

        if initialize_services():
            return {
                "success": True,
                "message": "Configuration reloaded and services reinitialized",
                "is_configured": is_configured()
            }
        else:
            return {
                "success": False,
                "message": "Configuration reloaded but service initialization failed"
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to reload configuration: {str(e)}"
        }

@app.post("/api/test/bulk-sms-direct")
async def test_bulk_sms_direct(request: dict):
    """Test bulk SMS with direct service call"""
    try:
        phone_number = request.get('phone_number')
        message = request.get('message', 'Test bulk SMS message')

        if not phone_number:
            return {"success": False, "error": "phone_number required"}

        logger.info(f"Testing bulk SMS direct call to {phone_number}")

        # Check services
        if not twilio_service:
            return {"success": False, "error": "Twilio service not available"}

        if not csv_processor:
            return {"success": False, "error": "CSV processor not available"}

        # Test if CSV processor has the same service
        csv_service_available = csv_processor.twilio_service is not None
        same_service = csv_processor.twilio_service is twilio_service

        # Ensure CSV processor has current service
        if csv_processor and twilio_service:
            csv_processor.twilio_service = twilio_service

        # Try sending with both services
        single_result = twilio_service.send_sms(phone_number, message + " (single)")

        if csv_processor.twilio_service:
            bulk_result = csv_processor.twilio_service.send_sms(phone_number, message + " (bulk)")
        else:
            bulk_result = {"success": False, "error": "CSV processor has no Twilio service"}

        return {
            "success": True,
            "phone_number": phone_number,
            "csv_service_available": csv_service_available,
            "same_service_instance": same_service,
            "single_sms_result": single_result,
            "bulk_sms_result": bulk_result
        }

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.post("/api/test/simulate-bulk")
async def simulate_bulk_sms(request: dict, db: Session = Depends(get_db)):
    """Simulate bulk SMS processing without CSV file"""
    try:
        phone_number = request.get('phone_number', '+447960858925')
        message_template = request.get('message_template', 'Hello {name}, test {custom_field}')

        # Simulate recipient data (like what comes from CSV)
        recipients = [
            {
                "phone_number": phone_number,
                "name": "TestUser",
                "custom_field": "123"
            }
        ]

        logger.info(f"Simulating bulk SMS to {phone_number}")

        # Check services
        if not twilio_service:
            return {"success": False, "error": "Twilio service not available"}

        if not csv_processor:
            return {"success": False, "error": "CSV processor not available"}

        # Ensure CSV processor has current service
        csv_processor.twilio_service = twilio_service

        # Simulate the exact same process as bulk SMS
        results = []
        for recipient in recipients:
            try:
                # Format phone number (same as CSV processor)
                formatted_number = csv_processor._format_phone_number(recipient["phone_number"])

                # Personalize message (same as CSV processor)
                personalized_message = csv_processor._personalize_message(message_template, recipient)

                # Send SMS using CSV processor's service
                result = csv_processor.twilio_service.send_sms(formatted_number, personalized_message)

                results.append({
                    "recipient": recipient,
                    "formatted_number": formatted_number,
                    "personalized_message": personalized_message,
                    "sms_result": result
                })

            except Exception as e:
                results.append({
                    "recipient": recipient,
                    "error": str(e),
                    "traceback": traceback.format_exc()
                })

        return {
            "success": True,
            "results": results,
            "csv_processor_service_available": csv_processor.twilio_service is not None,
            "same_as_global_service": csv_processor.twilio_service is twilio_service
        }

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.post("/api/test/bulk-sync")
async def test_bulk_sms_sync(
    file: UploadFile = File(...),
    message_template: str = Form(...),
    send_real_sms: bool = Form(False),
    db: Session = Depends(get_db)
):
    """Test bulk SMS processing synchronously (no background task) for debugging"""

    result = {
        "timestamp": datetime.now().isoformat(),
        "steps": [],
        "messages_sent": [],
        "final_result": {}
    }

    def add_step(step, status, details, data=None):
        result["steps"].append({
            "step": step,
            "status": status,
            "details": details,
            "data": data
        })

    try:
        # Step 1: Basic checks
        if not is_configured():
            add_step("Configuration", "error", "Twilio not configured")
            return result

        if not twilio_service:
            add_step("Service Check", "error", "Twilio service not available")
            return result

        add_step("Initial Checks", "success", f"Configured: {is_configured()}, Service: {twilio_service is not None}")

        # Step 2: Save file
        os.makedirs("uploads", exist_ok=True)
        file_path = f"uploads/sync_test_{uuid.uuid4()}_{file.filename}"

        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        add_step("File Save", "success", f"Saved {len(content)} bytes to {file_path}")

        # Step 3: Process CSV directly (no CSV processor)
        try:
            import pandas as pd
            df = pd.read_csv(file_path)
            add_step("CSV Read", "success", f"Read {len(df)} rows with columns: {list(df.columns)}")

            # Validate required columns
            if 'phone_number' not in df.columns:
                add_step("CSV Validation", "error", "Missing 'phone_number' column")
                return result

            recipients = []
            for index, row in df.iterrows():
                phone_number = str(row['phone_number']).strip()

                # Add + prefix if missing
                if not phone_number.startswith('+'):
                    phone_number = '+' + phone_number

                recipients.append({
                    "phone_number": phone_number,
                    "name": row.get('name', ''),
                    "custom_field": row.get('custom_field', '')
                })

            add_step("CSV Processing", "success", f"Processed {len(recipients)} recipients", recipients)

        except Exception as e:
            add_step("CSV Processing", "error", f"CSV error: {str(e)}")
            return result

        # Step 4: Send SMS synchronously (no background task)
        sent_count = 0
        failed_count = 0

        for i, recipient in enumerate(recipients):
            try:
                # Personalize message
                personalized_message = message_template
                for key, value in recipient.items():
                    if key != 'phone_number':
                        # Convert value to string to avoid type errors
                        str_value = str(value) if value is not None else ''
                        personalized_message = personalized_message.replace(f'{{{key}}}', str_value)

                add_step(f"Message {i+1} Prep", "success", f"To: {recipient['phone_number']}, Message: '{personalized_message}'")

                # Send SMS only if explicitly requested
                if send_real_sms:
                    sms_result = twilio_service.send_sms(recipient['phone_number'], personalized_message)
                else:
                    # Simulate successful SMS for testing
                    sms_result = {
                        "success": True,
                        "message_sid": f"TEST_SID_{i+1}",
                        "status": "test_mode",
                        "from_number": "TEST_SENDER",
                        "message": "SMS not sent - test mode"
                    }

                # Record result
                if sms_result.get("success"):
                    sent_count += 1
                    add_step(f"Message {i+1} Send", "success", f"SMS sent successfully: {sms_result}")

                    # Create database record
                    sms_message = SMSMessage(
                        message_sid=sms_result.get("message_sid"),
                        from_number=sms_result.get("from_number", ""),
                        to_number=recipient['phone_number'],
                        message_body=personalized_message,
                        status=sms_result.get("status", "sent"),
                        direction="outbound",
                        cost=float(sms_result.get("price", 0)) if sms_result.get("price") else None,
                        error_code=sms_result.get("error_code"),
                        error_message=sms_result.get("error_message")
                    )
                    db.add(sms_message)

                else:
                    failed_count += 1
                    add_step(f"Message {i+1} Send", "error", f"SMS failed: {sms_result}")

                result["messages_sent"].append({
                    "recipient": recipient,
                    "message": personalized_message,
                    "result": sms_result
                })

            except Exception as e:
                failed_count += 1
                add_step(f"Message {i+1} Send", "error", f"Exception: {str(e)}")
                result["messages_sent"].append({
                    "recipient": recipient,
                    "error": str(e)
                })

        # Commit database changes
        try:
            db.commit()
            add_step("Database Commit", "success", "Database changes committed")
        except Exception as e:
            add_step("Database Commit", "error", f"Database error: {str(e)}")

        # Final result
        result["final_result"] = {
            "total_recipients": len(recipients),
            "sent_count": sent_count,
            "failed_count": failed_count,
            "success_rate": f"{(sent_count/len(recipients)*100):.1f}%" if recipients else "0%"
        }

        # Cleanup
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass

        return result

    except Exception as e:
        import traceback
        add_step("System Error", "error", f"Unexpected error: {str(e)}")
        result["error_details"] = {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        return result

@app.get("/api/troubleshoot/bulk-sms")
async def troubleshoot_bulk_sms_info():
    """Info about the troubleshoot endpoint"""
    return {
        "message": "This is the bulk SMS troubleshooting endpoint",
        "usage": "POST with form data: file (CSV) and message_template",
        "example_curl": "curl -X POST /api/troubleshoot/bulk-sms -F 'file=@test.csv' -F 'message_template=Hi {name}'",
        "web_interface": "Use the 'Troubleshoot' button in the Bulk SMS tab"
    }

@app.post("/api/troubleshoot/bulk-sms")
async def troubleshoot_bulk_sms(
    file: UploadFile = File(...),
    message_template: str = Form(...),
    send_real_sms: bool = Form(False),
    db: Session = Depends(get_db)
):
    """Comprehensive troubleshooting for bulk SMS - runs through entire process with detailed reporting"""

    troubleshoot_report = {
        "timestamp": datetime.now().isoformat(),
        "steps": [],
        "final_diagnosis": "",
        "recommendations": []
    }

    def add_step(step_name, status, details, data=None):
        troubleshoot_report["steps"].append({
            "step": step_name,
            "status": status,  # "success", "warning", "error"
            "details": details,
            "data": data
        })

    try:
        # Step 1: Check basic configuration
        add_step("Configuration Check",
                "success" if is_configured() else "error",
                f"Twilio configured: {is_configured()}, Has twilio_service: {twilio_service is not None}, Has csv_processor: {csv_processor is not None}")

        if not is_configured():
            troubleshoot_report["final_diagnosis"] = "Twilio not configured"
            troubleshoot_report["recommendations"] = ["Configure Twilio credentials in the Configuration tab"]
            return troubleshoot_report

        # Step 2: File validation
        if not file.filename.endswith('.csv'):
            add_step("File Validation", "error", f"Invalid file type: {file.filename}")
            troubleshoot_report["final_diagnosis"] = "Invalid file type"
            return troubleshoot_report

        add_step("File Validation", "success", f"Valid CSV file: {file.filename}")

        # Step 3: Save and read file
        os.makedirs("uploads", exist_ok=True)
        file_path = f"uploads/troubleshoot_{uuid.uuid4()}_{file.filename}"

        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        add_step("File Upload", "success", f"File saved: {file_path}, Size: {len(content)} bytes")

        # Step 4: Read and analyze CSV content
        try:
            import pandas as pd
            df = pd.read_csv(file_path)
            add_step("CSV Reading", "success", f"CSV read successfully. Columns: {list(df.columns)}, Rows: {len(df)}", {
                "columns": list(df.columns),
                "row_count": len(df),
                "sample_data": df.head(3).to_dict('records') if len(df) > 0 else []
            })
        except Exception as e:
            add_step("CSV Reading", "error", f"Failed to read CSV: {str(e)}")
            troubleshoot_report["final_diagnosis"] = "CSV file format error"
            return troubleshoot_report

        # Step 5: CSV validation using processor
        if csv_processor:
            csv_processor.twilio_service = twilio_service  # Ensure current service
            validation_result = csv_processor.validate_csv_file(file_path)

            add_step("CSV Validation",
                    "success" if validation_result.get("success") else "error",
                    f"Validation result: {validation_result}",
                    validation_result)

            if not validation_result.get("success"):
                troubleshoot_report["final_diagnosis"] = "CSV validation failed"
                troubleshoot_report["recommendations"] = [
                    "Check CSV format: must have 'phone_number' column",
                    "Ensure phone numbers are valid",
                    "Check for proper CSV encoding"
                ]
                return troubleshoot_report
        else:
            add_step("CSV Validation", "error", "CSV processor not available")
            troubleshoot_report["final_diagnosis"] = "CSV processor not initialized"
            return troubleshoot_report

        # Step 6: Test individual SMS sending
        valid_numbers = validation_result.get("valid_numbers", [])
        if valid_numbers:
            test_recipient = valid_numbers[0]

            # Test phone number formatting
            formatted_number = csv_processor._format_phone_number(test_recipient["phone_number"])
            add_step("Phone Formatting", "success", f"Original: {test_recipient['phone_number']} → Formatted: {formatted_number}")

            # Test message personalization
            personalized_message = csv_processor._personalize_message(message_template, test_recipient)
            add_step("Message Personalization", "success", f"Template: '{message_template}' → Result: '{personalized_message}'")

            # Test actual SMS sending (only if explicitly requested)
            try:
                if send_real_sms:
                    sms_result = twilio_service.send_sms(formatted_number, personalized_message)
                    add_step("SMS Test",
                            "success" if sms_result.get("success") else "error",
                            f"SMS test result: {sms_result}",
                            sms_result)
                else:
                    # Simulate SMS test without actually sending
                    sms_result = {
                        "success": True,
                        "message_sid": "TEST_SID_TROUBLESHOOT",
                        "status": "test_mode",
                        "message": "SMS not sent - troubleshoot test mode"
                    }
                    add_step("SMS Test",
                            "success",
                            f"SMS test simulated (no real SMS sent): {sms_result}",
                            sms_result)

                if not sms_result.get("success"):
                    troubleshoot_report["final_diagnosis"] = "SMS sending failed"
                    troubleshoot_report["recommendations"] = [
                        f"Twilio error: {sms_result.get('error_message', 'Unknown error')}",
                        "Check phone number format",
                        "Verify Twilio account balance",
                        "Check sender ID configuration"
                    ]
                    return troubleshoot_report

            except Exception as e:
                add_step("SMS Test", "error", f"SMS test exception: {str(e)}")
                troubleshoot_report["final_diagnosis"] = "SMS service error"
                return troubleshoot_report

        # Step 7: Database test
        try:
            # Test creating a job record
            test_job = BulkSMSJob(
                job_id="test_" + str(uuid.uuid4()),
                filename=file.filename,
                total_count=len(valid_numbers),
                message_template=message_template,
                status="testing"
            )
            db.add(test_job)
            db.commit()

            # Test creating SMS message record
            test_message = SMSMessage(
                message_sid="test_sid",
                from_number="test_from",
                to_number=formatted_number,
                message_body=personalized_message,
                status="test",
                direction="outbound"
            )
            db.add(test_message)
            db.commit()

            # Clean up test records
            db.delete(test_job)
            db.delete(test_message)
            db.commit()

            add_step("Database Test", "success", "Database operations successful")

        except Exception as e:
            add_step("Database Test", "error", f"Database error: {str(e)}")
            troubleshoot_report["final_diagnosis"] = "Database error"
            return troubleshoot_report

        # Step 8: Full process simulation
        try:
            # Simulate the exact bulk SMS process
            job_id = "troubleshoot_" + str(uuid.uuid4())

            bulk_job = BulkSMSJob(
                job_id=job_id,
                filename=file.filename,
                total_count=len(valid_numbers),
                message_template=message_template,
                status="processing"
            )
            db.add(bulk_job)
            db.commit()

            sent_count = 0
            failed_count = 0
            message_results = []

            for recipient in valid_numbers[:2]:  # Test first 2 only
                try:
                    phone_number = csv_processor._format_phone_number(recipient["phone_number"])
                    message_body = csv_processor._personalize_message(message_template, recipient)

                    result = twilio_service.send_sms(phone_number, message_body)

                    # Create SMS message record (skip if duplicate blocked)
                    if result.get("status") != "duplicate_blocked":
                        sms_message = SMSMessage(
                            message_sid=result.get("message_sid"),
                            from_number=result.get("from_number", ""),
                            to_number=phone_number,
                            message_body=message_body,
                            status=result.get("status", "failed"),
                            direction="outbound",
                            cost=float(result.get("price", 0)) if result.get("price") else None,
                            error_code=result.get("error_code"),
                            error_message=result.get("error_message")
                        )
                        db.add(sms_message)
                    else:
                        logger.info(f"Skipping database record for duplicate blocked message to {phone_number}")

                    if result.get("success"):
                        sent_count += 1
                    else:
                        failed_count += 1

                    message_results.append({
                        "recipient": recipient,
                        "formatted_number": phone_number,
                        "message": message_body,
                        "result": result
                    })

                except Exception as e:
                    failed_count += 1
                    message_results.append({
                        "recipient": recipient,
                        "error": str(e)
                    })

            # Update job status
            bulk_job.status = "completed"
            bulk_job.sent_count = sent_count
            bulk_job.failed_count = failed_count
            bulk_job.completed_at = datetime.now()
            db.commit()

            add_step("Full Process Test", "success", f"Process completed. Sent: {sent_count}, Failed: {failed_count}", {
                "job_id": job_id,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "message_results": message_results
            })

            if failed_count > 0:
                troubleshoot_report["final_diagnosis"] = "Some messages failed during full process test"
                troubleshoot_report["recommendations"] = [
                    "Check individual message results in the data section",
                    "Verify phone numbers are valid and reachable",
                    "Check Twilio account status and balance"
                ]
            else:
                troubleshoot_report["final_diagnosis"] = "All systems working correctly"
                troubleshoot_report["recommendations"] = [
                    "Bulk SMS should work normally",
                    "If still having issues, check Railway logs for background task errors"
                ]

        except Exception as e:
            add_step("Full Process Test", "error", f"Full process failed: {str(e)}")
            troubleshoot_report["final_diagnosis"] = "Full process simulation failed"

        # Cleanup
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass

        return troubleshoot_report

    except Exception as e:
        import traceback
        add_step("Troubleshooting Error", "error", f"Troubleshooting itself failed: {str(e)}")
        troubleshoot_report["final_diagnosis"] = "Troubleshooting system error"
        troubleshoot_report["error_details"] = {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        return troubleshoot_report

@app.get("/api/troubleshoot/quick-test")
async def quick_troubleshoot(db: Session = Depends(get_db)):
    """Quick troubleshooting without file upload - accessible via browser"""

    report = {
        "timestamp": datetime.now().isoformat(),
        "tests": [],
        "summary": "",
        "raw_data": {}
    }

    try:
        # Detailed configuration analysis
        global current_config, twilio_service, csv_processor

        report["raw_data"] = {
            "current_config": current_config,
            "config_file_exists": os.path.exists(CONFIG_FILE),
            "environment_vars": {
                "TWILIO_ACCOUNT_SID": bool(os.getenv('TWILIO_ACCOUNT_SID')),
                "TWILIO_AUTH_TOKEN": bool(os.getenv('TWILIO_AUTH_TOKEN')),
                "TWILIO_SENDER_TYPE": os.getenv('TWILIO_SENDER_TYPE'),
                "TWILIO_PHONE_NUMBER": bool(os.getenv('TWILIO_PHONE_NUMBER')),
                "TWILIO_SENDER_ID": bool(os.getenv('TWILIO_SENDER_ID')),
            },
            "global_services": {
                "twilio_service_type": str(type(twilio_service)) if twilio_service else None,
                "csv_processor_type": str(type(csv_processor)) if csv_processor else None,
                "twilio_service_is_none": twilio_service is None,
                "csv_processor_is_none": csv_processor is None
            }
        }

        # Test 1: Configuration
        config_ok = is_configured()
        report["tests"].append({
            "test": "Configuration Check",
            "status": "pass" if config_ok else "fail",
            "details": f"is_configured(): {config_ok}, twilio_service exists: {twilio_service is not None}, csv_processor exists: {csv_processor is not None}"
        })

        # Test 2: Try to reinitialize services if missing
        if not config_ok or not twilio_service or not csv_processor:
            try:
                logger.info("Attempting to reinitialize services...")
                init_result = initialize_services()
                report["tests"].append({
                    "test": "Service Reinitialization",
                    "status": "pass" if init_result else "fail",
                    "details": f"Reinitialization result: {init_result}, twilio_service now: {twilio_service is not None}, csv_processor now: {csv_processor is not None}"
                })

                # Update config_ok after reinitialization
                config_ok = is_configured()

            except Exception as e:
                report["tests"].append({
                    "test": "Service Reinitialization",
                    "status": "fail",
                    "details": f"Reinitialization failed: {str(e)}"
                })

        # Test 3: Service sync
        if csv_processor and twilio_service:
            csv_processor.twilio_service = twilio_service
            same_service = csv_processor.twilio_service is twilio_service
            report["tests"].append({
                "test": "Service Sync",
                "status": "pass" if same_service else "fail",
                "details": f"CSV processor uses same service: {same_service}"
            })
        else:
            report["tests"].append({
                "test": "Service Sync",
                "status": "fail",
                "details": f"Cannot sync - twilio_service: {twilio_service is not None}, csv_processor: {csv_processor is not None}"
            })

        # Test 4: Simple SMS test (only if configured)
        if config_ok and twilio_service:
            try:
                test_result = twilio_service.send_sms("+447960858925", "Quick troubleshoot test")
                report["tests"].append({
                    "test": "SMS Sending",
                    "status": "pass" if test_result.get("success") else "fail",
                    "details": f"SMS result: {test_result}"
                })
            except Exception as e:
                report["tests"].append({
                    "test": "SMS Sending",
                    "status": "fail",
                    "details": f"SMS error: {str(e)}"
                })
        else:
            report["tests"].append({
                "test": "SMS Sending",
                "status": "skip",
                "details": f"Skipped - config_ok: {config_ok}, twilio_service: {twilio_service is not None}"
            })

        # Test 5: Database
        try:
            test_count = db.query(SMSMessage).count()
            report["tests"].append({
                "test": "Database",
                "status": "pass",
                "details": f"Database accessible, {test_count} SMS messages in history"
            })
        except Exception as e:
            report["tests"].append({
                "test": "Database",
                "status": "fail",
                "details": f"Database error: {str(e)}"
            })

        # Summary
        failed_tests = [t for t in report["tests"] if t["status"] == "fail"]
        if not failed_tests:
            report["summary"] = "All basic tests passed. Issue likely in CSV processing or background tasks."
        else:
            report["summary"] = f"{len(failed_tests)} tests failed: {', '.join([t['test'] for t in failed_tests])}"

        return report

    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.post("/api/test/sms")
async def test_sms_simple(request: dict):
    """Simple SMS test endpoint for debugging"""
    try:
        logger.info(f"Test SMS request: {request}")

        # Check basic requirements
        if not request.get('to_number') or not request.get('message_body'):
            return {"success": False, "error": "Missing to_number or message_body"}

        # Check configuration
        logger.info(f"Is configured: {is_configured()}")
        logger.info(f"Has twilio service: {twilio_service is not None}")

        if not is_configured():
            return {"success": False, "error": "Not configured"}

        if not twilio_service:
            return {"success": False, "error": "Twilio service not initialized"}

        # Try to send SMS
        result = twilio_service.send_sms(request['to_number'], request['message_body'])
        logger.info(f"SMS result: {result}")

        return {"success": True, "result": result}

    except Exception as e:
        import traceback
        error_details = {
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc()
        }
        logger.error(f"Test SMS error: {error_details}")
        return {"success": False, "error_details": error_details}

@app.post("/api/test/csv")
async def test_csv_processing(file: UploadFile = File(...)):
    """Test CSV processing without sending SMS"""
    try:
        logger.info(f"Test CSV upload: {file.filename}")

        # Save uploaded file
        file_path = f"uploads/test_{uuid.uuid4()}_{file.filename}"
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        logger.info(f"Test file saved: {file_path}, size: {len(content)} bytes")

        # Validate CSV
        if csv_processor:
            validation_result = csv_processor.validate_csv_file(file_path)
            logger.info(f"CSV validation result: {validation_result}")

            # Clean up test file
            if os.path.exists(file_path):
                os.remove(file_path)

            return {"success": True, "validation": validation_result}
        else:
            return {"success": False, "error": "CSV processor not available"}

    except Exception as e:
        import traceback
        error_details = {
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc()
        }
        logger.error(f"Test CSV error: {error_details}")
        return {"success": False, "error_details": error_details}

@app.get("/api/test/bulk-status")
async def test_bulk_status():
    """Test bulk SMS endpoint status"""
    try:
        return {
            "success": True,
            "is_configured": is_configured(),
            "has_csv_processor": csv_processor is not None,
            "has_twilio_service": twilio_service is not None,
            "uploads_dir_exists": os.path.exists("uploads"),
            "current_config": {
                "sender_type": current_config.get('sender_type'),
                "has_account_sid": bool(current_config.get('account_sid')),
                "has_auth_token": bool(current_config.get('auth_token')),
                "has_phone_number": bool(current_config.get('phone_number')),
                "has_sender_id": bool(current_config.get('sender_id')),
            }
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.post("/api/sms/send", response_model=SMSResponse)
async def send_sms(sms_request: SMSRequest, db: Session = Depends(get_db)):
    """Send a single SMS message"""

    # Check for duplicate requests at application level
    if is_duplicate_request(sms_request.to_number, sms_request.message_body, "single_sms_endpoint"):
        return SMSResponse(
            success=False,
            message="Duplicate request detected - identical SMS was sent recently. Please wait before sending the same message again.",
            message_sid=None
        )

    # Check if Twilio is configured (outside try block to avoid catching HTTPException)
    if not is_configured():
        logger.error("Twilio not configured - missing configuration")
        logger.error(f"Current config: {current_config}")

        # Check what's specifically missing
        missing = []
        if not current_config.get('account_sid'):
            missing.append("Account SID")
        if not current_config.get('auth_token'):
            missing.append("Auth Token")
        if not current_config.get('sender_type'):
            missing.append("Sender Type")
        elif current_config.get('sender_type') == 'phone' and not current_config.get('phone_number'):
            missing.append("Phone Number")
        elif current_config.get('sender_type') == 'alphanumeric' and not current_config.get('sender_id'):
            missing.append("Sender ID")

        return SMSResponse(
            success=False,
            message=f"Twilio not configured. Missing: {', '.join(missing)}. Please configure in the Configuration tab."
        )

    if not twilio_service:
        logger.error("Twilio service not initialized")
        return SMSResponse(
            success=False,
            message="Twilio service not available. Please restart the application."
        )

    try:

        logger.info(f"Sending SMS to {sms_request.to_number}")
        logger.info(f"Current config: {current_config}")
        logger.info(f"Twilio service initialized: {twilio_service is not None}")

        # Send SMS via Twilio
        result = twilio_service.send_sms(sms_request.to_number, sms_request.message_body)
        logger.info(f"SMS send result: {result}")
        
        # Store in database (skip if duplicate blocked)
        if result.get("status") != "duplicate_blocked":
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
        else:
            logger.info(f"Skipping database record for duplicate blocked message to {sms_request.to_number}")
        
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
        import traceback
        error_msg = str(e) if str(e) else "Unknown error occurred while sending SMS"
        full_traceback = traceback.format_exc()
        logger.error(f"Error sending SMS: {error_msg}")
        logger.error(f"Full traceback: {full_traceback}")
        logger.exception("Exception details:")

        # Return more detailed error information
        return SMSResponse(
            success=False,
            message=f"Server error: {error_msg} | Type: {type(e).__name__} | Traceback available in logs"
        )

@app.post("/api/sms/bulk")
async def send_bulk_sms(
    file: UploadFile = File(...),
    message_template: str = Form(...),
    db: Session = Depends(get_db)
):
    """Send bulk SMS from CSV file"""
    try:
        import traceback
        import threading
        import time

        call_stack = traceback.format_stack()
        thread_id = threading.get_ident()
        timestamp = time.time()

        logger.info(f"🚨 BULK SMS ENDPOINT CALLED: File={file.filename}, Template='{message_template[:50]}...', thread_id={thread_id}, timestamp={timestamp}")
        logger.info(f"🔍 Call stack (last 3 frames): {call_stack[-3:]}")

        # Check for duplicate requests at application level
        if is_duplicate_request(f"bulk_{file.filename}", message_template, "bulk_sms_endpoint"):
            return {
                "success": False,
                "message": "Duplicate bulk SMS request detected - identical request was made recently. Please wait before submitting again."
            }

        # Check if Twilio is configured
        if not is_configured():
            logger.error("Bulk SMS failed: Twilio not configured")
            return {
                "success": False,
                "message": "Twilio not configured. Please configure Twilio credentials first."
            }

        if not csv_processor:
            logger.error("Bulk SMS failed: CSV processor not initialized")
            return {
                "success": False,
                "message": "CSV processor not available. Please restart the application."
            }

        # Validate file type
        if not file.filename or not file.filename.endswith('.csv'):
            logger.error(f"Bulk SMS failed: Invalid file type {file.filename}")
            return {
                "success": False,
                "message": "Only CSV files are allowed"
            }

        # Ensure uploads directory exists
        os.makedirs("uploads", exist_ok=True)

        # Save uploaded file
        file_path = f"uploads/{uuid.uuid4()}_{file.filename}"
        logger.info(f"Saving uploaded file to: {file_path}")

        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        logger.info(f"File saved successfully. Size: {len(content)} bytes")

        # Ensure CSV processor has the current twilio_service
        if csv_processor and twilio_service:
            csv_processor.twilio_service = twilio_service
            logger.info("Updated CSV processor with current Twilio service")

        # Process bulk SMS
        logger.info("Starting bulk SMS processing...")
        logger.info(f"CSV processor service available: {csv_processor.twilio_service is not None}")
        logger.info(f"Global twilio service available: {twilio_service is not None}")
        result = await csv_processor.process_bulk_sms(file_path, message_template, db)
        logger.info(f"Bulk SMS processing result: {result}")

        if result.get("success"):
            return {
                "success": True,
                "job_id": result["job_id"],
                "message": result["message"],
                "total_count": result["total_count"]
            }
        else:
            # Clean up file if processing failed
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup file {file_path}: {cleanup_error}")

            return {
                "success": False,
                "message": result.get("error", "Failed to process bulk SMS")
            }
    except Exception as e:
        import traceback
        error_msg = str(e) if str(e) else "Unknown error occurred during bulk SMS processing"
        full_traceback = traceback.format_exc()
        logger.error(f"Error processing bulk SMS: {error_msg}")
        logger.error(f"Full traceback: {full_traceback}")

        # Clean up file if it exists
        try:
            if 'file_path' in locals() and os.path.exists(file_path):
                os.remove(file_path)
        except Exception as cleanup_error:
            logger.warning(f"Cleanup error: {cleanup_error}")

        return {
            "success": False,
            "message": f"Server error during bulk SMS processing: {error_msg}"
        }

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

@app.get("/api/sms/jobs/{job_id}/details")
async def get_bulk_job_details(job_id: str, db: Session = Depends(get_db)):
    """Get detailed information about a specific bulk SMS job"""
    try:
        # Get the job
        job = db.query(BulkSMSJob).filter(BulkSMSJob.job_id == job_id).first()
        if not job:
            return {"success": False, "error": "Job not found"}

        # Get all messages for this job (using timestamp range)
        messages = db.query(SMSMessage).filter(
            and_(
                SMSMessage.created_at >= job.created_at,
                SMSMessage.created_at <= (job.completed_at or datetime.now())
            )
        ).order_by(SMSMessage.created_at.desc()).all()

        message_details = []
        for msg in messages:
            message_details.append({
                "message_sid": msg.message_sid,
                "to_number": msg.to_number,
                "from_number": msg.from_number,
                "status": msg.status,
                "error_code": msg.error_code,
                "error_message": msg.error_message,
                "cost": msg.cost,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "message_body_preview": msg.message_body[:100] + "..." if len(msg.message_body) > 100 else msg.message_body
            })

        return {
            "success": True,
            "job": {
                "job_id": job.job_id,
                "filename": job.filename,
                "status": job.status,
                "total_count": job.total_count,
                "sent_count": job.sent_count,
                "failed_count": job.failed_count,
                "message_template": job.message_template,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "error_message": job.error_message
            },
            "messages": message_details
        }

    except Exception as e:
        logger.error(f"Error fetching job details: {e}")
        return {"success": False, "error": str(e)}

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

@app.post("/api/debug/csv-processing")
async def debug_csv_processing(file: UploadFile = File(...)):
    """Debug CSV processing step by step to identify phone number issues"""

    debug_info = {
        "timestamp": datetime.now().isoformat(),
        "filename": file.filename,
        "steps": []
    }

    try:
        # Step 1: Save and read file
        os.makedirs("uploads", exist_ok=True)
        file_path = f"uploads/debug_{uuid.uuid4()}_{file.filename}"

        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        debug_info["steps"].append({
            "step": "File Save",
            "status": "success",
            "details": f"Saved {len(content)} bytes"
        })

        # Step 2: Read raw CSV content
        with open(file_path, 'r') as f:
            raw_content = f.read()

        debug_info["raw_csv_content"] = raw_content

        # Step 3: Parse with pandas
        import pandas as pd
        df = pd.read_csv(file_path)

        debug_info["pandas_info"] = {
            "columns": list(df.columns),
            "row_count": len(df),
            "sample_rows": df.to_dict('records')
        }

        # Step 4: Process each row individually
        row_details = []
        for index, row in df.iterrows():
            row_info = {
                "row_index": index,
                "raw_row_data": dict(row),
                "phone_processing": {}
            }

            # Get phone number
            phone_number = str(row['phone_number']).strip()
            row_info["phone_processing"]["original"] = phone_number

            # Test validation and formatting
            if csv_processor:
                is_valid = csv_processor._validate_phone_number(phone_number)
                row_info["phone_processing"]["is_valid"] = is_valid

                if is_valid:
                    try:
                        formatted = csv_processor._format_phone_number(phone_number)
                        row_info["phone_processing"]["formatted"] = formatted
                    except Exception as e:
                        row_info["phone_processing"]["format_error"] = str(e)

            row_details.append(row_info)

        debug_info["row_details"] = row_details

        # Step 5: Test CSV processor validation
        if csv_processor:
            validation_result = csv_processor.validate_csv_file(file_path)
            debug_info["csv_processor_validation"] = validation_result

        # Cleanup
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass

        return debug_info

    except Exception as e:
        import traceback
        debug_info["error_details"] = {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        return debug_info

@app.get("/api/safelist")
async def get_safe_list():
    """Get all phone numbers in the Twilio Global Safe List"""
    if not is_configured():
        raise HTTPException(status_code=400, detail="Twilio not configured")

    if not twilio_service:
        raise HTTPException(status_code=500, detail="Twilio service not available")

    try:
        logger.info("Attempting to fetch Twilio Global Safe List...")

        # Get all safe list entries - using the correct Twilio API path
        safe_list = twilio_service.client.usage.safe_list.list()

        logger.info(f"Successfully fetched {len(safe_list)} safe list entries")

        return {
            "success": True,
            "safe_list": [
                {
                    "phone_number": entry.phone_number,
                    "date_created": entry.date_created.isoformat() if entry.date_created else None,
                    "date_updated": entry.date_updated.isoformat() if entry.date_updated else None,
                    "sid": entry.sid
                }
                for entry in safe_list
            ],
            "total_count": len(safe_list)
        }
    except Exception as e:
        logger.error(f"Error fetching safe list: {e}")
        logger.error(f"Error type: {type(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch safe list: {str(e)}")

@app.post("/api/safelist/add")
async def add_to_safe_list(request: dict):
    """Add a phone number to the Twilio Global Safe List"""
    if not is_configured():
        raise HTTPException(status_code=400, detail="Twilio not configured")

    if not twilio_service:
        raise HTTPException(status_code=500, detail="Twilio service not available")

    phone_number = request.get('phone_number')
    if not phone_number:
        raise HTTPException(status_code=400, detail="Phone number is required")

    try:
        logger.info(f"Attempting to add {phone_number} to Twilio Global Safe List...")

        # Add to safe list
        safe_list_entry = twilio_service.client.usage.safe_list.create(
            phone_number=phone_number
        )

        logger.info(f"Successfully added {phone_number} to safe list with SID: {safe_list_entry.sid}")

        return {
            "success": True,
            "message": f"Phone number {phone_number} added to safe list",
            "phone_number": safe_list_entry.phone_number,
            "date_created": safe_list_entry.date_created.isoformat() if safe_list_entry.date_created else None,
            "sid": safe_list_entry.sid
        }
    except Exception as e:
        logger.error(f"Error adding to safe list: {e}")
        logger.error(f"Error type: {type(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to add to safe list: {str(e)}")

@app.delete("/api/safelist/remove")
async def remove_from_safe_list(request: dict):
    """Remove a phone number from the Twilio Global Safe List"""
    if not is_configured():
        raise HTTPException(status_code=400, detail="Twilio not configured")

    if not twilio_service:
        raise HTTPException(status_code=500, detail="Twilio service not available")

    phone_number = request.get('phone_number')
    if not phone_number:
        raise HTTPException(status_code=400, detail="Phone number is required")

    try:
        # Find and delete the safe list entry
        safe_list_entries = twilio_service.client.usage.safe_list.list(phone_number=phone_number)

        if not safe_list_entries:
            raise HTTPException(status_code=404, detail=f"Phone number {phone_number} not found in safe list")

        # Delete the entry (there should only be one)
        for entry in safe_list_entries:
            twilio_service.client.usage.safe_list(entry.sid).delete()

        return {
            "success": True,
            "message": f"Phone number {phone_number} removed from safe list"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing from safe list: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to remove from safe list: {str(e)}")

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
