# GitHub App PR Reviewer

An AI-powered GitHub App that automatically reviews pull requests and provides feedback using OpenAI.

## Features

- 🤖 AI-powered code review using OpenAI
- 🔄 Automatic review on PR creation and updates
- 💬 Posts feedback directly as PR comments
- 🔒 Secure webhook handling with signature verification
- 🚀 Ready for production deployment

## Setup Instructions

### 1. Create GitHub App

1. Go to [GitHub Developer Settings](https://github.com/settings/apps)
2. Click "New GitHub App"
3. Configure the app:
   - **App name**: `pr-ai-reviewer` (or your preferred name)
   - **Homepage URL**: `http://localhost:3000` (for development)
   - **Webhook URL**: `http://localhost:3000/webhook` (for development)
   - **Webhook secret**: Generate a random secret and save it
4. Set permissions:
   - **Repository permissions**:
     - Pull requests: Read & write
     - Contents: Read
   - **Subscribe to events**: Pull requests
5. Install the app on your repository

### 2. Environment Setup

1. Clone this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create `.env` file:
   ```bash
   cp .env.example .env
   ```
4. Fill in your environment variables in `.env`

### 3. Local Development

1. Start the server:
   ```bash
   python app.py
   ```
2. Expose with ngrok:
   ```bash
   ngrok http 3000
   ```
3. Update your GitHub App webhook URL with the ngrok URL

### 4. Production Deployment

Deploy to your preferred platform (Vercel, Render, Railway) and update the webhook URL.

## Environment Variables

Create a `.env` file with the following variables:

```env
GITHUB_APP_ID=your_app_id
GITHUB_PRIVATE_KEY=your_private_key
GITHUB_WEBHOOK_SECRET=your_webhook_secret
OPENAI_API_KEY=your_openai_api_key
```

## Project Structure

```
├── app.py                 # Main Flask application
├── github_app.py          # GitHub App integration
├── ai_reviewer.py         # OpenAI integration for code review
├── webhook_handler.py     # Webhook event processing
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
└── README.md             # This file
```

## How It Works

1. **Webhook Reception**: GitHub sends webhook events when PRs are created/updated
2. **Diff Extraction**: The app fetches the PR diff using GitHub API
3. **AI Review**: The diff is sent to OpenAI for code review
4. **Comment Posting**: AI feedback is posted as a comment on the PR

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License 