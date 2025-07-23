#!/usr/bin/env python3
"""
Setup script for GitHub App PR Reviewer
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="github-pr-reviewer",
    version="1.0.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="An AI-powered GitHub App that automatically reviews pull requests",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/github-pr-reviewer",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Software Development :: Quality Assurance",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "github-pr-reviewer=app:main",
        ],
    },
    keywords="github, pull-request, code-review, ai, openai",
    project_urls={
        "Bug Reports": "https://github.com/yourusername/github-pr-reviewer/issues",
        "Source": "https://github.com/yourusername/github-pr-reviewer",
        "Documentation": "https://github.com/yourusername/github-pr-reviewer#readme",
    },
) 