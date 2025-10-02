"""
Performance testing module.
Contains various functions for testing application performance.
"""

import time
import requests
import threading
from typing import List, Dict

class PerformanceTester:
    """Tests application performance."""
    
    def __init__(self):
        self.results = []
    
    def slow_function(self, n: int) -> int:
        """Calculate factorial - intentionally slow implementation."""
        if n <= 1:
            return 1
        
        # Bug: Inefficient recursive implementation
        return n * self.slow_function(n - 1)
    
    def fetch_data_sync(self, urls: List[str]) -> List[Dict]:
        """Fetch data from multiple URLs synchronously."""
        results = []
        
        # Bug: Synchronous requests - should use async/threading
        for url in urls:
            try:
                response = requests.get(url, timeout=5)
                results.append({
                    'url': url,
                    'status': response.status_code,
                    'data': response.text[:100]  # Bug: Truncating without reason
                })
            except Exception as e:
                results.append({
                    'url': url,
                    'error': str(e)
                })
        
        return results
    
    def process_large_list(self, data: List[int]) -> List[int]:
        """Process a large list of numbers."""
        result = []
        
        # Bug: Inefficient nested loops
        for i in data:
            for j in data:
                if i != j:
                    result.append(i * j)
        
        return result
    
    def memory_intensive_task(self, size: int) -> List[str]:
        """Create a large list in memory."""
        # Bug: Creates unnecessary large objects
        large_list = []
        
        for i in range(size):
            # Bug: String concatenation in loop
            large_list.append("item_" + str(i) + "_" + "x" * 1000)
        
        return large_list
    
    def concurrent_task(self, tasks: List[str]) -> List[str]:
        """Execute tasks concurrently."""
        results = []
        
        # Bug: Using threading incorrectly
        threads = []
        for task in tasks:
            thread = threading.Thread(target=lambda: results.append(task.upper()))
            threads.append(thread)
            thread.start()
        
        # Bug: No proper thread synchronization
        for thread in threads:
            thread.join()
        
        return results

def benchmark_function(func, *args, **kwargs):
    """Benchmark a function's execution time."""
    start_time = time.time()
    result = func(*args, **kwargs)
    end_time = time.time()
    
    return {
        'result': result,
        'execution_time': end_time - start_time
    }

# Bug: Global variables that could cause issues
CACHE = {}
REQUEST_COUNT = 0

def cached_request(url: str) -> str:
    """Make a cached request."""
    global REQUEST_COUNT
    REQUEST_COUNT += 1
    
    # Bug: No cache expiration
    if url in CACHE:
        return CACHE[url]
    
    try:
        response = requests.get(url)
        CACHE[url] = response.text
        return response.text
    except Exception as e:
        return f"Error: {str(e)}"

# Bug: Unused imports
import os
import sys
import json
