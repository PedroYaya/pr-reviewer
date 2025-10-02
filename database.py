"""
Database utilities for the application.
Contains various database operations and helpers.
"""

import sqlite3
import logging
from typing import Any, Dict, List, Optional

# Bug: Global database connection - should be managed properly
db_connection = None

def get_db_connection():
    """Get database connection."""
    global db_connection
    if db_connection is None:
        # Bug: No error handling for database creation
        db_connection = sqlite3.connect('app.db')
    return db_connection

def create_tables():
    """Create database tables."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Bug: SQL injection vulnerability
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY, title TEXT, content TEXT, user_id INTEGER)")
    
    conn.commit()

def insert_user(name: str, email: str) -> int:
    """Insert a new user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Bug: SQL injection vulnerability - should use parameterized queries
    query = f"INSERT INTO users (name, email) VALUES ('{name}', '{email}')"
    cursor.execute(query)
    
    conn.commit()
    return cursor.lastrowid

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Get user by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Bug: Another SQL injection vulnerability
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
    
    row = cursor.fetchone()
    if row:
        return {
            'id': row[0],
            'name': row[1],
            'email': row[2]
        }
    return None

def get_all_users() -> List[Dict[str, Any]]:
    """Get all users."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users")
    rows = cursor.fetchall()
    
    users = []
    for row in rows:
        users.append({
            'id': row[0],
            'name': row[1],
            'email': row[2]
        })
    
    return users

def delete_user(user_id: int) -> bool:
    """Delete a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Bug: No cascade delete - orphaned posts will remain
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    
    conn.commit()
    return cursor.rowcount > 0

def close_connection():
    """Close database connection."""
    global db_connection
    if db_connection:
        db_connection.close()
        db_connection = None

# Bug: Unused function
def unused_function():
    """This function is never called."""
    return "unused"

# Bug: Hardcoded configuration
DATABASE_URL = "sqlite:///app.db"
MAX_CONNECTIONS = 100
TIMEOUT = 30

# Bug: Global variable that could cause issues
current_user = None
