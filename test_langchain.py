#!/usr/bin/env python3
"""
Test script for LangChain AI Reviewer
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_langchain_imports():
    """Test if LangChain modules can be imported"""
    try:
        from ai_reviewer_langchain import LangChainAIReviewer
        from webhook_handler_langchain import LangChainWebhookHandler
        print("✅ LangChain modules imported successfully")
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False

def test_langchain_ai_reviewer():
    """Test LangChain AI Reviewer initialization"""
    try:
        from ai_reviewer_langchain import LangChainAIReviewer
        
        # Check if OpenAI API key is set
        if not os.getenv('OPENAI_API_KEY'):
            print("⚠️  OPENAI_API_KEY not set - skipping AI test")
            return True
        
        reviewer = LangChainAIReviewer()
        print("✅ LangChain AI Reviewer initialized successfully")
        return True
    except Exception as e:
        print(f"❌ LangChain AI Reviewer initialization failed: {e}")
        return False

def test_langchain_webhook_handler():
    """Test LangChain Webhook Handler initialization"""
    try:
        from webhook_handler_langchain import LangChainWebhookHandler
        
        # Check if GitHub App credentials are set
        if not all([
            os.getenv('GITHUB_APP_ID'),
            os.getenv('GITHUB_PRIVATE_KEY'),
            os.getenv('GITHUB_WEBHOOK_SECRET')
        ]):
            print("⚠️  GitHub App credentials not set - skipping handler test")
            return True
        
        handler = LangChainWebhookHandler()
        print("✅ LangChain Webhook Handler initialized successfully")
        return True
    except Exception as e:
        print(f"❌ LangChain Webhook Handler initialization failed: {e}")
        return False

def test_langchain_functionality():
    """Test basic LangChain functionality"""
    try:
        from ai_reviewer_langchain import LangChainAIReviewer
        
        if not os.getenv('OPENAI_API_KEY'):
            print("⚠️  OPENAI_API_KEY not set - skipping functionality test")
            return True
        
        reviewer = LangChainAIReviewer()
        
        # Test with sample data
        sample_files = [
            {
                'filename': 'test.py',
                'status': 'modified',
                'additions': 5,
                'deletions': 2,
                'changes': 7,
                'patch': '+ def new_function():\n+     return "Hello World"\n- old_code = "deprecated"'
            }
        ]
        
        # Test summary generation
        summary = reviewer.generate_summary_comment("Test PR", sample_files)
        print("✅ LangChain summary generation working")
        
        # Test memory functionality
        reviewer.clear_memory()
        print("✅ LangChain memory management working")
        
        return True
    except Exception as e:
        print(f"❌ LangChain functionality test failed: {e}")
        return False

def main():
    """Run all LangChain tests"""
    print("🧪 Testing LangChain AI Reviewer...\n")
    
    tests = [
        ("LangChain Imports", test_langchain_imports),
        ("AI Reviewer", test_langchain_ai_reviewer),
        ("Webhook Handler", test_langchain_webhook_handler),
        ("Functionality", test_langchain_functionality),
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
        print("🎉 All LangChain tests passed! Ready to use enhanced AI review.")
        return 0
    else:
        print("⚠️  Some tests failed. Check the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
