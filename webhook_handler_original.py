"""
Webhook Handler Module
Processes GitHub webhook events and orchestrates the review process
"""

import hmac
import hashlib
import json
import logging
from typing import Dict, Any, Optional
from github_app import GitHubApp
from ai_reviewer import AIReviewer


class WebhookHandler:
    def __init__(self):
        self.github_app = GitHubApp()
        self.ai_reviewer = AIReviewer()
        self.logger = logging.getLogger(__name__)
    
    def handle_webhook(self, event_type: str, payload: Dict[str, Any], 
                      signature: Optional[str] = None, body: Optional[bytes] = None) -> Dict[str, Any]:
        """
        Handle incoming webhook events from GitHub
        
        Args:
            event_type: Type of GitHub event (e.g., 'pull_request')
            payload: The webhook payload
            signature: Webhook signature for verification
            body: Raw request body for signature verification
            
        Returns:
            Dict containing the result of processing
        """
        try:
            # Verify webhook signature if provided
            if signature and body:
                if not self._verify_signature(signature, body):
                    return {"error": "Invalid webhook signature"}
            
            # Handle different event types
            if event_type == 'pull_request':
                return self._handle_pull_request_event(payload)
            elif event_type == 'ping':
                return {"message": "Webhook received successfully"}
            else:
                return {"message": f"Event type '{event_type}' not handled"}
                
        except Exception as e:
            self.logger.error(f"Error handling webhook: {str(e)}")
            return {"error": f"Internal error: {str(e)}"}
    
    def _verify_signature(self, signature: str, body: bytes) -> bool:
        """Verify the webhook signature"""
        if not signature.startswith('sha256='):
            return False
        
        expected_signature = signature[7:]  # Remove 'sha256=' prefix
        webhook_secret = self.github_app.webhook_secret.encode('utf-8')
        
        computed_signature = hmac.new(
            webhook_secret,
            body,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, computed_signature)
    
    def _handle_pull_request_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle pull request events"""
        action = payload.get('action')
        pr_data = payload.get('pull_request', {})
        
        # Only process on PR open, synchronize, or reopen
        if action not in ['opened', 'synchronize', 'reopened']:
            return {"message": f"PR action '{action}' not processed"}
        
        try:
            # Extract PR information
            pr_number = pr_data.get('number')
            pr_title = pr_data.get('title', '')
            pr_description = pr_data.get('body', '')
            
            # Extract repository information
            repo_data = payload.get('repository', {})
            owner = repo_data.get('owner', {}).get('login', '')
            repo_name = repo_data.get('name', '')
            
            # Extract installation information
            installation_id = payload.get('installation', {}).get('id')
            
            if not all([pr_number, owner, repo_name, installation_id]):
                return {"error": "Missing required PR information"}
            
            self.logger.info(f"Processing PR #{pr_number} in {owner}/{repo_name}")
            
            # Get the files changed in the PR
            files_changed = self.github_app.get_pull_request_files(
                installation_id, owner, repo_name, pr_number
            )
            
            if not files_changed:
                return {"message": "No files changed in this PR"}
            
            # Generate AI review
            review_comment = self.ai_reviewer.review_code_changes(
                pr_title, pr_description, files_changed
            )
            
            # Post the review comment
            comment_result = self.github_app.post_comment(
                installation_id, owner, repo_name, pr_number, review_comment
            )
            
            self.logger.info(f"Review posted successfully for PR #{pr_number}")
            
            return {
                "success": True,
                "message": f"Review posted for PR #{pr_number}",
                "comment_id": comment_result.get('id'),
                "files_reviewed": len(files_changed)
            }
            
        except Exception as e:
            self.logger.error(f"Error processing PR: {str(e)}")
            return {"error": f"Failed to process PR: {str(e)}"}
    
    def _extract_pr_context(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract relevant context from PR payload"""
        pr_data = payload.get('pull_request', {})
        
        return {
            'number': pr_data.get('number'),
            'title': pr_data.get('title', ''),
            'description': pr_data.get('body', ''),
            'user': pr_data.get('user', {}).get('login', ''),
            'base_branch': pr_data.get('base', {}).get('ref', ''),
            'head_branch': pr_data.get('head', {}).get('ref', ''),
            'state': pr_data.get('state', ''),
            'created_at': pr_data.get('created_at', ''),
            'updated_at': pr_data.get('updated_at', '')
        } 