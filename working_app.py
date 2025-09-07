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
import logging
import mysql.connector
import requests

# Load environment variables
if os.path.exists('env.txt'):
    load_dotenv('env.txt')
else:
    load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key')
CORS(app, origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5000"])

# Add logging
logging.basicConfig(level=logging.DEBUG)

def get_ai_response(prompt, max_tokens=500, expect_json=False):
    """AI response function with OpenRouter support"""
    fake_ai = os.getenv('FAKE_AI', 'false').lower() in ['1', 'true', 'yes']
    
    if fake_ai:
        app.logger.debug("Using FAKE_AI mode")
        if expect_json:
            if 'Generate 5' in prompt and 'questions' in prompt:
                return [
                    "Tell me about a challenging project you worked on and your role.",
                    "How do you approach debugging complex, intermittent issues?",
                    "Describe a time you collaborated across teams to deliver a feature.",
                    "Explain a technical concept to a non-technical stakeholder.",
                    "What would you improve about your last project and why?"
                ]
            if 'Provide feedback' in prompt or 'Evaluate this answer' in prompt:
                return {"feedback": "Good structure and clear communication. Consider adding specific examples to strengthen your response.", "score": 7, "suggestions": "Add concrete examples with metrics."}
            if 'Generate a summary' in prompt:
                return {"strengths": ["Clear communication style", "Good problem-solving approach", "Structured thinking"], "improvements": ["Provide more specific examples", "Include metrics and outcomes", "Expand technical depth"], "resources": ["Practice coding problems on LeetCode", "Study system design patterns", "Review industry best practices"], "overall_score": 7}
            return {"message": "OK"}
        return "OK"
    
    # Real AI implementation using OpenRouter
    openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
    if not openrouter_api_key:
        app.logger.error("No OpenRouter API key found")
        return {"error": "No OpenRouter API key configured"}
    
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5000",
            "X-Title": "LLM Interview Sim"
        }
        model = os.getenv('OPENROUTER_MODEL', 'google/gemma-7b-it:free')
        
        # List of models to try in order (working model first)
        models_to_try = [
            model,
            'mistralai/mistral-7b-instruct:free',  # This one works!
            'google/gemma-7b-it:free',
            'gryphe/mythomax-l2-13b:free'
        ]
        
        for current_model in models_to_try:
            payload = {
                "model": current_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.7
            }
            
            app.logger.debug(f"Trying OpenRouter with model: {current_model}")
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                app.logger.debug(f"Success with model: {current_model}")
                break
            else:
                app.logger.warning(f"Model {current_model} failed: {response.status_code} - {response.text}")
                if current_model == models_to_try[-1]:  # Last model failed
                    return {"error": f"All models failed. Last error: {response.status_code} - {response.text}"}
                continue
        
        if response.status_code != 200:
            app.logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
            return {"error": f"API request failed with {response.status_code}"}
        
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            app.logger.error(f"Unexpected OpenRouter response format: {data}")
            return {"error": "Unexpected response format from AI"}
        
        if expect_json:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from the response
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    try:
                        return json.loads(json_match.group())
                    except json.JSONDecodeError:
                        pass
                # If all else fails, return the content as is
                return {"error": "Could not parse JSON from AI response", "raw": content}
        
        return content
        
    except requests.exceptions.Timeout:
        app.logger.error("OpenRouter API timeout")
        return {"error": "AI request timed out"}
    except requests.exceptions.RequestException as e:
        app.logger.error(f"OpenRouter API request error: {str(e)}")
        return {"error": f"AI request failed: {str(e)}"}
    except Exception as e:
        app.logger.error(f"Unexpected error in AI call: {str(e)}")
        return {"error": f"Unexpected error: {str(e)}"}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/interview')
def interview_page():
    return render_template('interview.html')

@app.route('/summary')
def summary_page():
    try:
        summary = session.get('interview_summary')
        app.logger.debug(f"Summary data: {summary}")
        
        if isinstance(summary, str) or not isinstance(summary, dict):
            summary = None
            
        # Provide default values if no summary
        if not summary:
            summary = {
                'strengths': ['Clear communication style', 'Good problem-solving approach', 'Structured thinking'],
                'improvements': ['Provide more specific examples', 'Include metrics and outcomes', 'Expand technical depth'],
                'resources': ['Practice coding problems on LeetCode', 'Study system design patterns', 'Review industry best practices'],
                'overall_score': 7
            }
            
        return render_template(
            'summary.html',
            strengths=summary.get('strengths', []),
            improvements=summary.get('improvements', []),
            resources=summary.get('resources', []),
            overall_score=summary.get('overall_score', 7)
        )
    except Exception as e:
        app.logger.error(f"Error in summary_page: {str(e)}", exc_info=True)
        return f"Error loading summary: {str(e)}", 500

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favico.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'message': 'Server is running'})

@app.route('/test_ai')
def test_ai():
    try:
        result = get_ai_response("Say hello and confirm you are working", max_tokens=50)
        return jsonify({
            'status': 'success',
            'ai_response': result,
            'fake_ai_mode': os.getenv('FAKE_AI', 'false'),
            'openrouter_key_set': bool(os.getenv('OPENROUTER_API_KEY')),
            'model': os.getenv('OPENROUTER_MODEL', 'google/gemma-7b-it:free')
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/test_models')
def test_models():
    """Test which OpenRouter models are working"""
    models_to_test = [
        'google/gemma-7b-it:free',
        'mistralai/mistral-7b-instruct:free', 
        'gryphe/mythomax-l2-13b:free',
        'openrouter/auto:free'
    ]
    
    results = {}
    openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
    
    if not openrouter_api_key:
        return jsonify({'error': 'No OpenRouter API key'})
    
    for model in models_to_test:
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:5000",
                "X-Title": "LLM Interview Sim"
            }
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 10,
                "temperature": 0.7
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            results[model] = {
                'status_code': response.status_code,
                'working': response.status_code == 200,
                'error': response.text if response.status_code != 200 else None
            }
        except Exception as e:
            results[model] = {
                'status_code': 'error',
                'working': False,
                'error': str(e)
            }
    
    return jsonify({
        'status': 'success',
        'model_tests': results,
        'recommended_model': next((model for model, result in results.items() if result['working']), 'none')
    })

@app.route('/configure', methods=['POST'])
def configure_interview():
    try:
        data = request.get_json()
        app.logger.debug(f"Received data: {data}")

        if not data:
            app.logger.error("No data received in configure_interview")
            return jsonify({'status': 'error', 'message': 'No data received'}), 400

        # Set session data
        session['job_role'] = data.get('job_role', 'Software Engineer')
        session['interview_type'] = data.get('interview_type', 'Technical')
        session['domain'] = data.get('domain', 'General')
        session['interview_started'] = True
        session['current_question_index'] = 0
        session['user_answers'] = []
        session['feedback_received'] = False
        session['interview_summary'] = None

        # Generate questions using AI
        if session['interview_type'] == 'Technical':
            prompt = (
                f"Generate 5 technical interview questions for the role of {session['job_role']} "
                f"in the domain of {session['domain']}. "
                "Make them specific and challenging. Respond as a JSON array of strings only, no other text."
            )
        else:
            prompt = (
                f"Generate 5 behavioral interview questions for the role of {session['job_role']}. "
                "Focus on leadership, teamwork, and problem-solving. Respond as a JSON array of strings only, no other text."
            )

        questions_response = get_ai_response(prompt, expect_json=True, max_tokens=800)
        app.logger.debug(f"Questions response: {questions_response}")
        
        # Handle response
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
            app.logger.warning(f"Unexpected questions response format: {type(questions_response)}")
            session['questions'] = [str(questions_response)]

        app.logger.debug(f"Final questions: {session['questions']}")

        return jsonify({
            'status': 'success',
            'question': session['questions'][0],
            'question_index': 1,
            'total_questions': len(session['questions'])
        })
    except Exception as e:
        app.logger.error(f"Error in configure_interview: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Configuration failed: {str(e)}'}), 500

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
                    'strengths': ['Clear communication style', 'Good problem-solving approach', 'Structured thinking'],
                    'improvements': ['Provide more specific examples', 'Include metrics and outcomes', 'Expand technical depth'],
                    'resources': ['Practice coding problems on LeetCode', 'Study system design patterns', 'Review industry best practices'],
                    'overall_score': normalized_score if isinstance(normalized_score, (int, float)) else 7
                }
            session['feedback_received'] = True

            return jsonify({
                'status': 'complete',
                'feedback': normalized_feedback_text,
                'score': normalized_score,
                'summary': session['interview_summary']
            })
    except Exception as e:
        app.logger.error(f"Error in submit_answer: {str(e)}", exc_info=True)
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
        app.logger.error(f"Error in current_question: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/history')
def get_history():
    try:
        # Return empty history for now (no database)
        return jsonify([])
    except Exception as e:
        app.logger.error(f"Error in get_history: {str(e)}", exc_info=True)
        return jsonify([])

@app.route('/export_pdf')
def export_pdf():
    try:
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

        # Summary
        y_position = height - 230
        summary = session.get('interview_summary', {})
        
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
    except Exception as e:
        app.logger.error(f"Error in export_pdf: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("Starting working interview app...")
    print(f"FAKE_AI mode: {os.getenv('FAKE_AI', 'false')}")
    app.run(debug=True, port=5000)
