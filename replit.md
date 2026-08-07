# Gizemli Vaka - Detective Mystery Game Platform

## Overview
Gizemli Vaka is a bilingual (Turkish/English) online platform offering interactive detective mystery games. Users engage with fictional murder cases by examining various evidence types (PDFs, videos, audio, images), analyzing clues, and submitting reports. The platform aims to provide an immersive investigative experience, featuring AI-generated case content and robust administrative tools for case management. It supports corporate team-building activities and integrates multiple payment gateways for the Turkish market.

## User Preferences
I prefer iterative development, with a focus on delivering functional components quickly. I value clear and concise communication. When making changes, please explain the reasoning and potential impact. I prefer that you ask before making major architectural changes or introducing new external dependencies.

## System Architecture
The platform is built on Python 3.11 using the Flask framework and SQLAlchemy for ORM. PostgreSQL is used as the database. The UI is developed with Bootstrap 5 and Jinja2 templates, supporting full bilingual functionality with dynamic content fields for English translations. Evidence viewing utilizes PDF.js for secure, no-download PDF display.

Key architectural features include:
- **Bilingual System**: Language preference is managed via session, with static UI elements conditionally rendered and dynamic content sourced from `_en` suffixed database fields.
- **Case Management**: An administrative panel allows for creating, editing, and managing cases, including toggling their active status and adding time-based hints.
- **AI Case Generation**: Integration with Gemini AI (via Replit AI Integrations) enables the generation of new case ideas, detailed case scenarios (including suspects, witnesses, and evidence requirements), and individual evidence files (HTML with forensic styling, watermarks, and handwritten notes). Case generation is handled asynchronously in a background thread with real-time progress tracking.
- **Payment System**: Multiple Turkish payment gateways (iyzico, PaynKolay, Param POS) are integrated for purchasing cases and hint packages, including support for 3D Secure transactions and team-based purchases.
- **SEO & Responsiveness**: Comprehensive SEO features (meta tags, Open Graph, JSON-LD, sitemap, robots.txt) and mobile-responsive design are implemented across all public-facing pages.
- **Evidence Handling**: The system manages and displays various digital evidence types (PDFs, videos, audio, images) within the platform, preventing direct downloads of sensitive content.

## External Dependencies
- **PostgreSQL**: Primary database for all application data.
- **Flask**: Python web framework.
- **SQLAlchemy**: Python SQL toolkit and Object-Relational Mapper.
- **Jinja2**: Templating engine for Flask.
- **Bootstrap 5**: Frontend UI framework.
- **PDF.js**: JavaScript library for rendering PDFs in the browser.
- **Gemini AI (via Replit AI Integrations)**: Used for AI-driven case generation and content creation.
- **iyzico**: Payment gateway for the Turkish market.
- **PaynKolay**: Payment gateway for the Turkish market.
- **Param POS**: SOAP-based 3D Secure payment integration for the Turkish market.
- **OpenAI gpt-image-1**: Used for generating AI case cover images.