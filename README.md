# 📱 Twilio SMS Hub

A modern, professional web application for sending and receiving SMS messages using Twilio's API. Features a beautiful Bootstrap interface with support for both traditional phone numbers and alphanumeric sender IDs.

![SMS Hub Interface](https://img.shields.io/badge/Interface-Bootstrap%205-blue)
![Twilio API](https://img.shields.io/badge/API-Twilio-red)
![Python](https://img.shields.io/badge/Python-3.8%2B-green)

## 🌟 Deploy for Real Testing

**Yes, you can deploy this to GitHub and test with real Twilio webhooks!**

### Quick Deploy Options:

#### Option 1: Railway (Free, Recommended)
1. Fork this repository to your GitHub
2. Go to [Railway](https://railway.app/) and sign up
3. Create new project from GitHub repo
4. Set environment variables (see below)
5. Deploy - you'll get a public HTTPS URL!

#### Option 2: Render (Free)
1. Go to [Render](https://render.com/)
2. Connect your GitHub repository
3. Create a new Web Service
4. Deploy - you'll get a public HTTPS URL!

## ✨ Key Features

- **🎨 Modern Bootstrap Interface** - Professional, responsive design
- **📞 Dual Sender Support** - Phone numbers AND alphanumeric sender IDs
- **📤 Single & Bulk SMS** - Send individual messages or CSV campaigns
- **📊 Real-time Analytics** - Delivery tracking and cost monitoring
- **📋 Message History** - Complete audit trail with filtering
- **�� Webhook Integration** - Automatic status updates and incoming SMS
- **🌍 International Support** - Global SMS with proper validation

## 📞 Webhook Configuration for Real Testing

Once deployed, configure these webhooks in your [Twilio Console](https://console.twilio.com/us1/develop/phone-numbers/manage/incoming):

### Primary Handler (A message comes in):
```
https://your-app-name.railway.app/api/webhooks/incoming
```

### Fallback Handler (Primary handler fails):
```
https://your-app-name.railway.app/api/webhooks/incoming
```

**The app provides copy-to-clipboard buttons for these URLs!**

## 🔧 Environment Variables for Deployment

Set these in your deployment platform:

```env
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_SENDER_TYPE=phone  # or "alphanumeric"
TWILIO_PHONE_NUMBER=+1234567890  # if using phone
TWILIO_SENDER_ID=YourBrand  # if using alphanumeric
```

## 📱 Alphanumeric Sender IDs

### Supported Regions:
- ✅ Europe (UK, Germany, France, etc.)
- ✅ Asia (India, Singapore, etc.)
- ✅ Australia
- ❌ United States (use phone numbers)
- ❌ Canada (use phone numbers)

### Requirements:
- Maximum 11 characters
- Letters, numbers, and spaces only
- One-way messaging (no replies)

## 🎯 Real Testing Workflow

1. **Deploy to Railway/Render** - Get public HTTPS URL
2. **Configure Twilio webhooks** - Use your deployed URL
3. **Test incoming SMS** - Send SMS to your Twilio number
4. **Test outgoing SMS** - Send from the web interface
5. **Monitor in real-time** - See delivery status and costs

---

**Ready for real-world SMS testing with live webhooks! 🚀**
