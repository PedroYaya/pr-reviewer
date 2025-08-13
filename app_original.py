#!/usr/bin/env python3
"""
GitHub App PR Reviewer - Main Application
"""

import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from webhook_handler import WebhookHandler

# Load environment variables
load_dotenv()

app = Flask(__name__)
webhook_handler = WebhookHandler()

@app.route('/')
def home():
    """Home endpoint for health checks"""
    return jsonify({
        "status": "ok",
        "message": "GitHub App PR Reviewer is running",
        "version": "1.0.0"
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle GitHub webhook events"""
    try:
        # Get the event type from headers
        event_type = request.headers.get('X-GitHub-Event')
        
        if not event_type:
            return jsonify({"error": "No event type provided"}), 400
        
        # Process the webhook
        result = webhook_handler.handle_webhook(
            event_type=event_type,
            payload=request.get_json(),
            signature=request.headers.get('X-Hub-Signature-256'),
            body=request.get_data()
        )
        
        return jsonify(result), 200
        
    except Exception as e:
        app.logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"🚀 Starting GitHub App PR Reviewer on port {port}")
    print(f"📝 Webhook endpoint: http://localhost:{port}/webhook")
    print(f"🔍 Health check: http://localhost:{port}/health")
    
    app.run(host='0.0.0.0', port=port, debug=debug) 