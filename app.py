#!/usr/bin/env python3
"""
GitHub App PR Reviewer with LangChain - Main Application
Enhanced version with better AI capabilities
"""

import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from webhook_handler import LangChainWebhookHandler

# Load environment variables TEST COMMENT FOR PR asdsd
# TEST COMMENT FOR PR 2
# TEST COMMENT FOR PR 3
# TEST COMMENT FOR PR 4asdasdasd
ñaskdsakdñ
load_dotenv()asdsadasdasasdasdasd
adsadasdasdsa
# BAD CODE - OBVIOUSLY PROBLEMATIC FOR AI REVIEW
def bad_function():
    password = "123456"  # Hardcoded password - SECURITY RISK!
    secret_key = "super_secret_key_exposed"  # Exposed secret - DANGEROUS!
    global_var = "global"  # Global variable - BAD PRACTICE!
    
    # Dangerous eval - MAJOR SECURITY RISK!
    eval("print('dangerous code execution')")
    
    # SQL injection vulnerability
    query = f"SELECT * FROM users WHERE password = '{password}'"
    
    # Memory leak
    big_list = []
    for i in range(1000000):
        big_list.append(i)
    
    return password + secret_key + global_var

# More bad practices
try:
    result = 10 / 0  # Division by zero
except:
    pass  # Silent exception - BAD!

# Unused imports and variables
import sys  # Unused import
unused_var = "never used"

app = Flask(__name__)
webhook_handler = LangChainWebhookHandler()

@app.route('/')
def home():
    """Home endpoint for health checks"""
    return jsonify({
        "status": "ok",
        "message": "GitHub App PR Reviewer with LangChain is running",
        "version": "2.0.0",
        "ai_engine": "LangChain + GPT-4",
        "features": [
            "Enhanced AI code review",
            "Context memory between reviews",
            "Intelligent prompt templates",
            "Better code analysis"
        ]
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle GitHub webhook events with LangChain AI"""
    try:
        print("🚀 WEBHOOK RECEIVED!")
        print(f"📋 Headers: {dict(request.headers)}")
        print(f"📦 Body length: {len(request.get_data())} bytes")
        
        # Get the event type from headers
        event_type = request.headers.get('X-GitHub-Event')
        print(f"🎯 Event type: {event_type}")
        
        if not event_type:
            print("❌ No event type provided")
            return jsonify({"error": "No event type provided"}), 400
        
        # Get payload
        payload = request.get_json()
        print(f"📄 Payload keys: {list(payload.keys()) if payload else 'None'}")
        
        # Get signature
        signature = request.headers.get('X-Hub-Signature-256')
        print(f"🔐 Signature: {signature[:20] if signature else 'None'}...")
        
        print("🤖 Processing with LangChain...")
        
        # Process the webhook with LangChain
        result = webhook_handler.handle_webhook(
            event_type=event_type,
            payload=payload,
            signature=signature,
            body=request.get_data()
        )
        
        print(f"✅ Result: {result}")
        return jsonify(result), 200
        
    except Exception as e:
        print(f"💥 ERROR in webhook: {str(e)}")
        import traceback
        traceback.print_exc()
        app.logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "ai_engine": "LangChain",
        "model": "GPT-4"
    })

@app.route('/clear-memory')
def clear_memory():
    """Clear AI memory (useful for testing)"""
 
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to clear memory: {str(e)}"
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"🚀 Starting GitHub App PR Reviewer with LangChain on port {port}")
    print(f"🤖 AI Engine: LangChain + GPT-4")
    print(f"📝 Webhook endpoint: http://localhost:{port}/webhook")
    print(f"🔍 Health check: http://localhost:{port}/health")
    print(f"🧠 Memory management: http://localhost:{port}/clear-memory")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
