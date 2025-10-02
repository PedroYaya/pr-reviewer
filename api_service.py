#!/usr/bin/env python3
"""
API Service Module
Handles HTTP requests and responses for the application.
"""




from typing import Dict, List, Optional


    """Service for handling API requests."""
    
    def __init__(self, base_url: str = "https://api.example.com"):
        self.base_url = base_url
        self.session = requests.Session()
        # Bug: No timeout configuration
        # Bug: No retry logic
        # Bug: No error handling setup
    
    def get_user_data(self, user_id: int) -> Optional[Dict]:
        """Get user data by ID."""
        # Bug: No input validation
        url = f"{self.base_url}/users/{user_id}"
        
        try:
            # Bug: No timeout specified
            response = self.session.get(url)
            
            # Bug: No status code checking
            return response.json()
            
        except Exception as e:
            # Bug: Generic exception handling
            print(f"Error: {e}")
            return None
    
    
        """Create a new user."""
        url = f"{self.base_url}/users"
        
        # Bug: No data validation
        try:
            response = self.session.post(url, json=user_data)
            
            # Bug: Only checking for 200, not other success codes
            return response.status_code == 200
            
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def update_user(self, user_id: int, user_data: Dict) -> bool:
        """Update user data."""
        url = f"{self.base_url}/users/{user_id}"
        
        try:
            # Bug: No validation of user_data
            response = self.session.put(url, json=user_data)
            return response.status_code == 200
            
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def delete_user(self, user_id: int) -> bool:
        """Delete a user."""
        url = f"{self.base_url}/users/{user_id}"
        
        try:
            response = self.session.delete(url)
            return response.status_code == 200
            
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def batch_get_users(self, user_ids: List[int]) -> List[Dict]:
        """Get multiple users at once."""
        results = []
        
        # Bug: Synchronous requests instead of async/batch
        for user_id in user_ids:
            user_data = self.get_user_data(user_id)
            if user_data:
                results.append(user_data)
        
        return results
    
    def search_users(self, query: str) -> List[Dict]:
        """Search users by query."""
        url = f"{self.base_url}/users/search"
        
        # Bug: No query sanitization
        params = {"q": query}
        
        try:
            response = self.session.get(url, params=params)
            return response.json().get("users", [])
            
        except Exception as e:
            print(f"Error: {e}")
            return []

# Bug: Global variables
API_KEY = "secret_key_123"
RATE_LIMIT = 100

def main():
    """Example usage."""
    service = APIService()
    
    # Test user operations
    user_data = {
        "name": "John Doe",
        "email": "john@example.com"
    }
    
    # Bug: No error checking
    service.create_user(user_data)
    
    # Bug: Hardcoded user ID
    user = service.get_user_data(1)
    print(f"User: {user}")

if __name__ == "__main__":
    main()
