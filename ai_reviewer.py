"""
AI Code Reviewer Module with LangChain
Enhanced version with better context handling and intelligent prompts
"""

import os
from typing import List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain.schema import HumanMessage, SystemMessage
from langchain.chains import LLMChain
from langchain.memory import ConversationBufferMemory


class LangChainAIReviewer:
    def __init__(self):
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        # Initialize LangChain components
        self.llm = ChatOpenAI(
            model="gpt-4",
            temperature=0.3,
            api_key=api_key
        )
        
        # Memory for maintaining context between reviews
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )
        
        # Create the review chain
        self.review_chain = self._create_review_chain()
    
    def _create_review_chain(self):
        """Create the LangChain review chain"""
        
        # System prompt template
        system_template = """You are an expert software engineer performing a code review. 
        Your task is to analyze code changes in a pull request and provide constructive feedback.
        
        Focus on:
        1. Code quality and best practices
        2. Potential bugs or issues
        3. Security concerns
        4. Performance implications
        5. Maintainability and readability
        6. Suggestions for improvement
        
        Be constructive, specific, and helpful. Use markdown formatting for better readability.
        
        Previous review context: {chat_history}"""
        
        system_message_prompt = SystemMessagePromptTemplate.from_template(system_template)
        
        # Human prompt template
        human_template = """Please review the following pull request and provide detailed feedback:

        **PR Title:** {pr_title}
        **PR Description:** {pr_description}
        
        **Files Changed:**
        {files_context}
        
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
        
        Please be thorough but constructive in your feedback."""
        
        human_message_prompt = HumanMessagePromptTemplate.from_template(human_template)
        
        # Create the chat prompt
        chat_prompt = ChatPromptTemplate.from_messages([
            system_message_prompt,
            human_message_prompt
        ])
        
        # Create the chain
        chain = LLMChain(
            llm=self.llm,
            prompt=chat_prompt,
            memory=self.memory,
            verbose=False
        )
        
        return chain
    
    def review_code_changes(self, pr_title: str, pr_description: str, files_changed: List[Dict[str, Any]]) -> str:
        """
        Review code changes using LangChain
        
        Args:
            pr_title: Title of the pull request
            pr_description: Description of the pull request
            files_changed: List of files with their changes
            
        Returns:
            str: AI-generated review comment
        """
        
        try:
            # Prepare the files context
            files_context = self._prepare_files_context(files_changed)
            
            # Run the review chain
            result = self.review_chain.run({
                'pr_title': pr_title,
                'pr_description': pr_description,
                'files_context': files_context
            })
            
            return result
            
        except Exception as e:
            return f"❌ Error generating AI review: {str(e)}"
    
    def _prepare_files_context(self, files_changed: List[Dict[str, Any]]) -> str:
        """Prepare enhanced context for the AI review"""
        context = ""
        
        for file_info in files_changed:
            filename = file_info.get('filename', 'Unknown')
            status = file_info.get('status', 'Unknown')
            additions = file_info.get('additions', 0)
            deletions = file_info.get('deletions', 0)
            changes = file_info.get('changes', 0)
            
            context += f"**{filename}** ({status})\n"
            context += f"- Additions: +{additions}\n"
            context += f"- Deletions: -{deletions}\n"
            context += f"- Total changes: {changes}\n"
            
            # Include the patch if available
            patch = file_info.get('patch', '')
            if patch:
                context += f"- **Changes:**\n```diff\n{patch}\n```\n"
            
            context += "\n"
        
        return context
    
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
    
    def clear_memory(self):
        """Clear the conversation memory"""
        self.memory.clear()
