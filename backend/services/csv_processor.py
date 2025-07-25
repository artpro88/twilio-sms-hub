"""
CSV processor service for bulk SMS operations
"""

import pandas as pd
import uuid
import asyncio
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
import sys
import os

# Add backend directory to path for imports
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from database import BulkSMSJob, SMSMessage, get_db
from services.twilio_service import TwilioService
import phonenumbers
import re
from datetime import datetime
import time

logger = logging.getLogger(__name__)

class CSVProcessor:
    """Service class for processing CSV files for bulk SMS"""
    
    def __init__(self, twilio_service=None):
        self.twilio_service = twilio_service
    
    def validate_csv_file(self, file_path: str) -> Dict[str, Any]:
        """
        Validate CSV file format and content
        
        Args:
            file_path: Path to the CSV file
            
        Returns:
            Dictionary with validation results
        """
        try:
            # Read CSV file
            df = pd.read_csv(file_path)
            
            # Check if required columns exist
            required_columns = ['phone_number']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                return {
                    "success": False,
                    "error": f"Missing required columns: {', '.join(missing_columns)}",
                    "required_columns": required_columns,
                    "found_columns": list(df.columns)
                }
            
            # Validate phone numbers
            valid_numbers = []
            invalid_numbers = []
            
            for index, row in df.iterrows():
                phone_number = str(row['phone_number']).strip()
                if self._validate_phone_number(phone_number):
                    # Format the phone number to E164 format with + prefix
                    formatted_number = self._format_phone_number(phone_number)
                    valid_numbers.append({
                        "row": index + 1,
                        "phone_number": formatted_number,
                        "original_phone_number": phone_number,
                        "name": row.get('name', ''),
                        "custom_field": row.get('custom_field', '')
                    })
                else:
                    invalid_numbers.append({
                        "row": index + 1,
                        "phone_number": phone_number,
                        "error": "Invalid phone number format"
                    })
            
            return {
                "success": True,
                "total_rows": len(df),
                "valid_numbers": valid_numbers,
                "invalid_numbers": invalid_numbers,
                "valid_count": len(valid_numbers),
                "invalid_count": len(invalid_numbers),
                "columns": list(df.columns)
            }
            
        except Exception as e:
            logger.error(f"Error validating CSV file: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _validate_phone_number(self, phone_number: str) -> bool:
        """
        Validate individual phone number

        Args:
            phone_number: Phone number to validate

        Returns:
            Boolean indicating if phone number is valid
        """
        try:
            # Remove any non-digit characters except +
            cleaned = re.sub(r'[^\d+]', '', phone_number)

            # Add + prefix if missing (assume international format)
            if not cleaned.startswith('+'):
                cleaned = '+' + cleaned

            # Parse the phone number
            parsed = phonenumbers.parse(cleaned, None)

            # Check if it's valid
            return phonenumbers.is_valid_number(parsed)
        except Exception as e:
            logger.warning(f"Phone number validation failed for {phone_number}: {e}")
            return False
    
    def _format_phone_number(self, phone_number: str) -> str:
        """
        Format phone number to E164 format

        Args:
            phone_number: Phone number to format

        Returns:
            Formatted phone number in E164 format
        """
        try:
            # Remove any non-digit characters except +
            cleaned = re.sub(r'[^\d+]', '', phone_number)

            # Add + prefix if missing (assume international format)
            if not cleaned.startswith('+'):
                cleaned = '+' + cleaned
                logger.info(f"Added + prefix to phone number: {phone_number} -> {cleaned}")

            # Parse the phone number
            parsed = phonenumbers.parse(cleaned, None)

            # Return in E164 format
            formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            logger.info(f"Formatted phone number: {phone_number} -> {formatted}")
            return formatted
        except Exception as e:
            logger.warning(f"Phone number formatting failed for {phone_number}: {e}")
            # If formatting fails, at least ensure + prefix
            if not phone_number.startswith('+'):
                return '+' + re.sub(r'[^\d]', '', phone_number)
            return phone_number
    
    async def process_bulk_sms(self, file_path: str, message_template: str, db: Session) -> Dict[str, Any]:
        """
        Process bulk SMS from CSV file
        
        Args:
            file_path: Path to the CSV file
            message_template: SMS message template
            db: Database session
            
        Returns:
            Dictionary with processing results
        """
        try:
            # Validate CSV file first
            logger.info(f"Starting CSV validation for file: {file_path}")
            validation_result = self.validate_csv_file(file_path)
            logger.info(f"CSV validation completed: {validation_result}")

            if not validation_result["success"]:
                logger.error(f"CSV validation failed: {validation_result}")
                return validation_result

            valid_numbers = validation_result["valid_numbers"]
            logger.info(f"Found {len(valid_numbers)} valid numbers: {[v['phone_number'] for v in valid_numbers]}")

            if not valid_numbers:
                logger.error("No valid phone numbers found in CSV file")
                return {
                    "success": False,
                    "error": "No valid phone numbers found in CSV file"
                }
            
            # Create bulk SMS job
            job_id = str(uuid.uuid4())
            logger.info(f"Creating bulk SMS job with ID: {job_id}")
            bulk_job = BulkSMSJob(
                job_id=job_id,
                filename=file_path.split('/')[-1],
                total_count=len(valid_numbers),
                message_template=message_template,
                status="processing"
            )

            db.add(bulk_job)
            db.commit()
            logger.info(f"Bulk SMS job created successfully: {job_id}")

            # Process SMS sending in background
            logger.info(f"Starting background SMS processing for job: {job_id}")
            # Ensure we pass the current twilio service to the background task
            current_service = self.twilio_service
            asyncio.create_task(self._send_bulk_sms(job_id, valid_numbers, message_template, db, current_service))
            
            return {
                "success": True,
                "job_id": job_id,
                "total_count": len(valid_numbers),
                "message": f"Bulk SMS job started. Processing {len(valid_numbers)} messages."
            }
            
        except Exception as e:
            logger.error(f"Error processing bulk SMS: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _send_bulk_sms(self, job_id: str, recipients: List[Dict], message_template: str, db: Session, twilio_service=None):
        """
        Send bulk SMS messages (background task)

        Args:
            job_id: Bulk SMS job ID
            recipients: List of recipient data
            message_template: SMS message template
            db: Database session
            twilio_service: Optional twilio service to use
        """
        sent_count = 0
        failed_count = 0
        
        try:
            logger.info(f"Starting bulk SMS job {job_id} with {len(recipients)} recipients")

            # Use passed service or fallback to instance service
            if twilio_service:
                self.twilio_service = twilio_service
                logger.info("Using passed twilio service")

            logger.info(f"Twilio service available: {self.twilio_service is not None}")

            # Check if Twilio service is available
            if not self.twilio_service:
                logger.error("Twilio service not available for bulk SMS - attempting to get global service")

                # Try to get the global twilio service from the main app
                try:
                    import sys
                    if 'run_app' in sys.modules:
                        run_app_module = sys.modules['run_app']
                        global_twilio_service = getattr(run_app_module, 'twilio_service', None)
                        if global_twilio_service:
                            self.twilio_service = global_twilio_service
                            logger.info("Successfully obtained global twilio service")
                        else:
                            logger.error("Global twilio service is also None")
                    else:
                        logger.error("run_app module not found in sys.modules")
                except Exception as e:
                    logger.error(f"Could not import global twilio service: {e}")

                # If still no service, fail the job
                if not self.twilio_service:
                    logger.error("No Twilio service available for bulk SMS")
                    job = db.query(BulkSMSJob).filter(BulkSMSJob.job_id == job_id).first()
                    if job:
                        job.status = BulkSMSJobStatus.FAILED
                        job.error_message = "Twilio service not available"
                        db.commit()
                    return

            # Process recipients in batches with rate limiting for large volumes
            # Configuration for high-volume processing (up to 10,000 contacts)
            batch_size = min(100, max(10, len(recipients) // 20))  # Dynamic batch size: 10-100 based on total
            delay_between_batches = 1.0  # 1 second between batches
            delay_between_messages = 0.05  # 50ms between individual messages (allows ~1200/min)

            # Twilio rate limits:
            # - Standard: 1 message/second (3600/hour)
            # - High Volume: Up to 100 messages/second with proper setup
            # Our settings: ~20 messages/second (safe for most accounts)

            total_recipients = len(recipients)
            logger.info(f"Processing {total_recipients} recipients in batches of {batch_size}")

            for batch_start in range(0, total_recipients, batch_size):
                batch_end = min(batch_start + batch_size, total_recipients)
                batch = recipients[batch_start:batch_end]
                batch_number = (batch_start // batch_size) + 1
                total_batches = (total_recipients + batch_size - 1) // batch_size

                logger.info(f"Processing batch {batch_number}/{total_batches} ({len(batch)} recipients)")

                for i, recipient in enumerate(batch):
                    try:
                        # Format phone number
                        phone_number = self._format_phone_number(recipient["phone_number"])

                        # Personalize message template
                        message_body = self._personalize_message(message_template, recipient)

                        # Check for duplicate requests at application level
                        try:
                            # Import the global duplicate checker
                            import sys
                            if 'run_app' in sys.modules:
                                run_app_module = sys.modules['run_app']
                                is_duplicate_request = getattr(run_app_module, 'is_duplicate_request', None)
                                if is_duplicate_request and is_duplicate_request(phone_number, message_body, "bulk_sms_background"):
                                    logger.info(f"Skipping duplicate request for {phone_number}")
                                    sent_count += 1  # Count as sent to avoid confusion
                                    continue
                        except Exception as e:
                            logger.warning(f"Could not check for duplicate request: {e}")

                        # Send SMS with rate limiting
                        logger.info(f"Sending SMS {batch_start + i + 1}/{total_recipients} to {phone_number}")
                        result = self.twilio_service.send_sms(phone_number, message_body)
                        logger.info(f"SMS result for {phone_number}: {result}")

                        # Rate limiting: delay between messages
                        if i < len(batch) - 1:  # Don't delay after the last message in batch
                            await asyncio.sleep(delay_between_messages)

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
                        logger.info(f"SMS sent successfully to {phone_number}")
                    else:
                        failed_count += 1
                        logger.error(f"SMS failed to {phone_number}: {result.get('error_message', 'Unknown error')}")
                    
                    # Enhanced rate limiting for large volumes
                    # Use async sleep instead of blocking sleep
                    # Reduced to 0.1 seconds for better throughput
                    # This allows ~600 messages per minute (well within Twilio limits)
                    
                except Exception as e:
                    logger.error(f"Error sending SMS to {recipient['phone_number']}: {e}")
                    failed_count += 1
                    
                    # Create failed SMS message record
                    sms_message = SMSMessage(
                        message_sid=None,
                        from_number="",
                        to_number=recipient["phone_number"],
                        message_body=message_template,
                        status="failed",
                        direction="outbound",
                        error_message=str(e)
                    )
                    
                    db.add(sms_message)
                
                # Batch processing: commit database changes after each batch
                try:
                    db.commit()
                    logger.info(f"Batch {batch_number}/{total_batches} completed. Progress: {sent_count} sent, {failed_count} failed")
                except Exception as commit_error:
                    logger.error(f"Database commit error: {commit_error}")

                # Update job progress after each batch
                try:
                    bulk_job = db.query(BulkSMSJob).filter(BulkSMSJob.job_id == job_id).first()
                    if bulk_job:
                        bulk_job.sent_count = sent_count
                        bulk_job.failed_count = failed_count
                        db.commit()
                        logger.info(f"Job progress updated: {sent_count}/{total_recipients} sent")
                except Exception as update_error:
                    logger.error(f"Job update error: {update_error}")

                # Rate limiting: delay between batches (except for the last batch)
                if batch_end < total_recipients:
                    logger.info(f"Waiting {delay_between_batches} seconds before next batch...")
                    await asyncio.sleep(delay_between_batches)
            
            # Mark job as completed
            bulk_job = db.query(BulkSMSJob).filter(BulkSMSJob.job_id == job_id).first()
            if bulk_job:
                bulk_job.status = "completed"
                bulk_job.completed_at = datetime.utcnow()
                db.commit()
            
            logger.info(f"Bulk SMS job {job_id} completed. Sent: {sent_count}, Failed: {failed_count}")
            
        except Exception as e:
            logger.error(f"Error in bulk SMS job {job_id}: {e}")
            
            # Mark job as failed
            bulk_job = db.query(BulkSMSJob).filter(BulkSMSJob.job_id == job_id).first()
            if bulk_job:
                bulk_job.status = "failed"
                bulk_job.completed_at = datetime.utcnow()
                db.commit()
    
    def _personalize_message(self, template: str, recipient: Dict) -> str:
        """
        Personalize message template with recipient data
        
        Args:
            template: Message template
            recipient: Recipient data
            
        Returns:
            Personalized message
        """
        message = template
        
        # Replace placeholders with recipient data
        if recipient.get("name"):
            message = message.replace("{name}", str(recipient["name"]))

        if recipient.get("custom_field"):
            message = message.replace("{custom_field}", str(recipient["custom_field"]))
        
        return message
