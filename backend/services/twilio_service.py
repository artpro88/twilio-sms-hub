"""
Twilio SMS service for sending and receiving SMS messages
"""

import os
from twilio.rest import Client
from twilio.base.exceptions import TwilioException
from typing import Optional, Dict, Any
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class TwilioService:
    """Service class for Twilio SMS operations"""

    # Class-level deduplication cache
    _recent_messages = {}

    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.sender_type = os.getenv("TWILIO_SENDER_TYPE", "phone")
        self.from_number = os.getenv("TWILIO_PHONE_NUMBER")
        self.sender_id = os.getenv("TWILIO_SENDER_ID")

        logger.info(f"Initializing TwilioService with sender_type: {self.sender_type}")
        logger.info(f"Phone number: {'***' if self.from_number else 'None'}")
        logger.info(f"Sender ID: {'***' if self.sender_id else 'None'}")

        # Determine the appropriate sender
        if self.sender_type == "phone":
            self.from_value = self.from_number
        else:
            self.from_value = self.sender_id

        logger.info(f"Using from_value: {'***' if self.from_value else 'None'}")

        if not self.account_sid:
            raise ValueError("Missing TWILIO_ACCOUNT_SID environment variable")
        if not self.auth_token:
            raise ValueError("Missing TWILIO_AUTH_TOKEN environment variable")
        if not self.from_value:
            if self.sender_type == "phone":
                raise ValueError("Missing TWILIO_PHONE_NUMBER environment variable for phone sender type")
            else:
                raise ValueError("Missing TWILIO_SENDER_ID environment variable for alphanumeric sender type")

        self.client = Client(self.account_sid, self.auth_token)
        logger.info("TwilioService initialized successfully")

    @classmethod
    def _is_duplicate(cls, to_number, message_body):
        """Check if this is a duplicate message sent within the last 5 seconds"""
        import time

        # Create a unique key for this message
        message_key = f"{to_number}:{message_body}"

        # Get current time
        current_time = time.time()

        # Check if we've sent this exact message recently (within 5 seconds)
        if message_key in cls._recent_messages:
            last_sent_time = cls._recent_messages[message_key]
            if current_time - last_sent_time < 5:  # 5 second deduplication window
                logger.warning(f"🚫 DUPLICATE MESSAGE BLOCKED: {to_number}, sent {current_time - last_sent_time:.2f} seconds ago")
                return True

        # Update the last sent time for this message
        cls._recent_messages[message_key] = current_time

        # Clean up old entries (older than 30 seconds)
        cls._recent_messages = {k: v for k, v in cls._recent_messages.items() if current_time - v < 30}

        return False

    def send_sms(self, to_number: str, message_body: str) -> Dict[str, Any]:
        """
        Send a single SMS message

        Args:
            to_number: Recipient phone number in E164 format
            message_body: Message content

        Returns:
            Dictionary with success status, message SID, and other details
        """
        import traceback
        call_stack = traceback.format_stack()
        logger.info(f"🚨 SMS SEND CALLED: to={to_number}, message='{message_body[:50]}...', caller_stack_depth={len(call_stack)}")
        logger.info(f"🔍 Call stack (last 3 frames): {call_stack[-3:]}")

        # Check for duplicate messages
        if self._is_duplicate(to_number, message_body):
            return {
                "success": True,
                "message_sid": "DUPLICATE_BLOCKED",
                "status": "duplicate_blocked",
                "direction": "outbound",
                "from_number": self.from_value,
                "to_number": to_number,
                "message_body": message_body,
                "price": "0",
                "price_unit": "USD",
                "error_code": None,
                "error_message": "Duplicate message blocked by deduplication system"
            }

        try:
            # Get the base URL with multiple fallback options
            base_url = os.getenv('BASE_URL')

            if not base_url:
                # Try Railway-specific environment variables
                railway_url = os.getenv('RAILWAY_STATIC_URL')
                railway_public_domain = os.getenv('RAILWAY_PUBLIC_DOMAIN')

                if railway_url:
                    base_url = f"https://{railway_url}"
                elif railway_public_domain:
                    base_url = f"https://{railway_public_domain}"
                else:
                    # Manual override for Railway - you can set this in Railway dashboard
                    manual_url = os.getenv('WEBHOOK_BASE_URL')
                    if manual_url:
                        base_url = manual_url
                    else:
                        # If we can't determine the URL, don't use status callback
                        logger.warning("Cannot determine base URL, sending SMS without status callback")
                        base_url = None

            logger.info(f"Using base URL for status callback: {base_url}")

            # Create message with or without status callback
            message_params = {
                'body': message_body,
                'from_': self.from_value,
                'to': to_number
            }

            if base_url and not base_url.startswith('http://localhost'):
                message_params['status_callback'] = f"{base_url}/api/webhooks/status"
                logger.info(f"Status callback URL: {message_params['status_callback']}")
            else:
                logger.info("Sending SMS without status callback (local development or unknown URL)")

            message = self.client.messages.create(**message_params)
            
            logger.info(f"SMS sent successfully. SID: {message.sid}")
            
            return {
                "success": True,
                "message_sid": message.sid,
                "status": message.status,
                "direction": message.direction,
                "from_number": message.from_,
                "to_number": message.to,
                "message_body": message.body,
                "price": message.price,
                "price_unit": message.price_unit,
                "error_code": message.error_code,
                "error_message": message.error_message
            }
            
        except TwilioException as e:
            logger.error(f"Twilio error sending SMS: {e}")
            return {
                "success": False,
                "error_code": getattr(e, 'code', None),
                "error_message": str(e),
                "message_sid": None
            }
        except Exception as e:
            logger.error(f"Unexpected error sending SMS: {e}")
            return {
                "success": False,
                "error_message": str(e),
                "message_sid": None
            }
    
    def get_message_status(self, message_sid: str) -> Dict[str, Any]:
        """
        Get the status of a sent message
        
        Args:
            message_sid: Twilio message SID
            
        Returns:
            Dictionary with message details and status
        """
        try:
            message = self.client.messages(message_sid).fetch()
            
            return {
                "success": True,
                "message_sid": message.sid,
                "status": message.status,
                "direction": message.direction,
                "from_number": message.from_,
                "to_number": message.to,
                "message_body": message.body,
                "price": message.price,
                "price_unit": message.price_unit,
                "error_code": message.error_code,
                "error_message": message.error_message,
                "date_created": message.date_created,
                "date_updated": message.date_updated,
                "date_sent": message.date_sent
            }
            
        except TwilioException as e:
            logger.error(f"Twilio error fetching message status: {e}")
            return {
                "success": False,
                "error_message": str(e)
            }
        except Exception as e:
            logger.error(f"Unexpected error fetching message status: {e}")
            return {
                "success": False,
                "error_message": str(e)
            }
    
    def validate_phone_number(self, phone_number: str) -> Dict[str, Any]:
        """
        Validate a phone number using Twilio Lookup API
        
        Args:
            phone_number: Phone number to validate
            
        Returns:
            Dictionary with validation results
        """
        try:
            phone_number_info = self.client.lookups.v1.phone_numbers(phone_number).fetch()
            
            return {
                "success": True,
                "phone_number": phone_number_info.phone_number,
                "country_code": phone_number_info.country_code,
                "national_format": phone_number_info.national_format
            }
            
        except TwilioException as e:
            logger.error(f"Phone number validation error: {e}")
            return {
                "success": False,
                "error_message": str(e)
            }
        except Exception as e:
            logger.error(f"Unexpected error validating phone number: {e}")
            return {
                "success": False,
                "error_message": str(e)
            }
    
    def get_account_balance(self) -> Dict[str, Any]:
        """
        Get Twilio account balance
        
        Returns:
            Dictionary with account balance information
        """
        try:
            balance = self.client.api.v2010.accounts(self.account_sid).balance.fetch()
            
            return {
                "success": True,
                "balance": balance.balance,
                "currency": balance.currency
            }
            
        except TwilioException as e:
            logger.error(f"Error fetching account balance: {e}")
            return {
                "success": False,
                "error_message": str(e)
            }
        except Exception as e:
            logger.error(f"Unexpected error fetching account balance: {e}")
            return {
                "success": False,
                "error_message": str(e)
            }
