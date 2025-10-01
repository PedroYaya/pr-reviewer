# GitHub App PR Reviewer

An AI-powered GitHub App that automatically reviews pull requests and provides feedback using OpenAI.

## Features

- 🤖 AI-powered code review using OpenAI
- 🔄 Automatic review on PR creation and updates
- 💬 Posts feedback directly as PR comments
- 🔒 Secure webhook handling with signature verification
- 🚀 Ready for production deployment

## Setup Instructions

### Quickstart (for teammates)

1. Clone the project
   ```bash
   git clone <repo-url>
   cd <repo-folder>
   ```

2. Create your environment file
   ```bash
   cp .env.example .env
   ```
   Fill in: `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`, `OPENAI_API_KEY`.

3. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```

4. Run and validate locally
   - Follow the steps in “Testing with ngrok (Organization GitHub App)”.

### 1. GitHub App (already created)

- The GitHub App for this project is already created in the organization. You do not need to create it again.
- If you are an org admin and need to adjust settings (Webhook URL, permissions/events, or installation), see “Organization configuration notes” below.
- As a teammate, just ensure the App is installed on the target repository. If not, ask an org admin to install it.

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

### 3. Production Deployment

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

### Code overview
- `app.py`: Flask server, routes (`/`, `/webhook`, `/health`, `/clear-memory`). Wires requests to the webhook handler.
- `webhook_handler.py`: Parses `pull_request` events, fetches changed files, calls the AI reviewer, posts the comment.
- `ai_reviewer.py`: Builds a LangChain prompt/chain and generates the review text.
- `github_app.py`: Authenticates as GitHub App (JWT/installation token) and calls GitHub REST API.

## Testing with ngrok (Organization GitHub App)

1. Start the server
   ```bash
   python app.py
   ```

2. Expose port 3000 with ngrok
   ```bash
   ngrok http 3000
   ```
   Copy the HTTPS public ngrok URL (e.g., `https://<id>.ngrok-free.app`).

3. Configure the Webhook in your organization GitHub App
   - Go to: Organization settings → Developer settings → GitHub Apps → your App
   - In the "General" tab:
     - Webhook URL: `https://<id>.ngrok-free.app/webhook`
     - Save changes
   - In "Permissions & events":
     - Repository permissions: Pull requests (Read & write), Contents (Read)
     - Subscribe to events: Pull requests
     - Save changes

4. Install the App on the test repository
   - From the same App page: "Install App" → choose the organization/repository

5. Test the flow
   - Open or update a Pull Request in the repository where the App is installed
   - The App will receive the event at `/webhook` and post a review comment

Notes
- If you change the ngrok URL, update the Webhook URL in the App.
- Required variables in `.env`: `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`, `OPENAI_API_KEY`.

### Organization configuration notes
- If the GitHub App already exists in the organization, you might not need admin permissions to run locally. However:
  - Changing the App’s Webhook URL requires organization App admin privileges.
  - Adjusting permissions (Pull requests, Contents) or subscribed events requires admin privileges.
  - Installing the App in repositories also requires appropriate org permissions.
- If you don’t have permissions, ask an org admin to:
  1) Set Webhook URL to your current ngrok `https://<id>.ngrok-free.app/webhook`.
  2) Confirm permissions and subscribed events as listed above.
  3) Install the App on the target repository.

## How It Works

1. **Webhook Reception**: GitHub sends webhook events when PRs are created/updated
2. **Diff Extraction**: The app fetches the PR diff using GitHub API
3. **AI Review**: The diff is sent to OpenAI for code review
4. **Comment Posting**: AI feedback is posted as a comment on the PR

### Main component flow (plain language)
1) A Pull Request is opened or updated in GitHub.
2) GitHub sends a message (a “webhook”) to our app at `/webhook`.
3) Our app checks that the message is real and comes from GitHub.
4) The app asks GitHub which files changed in that Pull Request.
5) The app sends those changes to the AI and asks for review feedback.
6) The AI returns a human‑readable review (issues, suggestions, summary).
7) The app posts that review as a comment directly on the Pull Request.

Where this happens in the code (optional):
- `app.py`: receives the message from GitHub at `/webhook` and passes it on.
- `webhook_handler.py`: main coordinator; checks the message, gets changed files, calls the AI, and posts the comment.
- `github_app.py`: talks to GitHub’s API (fetch files, post comments).
- `ai_reviewer.py`: talks to the AI to generate the review text.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License 