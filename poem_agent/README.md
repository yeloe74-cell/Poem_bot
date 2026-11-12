# Intelligent AI Poem Channel Management Agent

A production-oriented Python project for managing a poetry Telegram channel with a general AI agent architecture that supports the primary mission: collecting, evaluating, approving, scheduling, and publishing poetry content.

## Mission

This project is not a general-purpose chatbot. It is a Poem Bot system whose core responsibilities are:

- collect poems from public Telegram channels
- classify them by emotion, theme, and quality
- detect duplicates
- select worthy poems for publication
- find matching images and verify attribution
- create publication drafts
- require owner approval before publication
- schedule and publish approved content
- maintain channel analytics and learning feedback

## Architecture

The project is organized as a modular agent system:

- config/
- core/
- memory/
- poetry/
- media/
- channel/
- telegram/
- tools/
- storage/
- security/
- tests/

## Setup

1. Create a virtual environment
   python -m venv .venv
   source .venv/bin/activate
2. Install dependencies
   pip install -r requirements.txt
3. Copy environment file
   cp .env.example .env
4. Update the environment values
5. Start the app
   python -m poem_agent.main

## Notes

- Owner approval is required before any publication.
- AI provider keys must be kept in environment variables.
- The project uses SQLite by default for local deployments and keeps the storage layer adaptable.
