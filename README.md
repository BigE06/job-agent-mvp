# JobAgent.ai - The Unfair Career Advantage

**An AI-powered agent that finds jobs, analyzes fit, and hunts down the specific hiring team using Deep Boolean Logic.**

## Key Features

### 🧠 Smart Analysis
Compares your profile skills to job descriptions performing a **Gap Analysis**. It identifies missing keywords, assesses match score, and generates screening questions to prepare you.

### ✍️ Auto-Drafting
Writes cover letters referencing specific company news and your relevant experience. It uses the "Why You, Why Me, Why Us" framework to create compelling narratives.

### 🎯 Recruiter Radar
Uses **"Phrase-Locked" search algorithms** to find the exact Hiring Manager and Specialist Recruiter for the role. It bypasses generic HR by constructing complex Boolean strings (e.g., `("Marketing Recruiter" OR "Head of Marketing") AND "Company Name"`).

## Installation

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Run the Application**:
    ```bash
    python -m uvicorn app.main:app --reload
    ```
    Access the app at `http://127.0.0.1:8000`.

## Tech Stack

*   **Backend**: Python (FastAPI), SQLite
*   **Frontend**: Vanilla JavaScript, HTML/CSS (Glassmorphism UI)
*   **AI**: OpenAI API integration for analysis and drafting.
