"""
AI Code Reviewer Module
Integrates with OpenAI to analyze code changes and generate review comments
"""

import os
import openai
from typing import List, Dict, Any


class AIReviewer:
    def __init__(self):
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        openai.api_key = api_key
        self.model = "gpt-4"  # You can change this to gpt-3.5-turbo if needed
    
    def review_code_changes(self, pr_title: str, pr_description: str, files_changed: List[Dict[str, Any]]) -> str:
        """
        Review code changes and generate feedback
        
        Args:
            pr_title: Title of the pull request
            pr_description: Description of the pull request
            files_changed: List of files with their changes
            
        Returns:
            str: AI-generated review comment
        """
        
        # Prepare the context for the AI
        context = self._prepare_review_context(pr_title, pr_description, files_changed)
        
        # Create the prompt for code review
        prompt = self._create_review_prompt(context)
        
        try:
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are an experienced software engineer performing a code review. 
                        Your task is to analyze the code changes in a pull request and provide constructive feedback.
                        
                        Focus on:
                        1. Code quality and best practices
                        2. Potential bugs or issues
                        3. Security concerns
                        4. Performance implications
                        5. Maintainability and readability
                        6. Suggestions for improvement
                        
                        Be constructive, specific, and helpful. Use markdown formatting for better readability."""
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=2000,
                temperature=0.3
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"❌ Error generating AI review: {str(e)}"
    
    def _prepare_review_context(self, pr_title: str, pr_description: str, files_changed: List[Dict[str, Any]]) -> str:
        """Prepare the context for the AI review"""
        context = f"## Pull Request Information\n"
        context += f"**Title:** {pr_title}\n"
        context += f"**Description:** {pr_description}\n\n"
        
        context += f"## Files Changed\n"
        for file_info in files_changed:
            filename = file_info.get('filename', 'Unknown')
            status = file_info.get('status', 'Unknown')
            additions = file_info.get('additions', 0)
            deletions = file_info.get('deletions', 0)
            changes = file_info.get('changes', 0)
            
            context += f"- **{filename}** ({status})\n"
            context += f"  - Additions: +{additions}\n"
            context += f"  - Deletions: -{deletions}\n"
            context += f"  - Total changes: {changes}\n"
            
            # Include the patch if available
            patch = file_info.get('patch', '')
            if patch:
                context += f"  - **Changes:**\n```diff\n{patch}\n```\n"
            
            context += "\n"
        
        return context
    
    def _create_review_prompt(self, context: str) -> str:
        """Create the prompt for the AI review"""
        prompt = f"""
Please review the following pull request and provide detailed feedback:

{context}

Please provide your review in the following format:

## 🤖 AI Code Review

### ✅ Positive Aspects
- [List any good practices, clean code, etc.]

### ⚠️ Issues Found
- [List any potential issues, bugs, or concerns]

### 🔧 Suggestions for Improvement
- [List specific suggestions for better code]

### 📝 Summary
[Overall assessment and recommendation]

### 🔍 Detailed Analysis
[Detailed analysis of the changes]

Please be thorough but constructive in your feedback.
"""
        return prompt
    
    def generate_summary_comment(self, pr_title: str, files_changed: List[Dict[str, Any]]) -> str:
        """Generate a quick summary comment for the PR"""
        total_files = len(files_changed)
        total_additions = sum(f.get('additions', 0) for f in files_changed)
        total_deletions = sum(f.get('deletions', 0) for f in files_changed)
        
        summary = f"## 📊 PR Summary\n\n"
        summary += f"**Title:** {pr_title}\n"
        summary += f"**Files changed:** {total_files}\n"
        summary += f"**Additions:** +{total_additions}\n"
        summary += f"**Deletions:** -{total_deletions}\n"
        summary += f"**Net changes:** {total_additions - total_deletions}\n\n"
        
        summary += f"**Files:**\n"
        for file_info in files_changed:
            filename = file_info.get('filename', 'Unknown')
            status = file_info.get('status', 'Unknown')
            summary += f"- `{filename}` ({status})\n"
        
        return summary 