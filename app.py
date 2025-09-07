from flask import Flask, render_template, request, jsonify, session, send_file, send_from_directory
from flask_cors import CORS
import json
import os
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from io import BytesIO
import time
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
import logging
import mysql.connector
import requests

# Load environment variables (support env.txt or .env)
if os.path.exists('env.txt'):
	load_dotenv('env.txt')
else:
load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key')
CORS(app, origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5000"])

# Add logging
logging.basicConfig(level=logging.DEBUG)


def _parse_json_like(text: str):
    """Best-effort parse of JSON content that may include markdown fences.

    Handles objects and arrays and strips ```json / ``` fences.
    """
    if not isinstance(text, str):
        return text
    s = text.strip()
    # Strip markdown code fences
    import re
    # Remove fenced code blocks if present
    if s.startswith('```') and s.rstrip().endswith('```'):
        s = re.sub(r"^```(?:json)?\s*([\s\S]*?)\s*```$", r"\1", s.strip(), flags=re.IGNORECASE)
    # Try direct parse
    try:
        return json.loads(s)
    except Exception:
        pass
    # Extract first JSON array by bracket matching
    start_idx = s.find('[')
    if start_idx != -1:
        depth = 0
        for i in range(start_idx, len(s)):
            if s[i] == '[':
                depth += 1
            elif s[i] == ']':
                depth -= 1
                if depth == 0:
                    candidate = s[start_idx:i+1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
    # Extract first JSON object by brace matching
    start_idx = s.find('{')
    if start_idx != -1:
        depth = 0
        for i in range(start_idx, len(s)):
            if s[i] == '{':
                depth += 1
            elif s[i] == '}':
                depth -= 1
                if depth == 0:
                    candidate = s[start_idx:i+1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
    # Give up with detailed raw
    return {"error": "Could not parse JSON", "raw": text}
    return {"error": "Could not parse JSON", "raw": text}


def get_ai_response(prompt, max_tokens=500, expect_json=False):
    # Local fallback to avoid external API during setup/troubleshooting
    if os.getenv('FAKE_AI', 'false').lower() in ['1', 'true', 'yes']:
        app.logger.debug("AI provider: FAKE_AI")
        if expect_json:
            # Return simple structured defaults
            if 'Generate 5' in prompt and 'questions' in prompt:
                return [
                    "Tell me about a challenging project you worked on.",
                    "How do you approach debugging complex issues?",
                    "Describe a time you collaborated across teams.",
                    "Explain a technical concept to a non-technical audience.",
                    "What would you improve about your last project?"
                ]
            if 'Provide feedback' in prompt or 'Evaluate this answer' in prompt:
                return {"feedback": "Clear explanation with room for more concrete examples.", "score": 7, "suggestions": "Add metrics and specific outcomes."}
            if 'Generate a summary' in prompt:
                return {"strengths": ["Good fundamentals", "Communicates clearly"], "improvements": ["Add examples", "Deepen domain details"], "resources": ["https://roadmap.sh", "https://refactoring.guru"], "overall_score": 7}
            return {"message": "OK"}
        return "OK"
    """Call Together or Hugging Face depending on available API key.

    - If HUGGINGFACE_API_KEY is set, or TOGETHER_API_KEY starts with 'hf_', use HF Inference API
    - Else use Together chat completions
    """
    together_api_key_raw = os.getenv('TOGETHER_API_KEY')
    together_api_key = together_api_key_raw.strip() if together_api_key_raw else None
    hf_api_key_env = os.getenv('HUGGINGFACE_API_KEY')
    hf_api_key_env = hf_api_key_env.strip() if hf_api_key_env else None
    hf_api_key = hf_api_key_env or (together_api_key if together_api_key and together_api_key.startswith('hf_') else None)
    openrouter_api_key_raw = os.getenv('OPENROUTER_API_KEY')
    openrouter_api_key = openrouter_api_key_raw.strip() if openrouter_api_key_raw else None

    if hf_api_key:
        app.logger.debug("AI provider: Hugging Face Inference API")
    # OpenRouter fallback if configured
    if openrouter_api_key:
        app.logger.debug("AI provider: OpenRouter")
        url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
            "Authorization": f"Bearer {openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5000",
            "X-Title": "LLM Interview Sim"
        }
        model = os.getenv('OPENROUTER_MODEL', 'google/gemma-7b-it:free')
        payload = {
            "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
        response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 200:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            return {"error": f"OpenRouter request failed with {response.status_code}", "detail": detail}
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            return {"error": "Unexpected OpenRouter response format", "raw": data}
        if expect_json:
            return _parse_json_like(content)
        return content
        # Use official client for reliability
        model = os.getenv('HUGGINGFACE_MODEL', 'meta-llama/Llama-2-70b-chat-hf')
        try:
            client = InferenceClient(model=model, token=hf_api_key)
            content = client.text_generation(
                prompt,
                max_new_tokens=max_tokens,
                temperature=0.7,
                return_full_text=False
            )
        except Exception as e:
            return {"error": "HF client error", "detail": str(e)}

    if expect_json:
        try:
            return json.loads(content)
        except Exception:
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    return {"error": "Invalid JSON parsing", "raw": content}
            else:
                return {"error": "Could not parse JSON", "raw": content}
    return content

    # Default: Together API
    if not together_api_key:
        return {"error": "No API key set. Provide TOGETHER_API_KEY or HUGGINGFACE_API_KEY in env.txt."}
    app.logger.debug("AI provider: Together API")
    url = "https://api.together.xyz/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {together_api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "meta-llama/Llama-2-70b-chat-hf",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code != 200:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        return {"error": f"Together request failed with {response.status_code}", "detail": detail}

    resp_json = response.json()
    if "choices" not in resp_json or not resp_json["choices"]:
        return {"error": "Invalid response from AI API", "raw": resp_json}

    content = resp_json["choices"][0].get("message", {}).get("content", "")
    if expect_json:
        return _parse_json_like(content)
    return content


@app.route('/ai_health')
def ai_health():
    together_api_key_raw = os.getenv('TOGETHER_API_KEY')
    together_api_key = together_api_key_raw.strip() if together_api_key_raw else None
    hf_api_key_env = os.getenv('HUGGINGFACE_API_KEY')
    hf_api_key_env = hf_api_key_env.strip() if hf_api_key_env else None
    hf_api_key = hf_api_key_env or (together_api_key if together_api_key and together_api_key.startswith('hf_') else None)
    openrouter_api_key_raw = os.getenv('OPENROUTER_API_KEY')
    openrouter_api_key = openrouter_api_key_raw.strip() if openrouter_api_key_raw else None
    provider = 'huggingface' if hf_api_key else ('openrouter' if openrouter_api_key else ('together' if together_api_key else 'none'))
    if provider == 'huggingface':
        model = os.getenv('HUGGINGFACE_MODEL', 'meta-llama/Llama-2-70b-chat-hf')
    elif provider == 'openrouter':
        model = os.getenv('OPENROUTER_MODEL', 'google/gemma-7b-it:free')
    else:
        model = 'meta-llama/Llama-2-70b-chat-hf'
    return jsonify({
        'provider': provider,
        'model': model,
        'has_hf_key': bool(hf_api_key),
        'has_together_key': bool(together_api_key),
        'has_openrouter_key': bool(openrouter_api_key),
        'hf_key_prefix': (hf_api_key[:3] + '***') if hf_api_key else None,
        'hf_key_len': len(hf_api_key) if hf_api_key else 0
    })


def get_db_connection():
    return mysql.connector.connect(
        host='localhost',
        user='root',         # change if needed
        password='your_password_here',  # 🔴 replace with your MySQL root/user password
        database='interview_sim'
    )


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/interview')
def interview_page():
    return render_template('interview.html')


@app.route('/summary')
def summary_page():
    summary = session.get('interview_summary')
    if isinstance(summary, str) or not isinstance(summary, dict):
        summary = None
    return render_template(
        'summary.html',
        strengths=(summary or {}).get('strengths', []),
        improvements=(summary or {}).get('improvements', []),
        resources=(summary or {}).get('resources', []),
        overall_score=(summary or {}).get('overall_score', None)
    )


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favico.ico', mimetype='image/vnd.microsoft.icon')


@app.route('/configure', methods=['POST'])
def configure_interview():
    try:
        data = request.get_json()
        app.logger.debug(f"Received data: {data}")

        if not data:
            return jsonify({'status': 'error', 'message': 'No data received'}), 400

        session['job_role'] = data.get('job_role')
        session['interview_type'] = data.get('interview_type')
        session['domain'] = data.get('domain')
        session['interview_started'] = True
        session['current_question_index'] = 0
        session['user_answers'] = []
        session['feedback_received'] = False
        session['interview_summary'] = None

        # Generate questions
        if session['interview_type'] == 'Technical':
            prompt = (
                f"Generate 5 technical interview questions for the role of {session['job_role']} "
                f"in the domain of {session['domain']}. Respond as a JSON array of strings."
            )
        else:
            prompt = (
                f"Generate 5 behavioral interview questions for the role of {session['job_role']}. "
                "Respond as a JSON array of strings."
            )

        questions_response = get_ai_response(prompt, expect_json=True)
        # Fallback if AI fails
        if isinstance(questions_response, dict) and questions_response.get('error'):
            app.logger.warning(f"Question generation failed, falling back. Detail: {questions_response}")
            session['questions'] = [
                "Tell me about a challenging project you worked on and your role.",
                "How do you approach debugging complex, intermittent issues?",
                "Describe a time you collaborated across teams to deliver a feature.",
                "Explain a technical concept to a non-technical stakeholder.",
                "What would you improve about your last project and why?"
            ]
        elif isinstance(questions_response, list):
            session['questions'] = questions_response
        else:
            session['questions'] = [str(questions_response)]

        app.logger.debug(f"Generated questions: {session['questions']}")

        return jsonify({
            'status': 'success',
            'question': session['questions'][0],
            'question_index': 1,
            'total_questions': len(session['questions'])
        })
    except Exception as e:
        app.logger.error(f"Error in configure_interview: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/submit_answer', methods=['POST'])
def submit_answer():
    try:
        data = request.get_json()
        user_answer = data.get('answer')
        question_index = session.get('current_question_index', 0)

        # Store the answer
        session['user_answers'].append(user_answer)

        # Get feedback for the answer
        question = session['questions'][question_index]
        prompt = (
            f"Evaluate this interview answer for a {session.get('job_role')} position.\n\n"
            f"Question: {question}\n"
            f"Answer: {user_answer}\n\n"
            "Provide concise feedback focusing on:\n"
            "- Technical accuracy (if technical question)\n"
            "- Clarity and structure\n"
            "- Specific examples provided\n"
            "- Completeness of response\n\n"
            "Score criteria: 1-3 (Poor), 4-6 (Fair), 7-8 (Good), 9-10 (Excellent)\n\n"
            "Respond ONLY in this JSON format:\n"
            "{\n"
            "  \"feedback\": \"Brief 2-3 sentence evaluation highlighting key strengths and one main area to improve\",\n"
            "  \"score\": 7,\n"
            "  \"suggestions\": \"One specific actionable improvement tip\"\n"
            "}"
        )
        feedback = get_ai_response(prompt, expect_json=True)
        # Normalize feedback structure
        if isinstance(feedback, dict) and not feedback.get('error'):
            normalized_feedback_text = feedback.get('feedback') or json.dumps(feedback)
            normalized_score = feedback.get('score')
        else:
            # Fallback feedback
            app.logger.warning(f"Feedback generation failed or invalid, falling back. Detail: {feedback}")
            normalized_feedback_text = "Good structure and clear communication. Consider adding specific examples to strengthen your response."
            normalized_score = 7

        if 'feedback_data' not in session:
            session['feedback_data'] = []

        session['feedback_data'].append({
            'question': question,
            'answer': user_answer,
            'feedback': feedback
        })

        # Next or finish
        if question_index < len(session['questions']) - 1:
            session['current_question_index'] = question_index + 1
            next_question = session['questions'][session['current_question_index']]
            return jsonify({
                'status': 'next_question',
                'feedback': normalized_feedback_text,
                'score': normalized_score,
                'question': next_question,
                'question_index': session['current_question_index'] + 1,
                'total_questions': len(session['questions'])
            })
        else:
            summary_prompt = (
                f"Generate a concise interview summary for a {session['interview_type']} interview for {session['job_role']} position.\n\n"
                "Based on the interview responses, provide:\n"
                "- 3 specific strengths (be specific, not generic)\n"
                "- 3 concrete areas for improvement\n"
                "- 3 practical resources for improvement\n"
                "- Overall score (1-10) based on performance\n\n"
                "Keep each item brief and actionable. Focus on specific skills and behaviors observed.\n\n"
                "Respond ONLY in this JSON format:\n"
                "{\n"
                "  \"strengths\": [\"Specific strength 1\", \"Specific strength 2\", \"Specific strength 3\"],\n"
                "  \"improvements\": [\"Concrete improvement 1\", \"Concrete improvement 2\", \"Concrete improvement 3\"],\n"
                "  \"resources\": [\"Practical resource 1\", \"Practical resource 2\", \"Practical resource 3\"],\n"
                "  \"overall_score\": 7\n"
                "}"
            )
            summary_resp = get_ai_response(summary_prompt, expect_json=True)
            if isinstance(summary_resp, dict) and not summary_resp.get('error'):
                session['interview_summary'] = summary_resp
            else:
                app.logger.warning(f"Summary generation failed, using fallback. Detail: {summary_resp}")
                session['interview_summary'] = {
                    'strengths': ['Good fundamentals', 'Communicates clearly'],
                    'improvements': ['Add examples with metrics', 'Deepen domain details'],
                    'resources': ['https://roadmap.sh', 'https://refactoring.guru'],
                    'overall_score': normalized_score if isinstance(normalized_score, (int, float)) else 7
                }
            session['feedback_received'] = True

            # Save in DB
            score = normalized_score if isinstance(normalized_score, (int, float)) else (feedback.get('score', 7) if isinstance(feedback, dict) else 7)
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO interview_history (date, role, type, domain, score) VALUES (%s, %s, %s, %s, %s)",
                    (
                        datetime.now(),
                        session['job_role'],
                        session['interview_type'],
                        session['domain'] if session['interview_type'] == 'Technical' else 'N/A',
                        score
                    )
                )
                conn.commit()
                cursor.close()
                conn.close()
            except Exception as db_err:
                app.logger.error(f"Database error: {db_err}")

            return jsonify({
                'status': 'complete',
                'feedback': normalized_feedback_text,
                'score': score,
                'summary': session['interview_summary']
            })
    except Exception as e:
        app.logger.error(f"Error in submit_answer: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/current_question', methods=['GET'])
def current_question():
    try:
        if not session.get('interview_started') or 'questions' not in session:
            return jsonify({'status': 'error', 'message': 'Interview not configured yet'}), 400
        idx = session.get('current_question_index', 0)
        return jsonify({
            'status': 'success',
            'question': session['questions'][idx],
            'question_index': idx + 1,
            'total_questions': len(session['questions'])
        })
    except Exception as e:
        app.logger.error(f"Error in current_question: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/history')
def get_history():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT date, role, type, domain, score FROM interview_history ORDER BY date DESC")
        history = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(history)
    except Exception as db_err:
        app.logger.error(f"Database error: {db_err}")
        return jsonify([])


@app.route('/export_pdf')
def export_pdf():
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Title
    p.setFont('Helvetica-Bold', 16)
    p.drawString(100, height - 100, 'Interview Simulation Report')
    p.setFont('Helvetica', 12)
    p.drawString(100, height - 130, f'Job Role: {session.get("job_role", "N/A")}')
    p.drawString(100, height - 150, f'Interview Type: {session.get("interview_type", "N/A")}')
    if session.get('interview_type') == 'Technical':
        p.drawString(100, height - 170, f'Domain: {session.get("domain", "N/A")}')
    p.drawString(100, height - 190, f'Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}')

    y_position = height - 230
    summary = session.get('interview_summary', {})

    if isinstance(summary, str):
        summary = {
            'strengths': ['Good technical knowledge', 'Clear communication'],
            'improvements': ['Provide more examples', 'Better structure'],
            'resources': ['Practice more interviews', 'Review technical concepts'],
            'overall_score': 7
        }

    p.setFont('Helvetica-Bold', 14)
    p.drawString(100, y_position, 'Summary')
    y_position -= 30

    p.setFont('Helvetica-Bold', 12)
    p.drawString(100, y_position, 'Strengths:')
    y_position -= 20
    p.setFont('Helvetica', 12)
    for strength in summary.get('strengths', []):
        p.drawString(120, y_position, f'• {strength}')
        y_position -= 20

    p.setFont('Helvetica-Bold', 12)
    p.drawString(100, y_position, 'Areas for Improvement:')
    y_position -= 20
    p.setFont('Helvetica', 12)
    for improvement in summary.get('improvements', []):
        p.drawString(120, y_position, f'• {improvement}')
        y_position -= 20

    p.setFont('Helvetica-Bold', 12)
    p.drawString(100, y_position, 'Suggested Resources:')
    y_position -= 20
    p.setFont('Helvetica', 12)
    for resource in summary.get('resources', []):
        p.drawString(120, y_position, f'• {resource}')
        y_position -= 20

    p.setFont('Helvetica-Bold', 12)
    p.drawString(100, y_position, f'Overall Score: {summary.get("overall_score", "N/A")}/10')

    p.showPage()
    p.save()

    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='interview_report.pdf', mimetype='application/pdf')


if __name__ == '__main__':
    app.run(debug=True, port=5000)
