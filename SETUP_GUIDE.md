# Twilio SMS Integration - Quick Setup Guide

## 🚀 Quick Start

### 1. Get Twilio Credentials
1. Sign up at [Twilio](https://www.twilio.com/try-twilio)
2. Get your credentials from the [Twilio Console](https://console.twilio.com/):
   - Account SID
   - Auth Token
   - Phone Number (purchase one if needed)

### 2. Setup Application
```bash
# Navigate to the twilio-sms directory
cd twilio-sms

# Run the setup script
python start.py
```

The setup script will:
- ✅ Check Python version (3.8+ required)
- 📦 Install dependencies
- 🔧 Create .env file from template
- 📁 Create necessary directories
- 🚀 Start the application

### 3. Configure Environment
Edit the `.env` file with your Twilio credentials:
```env
TWILIO_ACCOUNT_SID=your_account_sid_here
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+1234567890
```

### 4. Access Application
- **Web Interface**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

## 📱 Features Overview

### Send Single SMS
- Enter phone number (with country code)
- Type message (up to 1600 characters)
- Real-time delivery tracking

### Bulk SMS from CSV
- Upload CSV with phone numbers
- Use message templates with placeholders
- Track job progress in real-time

### Message History
- View all sent/received messages
- Filter by status and direction
- See costs and delivery times

### Statistics Dashboard
- Total messages sent/delivered/failed
- Cost tracking
- Daily and monthly usage

## 📋 CSV Format

Your CSV file should have these columns:
```csv
phone_number,name,custom_field
+1234567890,John Doe,Premium Customer
+1987654321,Jane Smith,Regular Customer
```

**Required**: `phone_number` (with country code)
**Optional**: `name`, `custom_field` (or any custom columns)

### Message Templates
Use placeholders in your message template:
```
Hello {name}, this is a message for you as a {custom_field}!
```

## 🔧 Manual Setup (Alternative)

If you prefer manual setup:

### 1. Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### 2. Create Environment File
```bash
cp .env.example .env
# Edit .env with your Twilio credentials
```

### 3. Run Application
```bash
python run_app.py
```

## 🔗 Webhook Configuration

For receiving SMS and delivery updates:

### 1. Incoming SMS Webhook
- Go to [Twilio Phone Numbers](https://console.twilio.com/us1/develop/phone-numbers/manage/incoming)
- Click your phone number
- Set webhook URL: `https://yourdomain.com/api/webhooks/incoming`

### 2. Status Callbacks
Status callbacks are automatically configured when sending messages.

## 🛡️ Production Deployment

For production use:

### 1. Security
- Use HTTPS for webhooks
- Set strong SECRET_KEY
- Implement authentication
- Validate webhook signatures

### 2. Environment Variables
```env
DEBUG=False
SECRET_KEY=your_strong_secret_key
BASE_URL=https://yourdomain.com
```

### 3. Database
Consider using PostgreSQL or MySQL for production:
```env
DATABASE_URL=postgresql://user:password@localhost/sms_app
```

## 🐛 Troubleshooting

### Common Issues

**"Missing Twilio configuration"**
- Check .env file has correct credentials
- Verify credentials in Twilio Console

**Phone number validation errors**
- Include country code (+1 for US)
- Use E.164 format (+1234567890)

**CSV upload fails**
- Ensure CSV has `phone_number` column
- Check phone number format
- Verify file is valid CSV

**Webhooks not working**
- Use HTTPS for production webhooks
- Check webhook URLs are publicly accessible
- Review Twilio webhook logs

## 📞 Support

- Check the main README.md for detailed documentation
- Review API docs at `/docs` when running
- Check Twilio's [documentation](https://www.twilio.com/docs)

## 🎯 Next Steps

1. **Test with sample data**: Use the included `sample_contacts.csv`
2. **Configure webhooks**: Set up incoming SMS handling
3. **Customize**: Modify templates and styling as needed
4. **Deploy**: Set up production environment with HTTPS

Happy texting! 📱✨
