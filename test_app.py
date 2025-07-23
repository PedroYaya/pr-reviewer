#!/usr/bin/env python3
"""
Simple test script for the GitHub App PR Reviewer
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_environment():
    """Test if all required environment variables are set"""
    required_vars = [
        'GITHUB_APP_ID',
        'GITHUB_PRIVATE_KEY', 
        'GITHUB_WEBHOOK_SECRET',
        'OPENAI_API_KEY'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file")
        return False
    
    print("✅ All environment variables are set")
    return True

def test_imports():
    """Test if all required modules can be imported"""
    try:
        from github_app import GitHubApp
        from ai_reviewer import AIReviewer
        from webhook_handler import WebhookHandler
        print("✅ All modules imported successfully")
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False

def test_github_app():
    """Test GitHub App initialization"""
    try:
        from github_app import GitHubApp
        app = GitHubApp()
        print("✅ GitHub App initialized successfully")
        return True
    except Exception as e:
        print(f"❌ GitHub App initialization failed: {e}")
        return False

def test_ai_reviewer():
    """Test AI Reviewer initialization"""
    try:
        from ai_reviewer import AIReviewer
        reviewer = AIReviewer()
        print("✅ AI Reviewer initialized successfully")
        return True
    except Exception as e:
        print(f"❌ AI Reviewer initialization failed: {e}")
        return False

def main():
    """Run all tests"""
    print("🧪 Testing GitHub App PR Reviewer...\n")
    
    tests = [
        ("Environment Variables", test_environment),
        ("Module Imports", test_imports),
        ("GitHub App", test_github_app),
        ("AI Reviewer", test_ai_reviewer),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"Testing {test_name}...")
        if test_func():
            passed += 1
        print()
    
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Your setup is ready.")
        return 0
    else:
        print("⚠️  Some tests failed. Please check the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 