# Twilio SMS Integration

A comprehensive web application for sending and receiving SMS messages using Twilio's API. Features include single SMS sending, bulk SMS from CSV files, message history tracking, and real-time statistics.

## 🚀 Features

### Core Functionality
- **Single SMS Sending**: Send individual SMS messages with real-time delivery tracking
- **Bulk SMS from CSV**: Upload CSV files and send personalized messages to multiple recipients
- **SMS Receiving**: Handle incoming SMS messages via Twilio webhooks
- **Message History**: View complete history of sent and received messages
- **Real-time Statistics**: Track delivery rates, costs, and usage metrics
- **Account Balance**: Monitor your Twilio account balance

### Advanced Features
- **Phone Number Validation**: Automatic validation and formatting of phone numbers
- **Message Templates**: Use placeholders for personalized bulk messages
- **Rate Limiting**: Built-in rate limiting to prevent API abuse
- **Error Handling**: Comprehensive error tracking and reporting
- **Responsive Design**: Mobile-friendly interface
- **Real-time Updates**: Auto-refreshing data and progress tracking

## 📋 Requirements

- Python 3.8+
- Twilio Account (with Account SID, Auth Token, and Phone Number)
- Modern web browser

## 🛠️ Installation

### 1. Clone or Download
```bash
# If this is part of a larger project, navigate to the twilio-sms directory
cd twilio-sms
```

### 2. Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### 3. Configure Environment Variables
Copy the example environment file and configure your Twilio credentials:

```bash
cp .env.example .env
```

Edit `.env` file with your Twilio credentials:
```env
# Twilio Configuration
TWILIO_ACCOUNT_SID=your_account_sid_here
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+1234567890

# Database Configuration
DATABASE_URL=sqlite:///./sms_app.db

# Application Configuration
SECRET_KEY=your_secret_key_here
DEBUG=True
HOST=0.0.0.0
PORT=8000

# Rate Limiting
MAX_SMS_PER_MINUTE=10
MAX_BULK_SMS_SIZE=1000
```

### 4. Get Twilio Credentials

1. Sign up for a [Twilio account](https://www.twilio.com/try-twilio)
2. Get your Account SID and Auth Token from the [Twilio Console](https://console.twilio.com/)
3. Purchase a phone number from the [Phone Numbers section](https://console.twilio.com/us1/develop/phone-numbers/manage/incoming)

## 🚀 Running the Application

### Start the Server
```bash
cd backend/app
python main.py
```

The application will be available at:
- **Web Interface**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

## 📱 Usage

### Single SMS
1. Navigate to the "Send SMS" tab
2. Enter the recipient's phone number (include country code, e.g., +1234567890)
3. Type your message (up to 1600 characters)
4. Click "Send SMS"

### Bulk SMS from CSV
1. Navigate to the "Bulk SMS" tab
2. Prepare a CSV file with the following format:
   ```csv
   phone_number,name,custom_field
   +1234567890,John Doe,Premium Customer
   +1987654321,Jane Smith,Regular Customer
   ```
3. Upload your CSV file
4. Create a message template using placeholders:
   ```
   Hello {name}, this is a personalized message for you as a {custom_field}!
   ```
5. Click "Upload and Send"

### CSV File Requirements
- **Required column**: `phone_number` (must include country code)
- **Optional columns**: `name`, `custom_field` (or any custom column names)
- **Placeholders**: Use `{column_name}` in your message template

### Message History
- View all sent and received messages
- Filter by status (sent, delivered, failed)
- See delivery timestamps and costs

### Statistics Dashboard
- Total messages sent/delivered/failed
- Total cost tracking
- Daily and monthly usage statistics

## 🔧 API Endpoints

### SMS Operations
- `POST /api/sms/send` - Send single SMS
- `POST /api/sms/bulk` - Send bulk SMS from CSV
- `GET /api/sms/history` - Get message history
- `GET /api/sms/stats` - Get SMS statistics

### Job Management
- `GET /api/sms/jobs` - Get bulk SMS job status

### Webhooks
- `POST /api/webhooks/status` - Twilio status callback
- `POST /api/webhooks/incoming` - Incoming SMS webhook

### Utility
- `GET /api/account/balance` - Get Twilio account balance
- `POST /api/validate-csv` - Validate CSV file format

## 🔗 Webhook Configuration

To receive SMS messages and delivery status updates, configure webhooks in your Twilio Console:

### For Incoming Messages
1. Go to [Phone Numbers](https://console.twilio.com/us1/develop/phone-numbers/manage/incoming)
2. Click on your phone number
3. Set the webhook URL to: `https://yourdomain.com/api/webhooks/incoming`

### For Status Callbacks
Status callbacks are automatically configured when sending messages.

## 🛡️ Security Considerations

- Store Twilio credentials securely (use environment variables)
- Implement rate limiting for production use
- Validate webhook signatures in production
- Use HTTPS for webhook endpoints
- Sanitize user inputs
- Implement proper authentication for production deployment

## 📊 Database Schema

The application uses SQLite by default with the following tables:
- `sms_messages` - Store all SMS messages
- `bulk_sms_jobs` - Track bulk SMS job progress
- `webhook_logs` - Log webhook events

## 🔧 Customization

### Rate Limiting
Adjust rate limits in the `.env` file:
```env
MAX_SMS_PER_MINUTE=10
MAX_BULK_SMS_SIZE=1000
```

### Database
Change database by updating the `DATABASE_URL` in `.env`:
```env
# PostgreSQL example
DATABASE_URL=postgresql://user:password@localhost/sms_app

# MySQL example
DATABASE_URL=mysql://user:password@localhost/sms_app
```

## 🐛 Troubleshooting

### Common Issues

1. **"Missing Twilio configuration" error**
   - Ensure all Twilio credentials are set in `.env` file
   - Verify credentials are correct in Twilio Console

2. **Phone number validation errors**
   - Include country code (e.g., +1 for US)
   - Use E.164 format (+1234567890)

3. **CSV upload fails**
   - Ensure CSV has required `phone_number` column
   - Check phone number format in CSV
   - Verify file is valid CSV format

4. **Webhooks not working**
   - Ensure webhook URLs are publicly accessible
   - Use HTTPS for production webhooks
   - Check Twilio webhook logs in Console

## 📝 License

This project is open source and available under the MIT License.

## 🤝 Support

For issues and questions:
1. Check the troubleshooting section above
2. Review Twilio's [documentation](https://www.twilio.com/docs)
3. Check the API documentation at `/docs` when running the application
