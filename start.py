#!/usr/bin/env python3
"""
Startup script for Twilio SMS Integration
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def check_python_version():
    """Check if Python version is 3.8 or higher"""
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        print(f"Current version: {sys.version}")
        return False
    print(f"✅ Python version: {sys.version.split()[0]}")
    return True

def check_pip():
    """Check if pip is available"""
    try:
        subprocess.run([sys.executable, "-m", "pip", "--version"], 
                      check=True, capture_output=True)
        print("✅ pip is available")
        return True
    except subprocess.CalledProcessError:
        print("❌ pip is not available")
        return False

def install_dependencies():
    """Install required dependencies"""
    print("\n📦 Installing dependencies...")
    
    requirements_file = Path("backend/requirements.txt")
    if not requirements_file.exists():
        print("❌ requirements.txt not found")
        return False
    
    try:
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-r", str(requirements_file)
        ], check=True)
        print("✅ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False

def check_env_file():
    """Check if .env file exists and has required variables"""
    env_file = Path(".env")
    env_example = Path(".env.example")
    
    if not env_file.exists():
        if env_example.exists():
            print("\n⚠️  .env file not found. Creating from .env.example...")
            shutil.copy(env_example, env_file)
            print("✅ .env file created")
            print("\n🔧 Please edit .env file with your Twilio credentials:")
            print("   - TWILIO_ACCOUNT_SID")
            print("   - TWILIO_AUTH_TOKEN") 
            print("   - TWILIO_PHONE_NUMBER")
            return False
        else:
            print("❌ .env.example file not found")
            return False
    
    # Check if required variables are set
    required_vars = [
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN", 
        "TWILIO_PHONE_NUMBER"
    ]
    
    missing_vars = []
    with open(env_file, 'r') as f:
        content = f.read()
        for var in required_vars:
            if f"{var}=your_" in content or f"{var}=" not in content:
                missing_vars.append(var)
    
    if missing_vars:
        print(f"\n⚠️  Missing or incomplete environment variables: {', '.join(missing_vars)}")
        print("Please edit .env file with your actual Twilio credentials")
        return False
    
    print("✅ Environment configuration looks good")
    return True

def create_directories():
    """Create necessary directories"""
    directories = ["uploads", "backend/uploads"]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
    
    print("✅ Directories created")

def start_application():
    """Start the FastAPI application"""
    print("\n🚀 Starting Twilio SMS Integration...")
    print("📱 Web Interface: http://localhost:8000")
    print("📚 API Documentation: http://localhost:8000/docs")
    print("\nPress Ctrl+C to stop the server\n")

    try:
        # Start the application using run_app.py
        subprocess.run([sys.executable, "run_app.py"])

    except KeyboardInterrupt:
        print("\n\n👋 Server stopped")
    except Exception as e:
        print(f"\n❌ Error starting application: {e}")

def main():
    """Main setup and startup function"""
    print("🔧 Twilio SMS Integration Setup")
    print("=" * 40)
    
    # Check system requirements
    if not check_python_version():
        return
    
    if not check_pip():
        return
    
    # Install dependencies
    if not install_dependencies():
        return
    
    # Check environment configuration
    if not check_env_file():
        print("\n⚠️  Please configure your .env file and run this script again")
        return
    
    # Create directories
    create_directories()
    
    print("\n✅ Setup complete!")
    
    # Ask user if they want to start the application
    response = input("\nStart the application now? (y/n): ").lower().strip()
    if response in ['y', 'yes']:
        start_application()
    else:
        print("\n📝 To start the application later, run:")
        print("   python run_app.py")

if __name__ == "__main__":
    main()
