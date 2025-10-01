"""
GitHub App Integration Module
Handles authentication and API interactions with GitHub
"""

import os
import jwt
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, Optional


class GitHubApp:
    def __init__(self):
        self.app_id = os.getenv('GITHUB_APP_ID')
        self.private_key = os.getenv('GITHUB_PRIVATE_KEY')
        self.webhook_secret = os.getenv('GITHUB_WEBHOOK_SECRET')
        
        if not all([self.app_id, self.private_key, self.webhook_secret]):
            raise ValueError("Missing required GitHub App environment variables")
        
        # Clean up private key format
        self.private_key = self.private_key.replace('\\n', '\n')
        
        self.base_url = "https://api.github.com"
        self._installation_token = None
        self._token_expires_at = None
    
    def generate_jwt(self) -> str:
        """Generate JWT token for GitHub App authentication"""
        now = datetime.utcnow()
        exp_time = now + timedelta(minutes=10)
        now_timestamp = int(now.timestamp())
        exp_timestamp = int(exp_time.timestamp())

        payload = {
            'iat': now_timestamp,
            'exp': exp_timestamp,
            'iss': self.app_id
        }
        
        return jwt.encode(payload, self.private_key, algorithm='RS256')
    
    def get_installation_token(self, installation_id: int) -> str:
        """Get installation access token for a specific installation"""
        # Check if we have a valid cached token
        if (self._installation_token and self._token_expires_at and 
            datetime.utcnow() < self._token_expires_at):
            return self._installation_token
        
        jwt_token = self.generate_jwt()
        headers = {
            'Authorization': f'Bearer {jwt_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        
        url = f"{self.base_url}/app/installations/{installation_id}/access_tokens"
        response = requests.post(url, headers=headers)
        
        if response.status_code != 201:
            raise Exception(f"Failed to get installation token: {response.text}")
        
        token_data = response.json()
        self._installation_token = token_data['token']
        self._token_expires_at = datetime.fromisoformat(token_data['expires_at'].replace('Z', '+00:00'))
        
        return self._installation_token
    
    def get_authenticated_session(self, installation_id: int) -> requests.Session:
        """Get an authenticated requests session"""
        token = self.get_installation_token(installation_id)
        session = requests.Session()
        session.headers.update({
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json'
        })
        return session
    
    def get_pull_request_diff(self, installation_id: int, owner: str, repo: str, pr_number: int) -> str:
        """Get the diff for a pull request"""
        session = self.get_authenticated_session(installation_id)
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
        
        response = session.get(url)
        if response.status_code != 200:
            raise Exception(f"Failed to get PR: {response.text}")
        
        pr_data = response.json()
        return pr_data.get('diff_url', '')
    
    def get_pull_request_files(self, installation_id: int, owner: str, repo: str, pr_number: int) -> list:
        """Get the files changed in a pull request"""
        session = self.get_authenticated_session(installation_id)
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        
        response = session.get(url)
        if response.status_code != 200:
            raise Exception(f"Failed to get PR files: {response.text}")
        
        return response.json()
    
    def post_comment(self, installation_id: int, owner: str, repo: str, pr_number: int, comment: str) -> Dict[str, Any]:
        """Post a comment on a pull request"""
        session = self.get_authenticated_session(installation_id)
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        
        data = {
            'body': comment
        }
        
        response = session.post(url, json=data)
        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to post comment: {response.text}")
        
        return response.json()
    
    def get_pull_request_details(self, installation_id: int, owner: str, repo: str, pr_number: int) -> Dict[str, Any]:
        """Get detailed information about a pull request"""
        session = self.get_authenticated_session(installation_id)
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
        
        response = session.get(url)
        if response.status_code != 200:
            raise Exception(f"Failed to get PR details: {response.text}")
        
        return response.json() 