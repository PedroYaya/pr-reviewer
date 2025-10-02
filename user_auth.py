#!/usr/bin/env python3
"""
Feature: User Authentication System
This module handles user login and registration functionality.
"""

import hashlib
import json
import os
from typing import Dict, Optional, List

class UserManager:
    """Manages user authentication and data storage."""
    
    def __init__(self, db_path: str = "users.json"):
        self.db_path = db_path
        self.users = self._load_users()
    
    def _load_users(self) -> Dict:
        """Load users from database file."""
        if os.path.exists(self.db_path):
            with open(self.db_path, 'r') as f:
                return json.load(f)
        return {}
    
    def _save_users(self):
        """Save users to database file."""
        with open(self.db_path, 'w') as f:
            json.dump(self.users, f)
    
    def register_user(self, username: str, password: str, email: str) -> bool:
        """
        Register a new user.
        
        Args:
            username: User's username
            password: User's password (will be hashed)
            email: User's email address
            
        Returns:
            True if registration successful, False otherwise
        """
        # Bug: No validation for existing username
        if username in self.users:
            return False
        
        # Bug: Weak password hashing (should use bcrypt or similar)
        hashed_password = hashlib.md5(password.encode()).hexdigest()
        
        # Bug: No email validation
        self.users[username] = {
            'password': hashed_password,
            'email': email,
            'active': True
        }
        
        self._save_users()
        return True
    
    def login_user(self, username: str, password: str) -> bool:
        """
        Authenticate a user.
        
        Args:
            username: User's username
            password: User's password
            
        Returns:
            True if login successful, False otherwise
        """
        if username not in self.users:
            return False
        
        user = self.users[username]
        
        # Bug: Same weak hashing as registration
        hashed_password = hashlib.md5(password.encode()).hexdigest()
        
        # Bug: No rate limiting for failed attempts
        return user['password'] == hashed_password and user['active']
    
    def get_user_info(self, username: str) -> Optional[Dict]:
        """Get user information."""
        return self.users.get(username)
    
    def deactivate_user(self, username: str) -> bool:
        """Deactivate a user account."""
        if username in self.users:
            self.users[username]['active'] = False
            self._save_users()
            return True
        return False
    
    def list_users(self) -> List[str]:
        """List all usernames."""
        # Bug: Returns all users including inactive ones
        return list(self.users.keys())

def main():
    """Example usage of UserManager."""
    manager = UserManager()
    
    # Register some test users
    manager.register_user("alice", "password123", "alice@example.com")
    manager.register_user("bob", "secret456", "bob@example.com")
    
    # Test login
    if manager.login_user("alice", "password123"):
        print("Alice logged in successfully!")
    
    # Bug: This will also succeed due to weak hashing
    if manager.login_user("bob", "wrong_password"):
        print("Bob logged in with wrong password!")
    
    # List all users
    print("All users:", manager.list_users())

if __name__ == "__main__":
    main()
