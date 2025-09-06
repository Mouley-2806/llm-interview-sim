from flask import Flask, render_template, request, jsonify, session, send_file
from flask_cors import CORS
import openai
import json
import os
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from io import BytesIO
import time
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key')
CORS(app, origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5000"])  # Enable CORS for specific origins

# Add logging
logging.basicConfig(level=logging.DEBUG)

# Initialize OpenAI (if API key is available)
openai_api_key = os.getenv('OPENAI_API_KEY')
if openai_api_key:
    openai.api_key = openai_api_key

def get_ai_response(prompt, max_tokens=500):
    """
    Get response from OpenAI API or use mock responses if no API key is available
    """
    # If no OpenAI API key, use mock responses
    if not openai_api_key:
        time.sleep(1)  # Simulate API delay
        
        # Mock responses for different types of prompts
        if 'technical' in prompt.lower():
            return [
                'Explain the difference between let, const, and var in JavaScript.',
                'Describe how you would implement a responsive design for a web application.',
                'What are React hooks and why are they important?',
                'How would you optimize website performance?',
                'Explain the concept of closures in JavaScript with an example.'
            ]
        elif 'behavioral' in prompt.lower():
            return [
                'Tell me about a time you had to deal with a difficult teammate.',
                'Describe a project where you had to meet a tight deadline.',
                'Give an example of how you\'ve handled feedback on your work.',
                'Tell me about a time you took initiative on a project.',
                'Describe a situation where you had to persuade others to adopt your idea.'
            ]
        elif 'evaluate' in prompt.lower():
            return {
                'feedback': 'Well done! You provided a comprehensive answer with good structure and relevant examples.',
                'score': 8,
                'suggestions': 'Consider using the STAR method (Situation, Task, Action, Result) to structure your answers for behavioral questions.'
            }
        elif 'summary' in prompt.lower():
            return {
                'strengths': ['Good technical knowledge', 'Clear communication style'],
                'improvements': ['Provide more specific examples', 'Structure answers more effectively'],
                'resources': ['https://leetcode.com for technical practice', 'https://interviewing.io for mock interviews'],
                'overall_score': 7
            }
    
    # If OpenAI API key is available, make actual API calls
    try:
        response = openai.ChatCompletion.create(
            model='gpt-3.5-turbo',
            messages=[
                {'role': 'system', 'content': 'You are a helpful interview coach.'},
                {'role': 'user', 'content': prompt}
            ],
            max_tokens=max_tokens,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        return {'error': f'OpenAI API error: {str(e)}'}

@app.route('/')
def index():
    return render_template('index.html')

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
        
        # Generate questions based on interview type
        if session['interview_type'] == 'Technical':
            prompt = f'Generate 5 technical interview questions for {session["job_role"]} in {session["domain"]}'
            questions_response = get_ai_response(prompt)
            if isinstance(questions_response, list):
                session['questions'] = questions_response
            else:
                # If we get a string response, use default questions
                session['questions'] = [
                    'Explain the difference between let, const, and var in JavaScript.',
                    'Describe how you would implement a responsive design for a web application.',
                    'What are React hooks and why are they important?',
                    'How would you optimize website performance?',
                    'Explain the concept of closures in JavaScript with an example.'
                ]
        else:
            prompt = f'Generate 5 behavioral interview questions for {session["job_role"]}'
            questions_response = get_ai_response(prompt)
            if isinstance(questions_response, list):
                session['questions'] = questions_response
            else:
                # If we get a string response, use default questions
                session['questions'] = [
                    'Tell me about a time you had to deal with a difficult teammate.',
                    'Describe a project where you had to meet a tight deadline.',
                    'Give an example of how you\'ve handled feedback on your work.',
                    'Tell me about a time you took initiative on a project.',
                    'Describe a situation where you had to persuade others to adopt your idea.'
                ]
        
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

@app.route('/configure', methods=['GET'])
def get_question():
    """Get the current question from session"""
    try:
        app.logger.debug("GET /configure called")
        app.logger.debug(f"Session data: {dict(session)}")
        
        if not session.get('interview_started'):
            return jsonify({'status': 'error', 'message': 'Interview not started. Please start from the homepage.'}), 400
        
        question_index = session.get('current_question_index', 0)
        questions = session.get('questions', [])
        
        if not questions:
            return jsonify({'status': 'error', 'message': 'No questions found. Please start a new interview.'}), 400
            
        if question_index >= len(questions):
            return jsonify({'status': 'error', 'message': 'Interview completed. No more questions.'}), 400
        
        return jsonify({
            'status': 'success', 
            'question': questions[question_index],
            'question_index': question_index + 1,
            'total_questions': len(questions)
        })
    except Exception as e:
        app.logger.error(f"Error in get_question: {str(e)}")
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
        prompt = f'Evaluate this answer for a {session.get("job_role")} position:\nQuestion: {question}\nAnswer: {user_answer}\n\nProvide feedback on clarity, correctness, and completeness. Also provide a score from 1-10 and suggestions for improvement.'
        feedback = get_ai_response(prompt)
        
        # Store feedback
        if 'feedback_data' not in session:
            session['feedback_data'] = []
        
        session['feedback_data'].append({
            'question': question,
            'answer': user_answer,
            'feedback': feedback
        })
        
        # Move to next question or finish interview
        if question_index < len(session['questions']) - 1:
            session['current_question_index'] = question_index + 1
            next_question = session['questions'][session['current_question_index']]
            
            return jsonify({
                'status': 'next_question',
                'feedback': feedback,
                'question': next_question,
                'question_index': session['current_question_index'] + 1,
                'total_questions': len(session['questions'])
            })
        else:
            # Interview is complete, generate summary
            prompt = f'Generate a summary for a {session["interview_type"]} interview for {session["job_role"]} position. Include strengths, areas for improvement, suggested resources, and an overall score out of 10.'
            session['interview_summary'] = get_ai_response(prompt)
            session['feedback_received'] = True
            
            # Save to history
            if 'interview_history' not in session:
                session['interview_history'] = []
                
            session['interview_history'].append({
                'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'role': session['job_role'],
                'type': session['interview_type'],
                'domain': session['domain'] if session['interview_type'] == 'Technical' else 'N/A',
                'score': 7  # This would be extracted from the summary in a real implementation
            })
            
            return jsonify({
                'status': 'complete',
                'feedback': feedback,
                'summary': session['interview_summary']
            })
    except Exception as e:
        app.logger.error(f"Error in submit_answer: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/history')
def get_history():
    history = session.get('interview_history', [])
    return jsonify(history)

@app.route('/export_pdf')
def export_pdf():
    # Create a PDF with the interview results
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # Set up title
    p.setFont('Helvetica-Bold', 16)
    p.drawString(100, height - 100, 'Interview Simulation Report')
    p.setFont('Helvetica', 12)
    p.drawString(100, height - 130, f'Job Role: {session.get("job_role", "N/A")}')
    p.drawString(100, height - 150, f'Interview Type: {session.get("interview_type", "N/A")}')
    if session.get('interview_type') == 'Technical':
        p.drawString(100, height - 170, f'Domain: {session.get("domain", "N/A")}')
    p.drawString(100, height - 190, f'Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    
    # Add summary - handle case where summary might be a string
    y_position = height - 230
    summary = session.get('interview_summary', {})
    
    # If summary is a string (from OpenAI response), create a default structure
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
        if y_position < 100:  # Prevent writing off the page
            p.showPage()
            y_position = height - 100
    
    p.setFont('Helvetica-Bold', 12)
    p.drawString(100, y_position, 'Areas for Improvement:')
    y_position -= 20
    p.setFont('Helvetica', 12)
    for improvement in summary.get('improvements', []):
        p.drawString(120, y_position, f'• {improvement}')
        y_position -= 20
        if y_position < 100:  # Prevent writing off the page
            p.showPage()
            y_position = height - 100
    
    p.setFont('Helvetica-Bold', 12)
    p.drawString(100, y_position, 'Suggested Resources:')
    y_position -= 20
    p.setFont('Helvetica', 12)
    for resource in summary.get('resources', []):
        p.drawString(120, y_position, f'• {resource}')
        y_position -= 20
        if y_position < 100:  # Prevent writing off the page
            p.showPage()
            y_position = height - 100
    
    p.setFont('Helvetica-Bold', 12)
    p.drawString(100, y_position, f'Overall Score: {summary.get("overall_score", "N/A")}/10')
    
    p.showPage()
    p.save()
    
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='interview_report.pdf', mimetype='application/pdf')

@app.route('/interview')
def interview():
    return render_template('interview.html')

@app.route('/summary')
def summary():
    return render_template('summary.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)