from flask import Flask, render_template, request, jsonify, session, send_file, send_from_directory, redirect
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

def _parse_json_like(content, prompt=""):
    """Enhanced JSON parsing for AI responses - more aggressive parsing"""
    import re
    
    if not isinstance(content, str):
        return content
    
    # Clean up the content - remove extra whitespace and newlines
    content = content.strip()
    app.logger.debug(f"Parsing content: {content[:300]}...")
    
    # Try standard JSON parsing first
    try:
        result = json.loads(content)
        app.logger.debug("Standard JSON parsing successful")
        return result
    except json.JSONDecodeError:
        pass
    
    # Remove markdown code blocks if present
    if content.startswith('```') and content.endswith('```'):
        content = re.sub(r'^```(?:json)?\s*', '', content, flags=re.IGNORECASE)
        content = re.sub(r'\s*```$', '', content)
        content = content.strip()
    
    # Try JSON parsing again after cleaning
    try:
        result = json.loads(content)
        app.logger.debug("JSON parsing successful after cleaning")
        return result
    except json.JSONDecodeError:
        pass
    
    # Try to find JSON objects with more flexible matching
    json_patterns = [
        r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',  # Nested objects
        r'\{.*?\}',  # Simple objects
    ]
    
    for pattern in json_patterns:
        json_match = re.search(pattern, content, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group())
                app.logger.debug("JSON object extraction successful")
                return result
            except json.JSONDecodeError:
                continue
    
    # Try to find JSON arrays with more flexible matching
    array_patterns = [
        r'\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]',  # Nested arrays
        r'\[.*?\]',  # Simple arrays
    ]
    
    for pattern in array_patterns:
        array_match = re.search(pattern, content, re.DOTALL)
        if array_match:
            try:
                result = json.loads(array_match.group())
                app.logger.debug("JSON array extraction successful")
                return result
            except json.JSONDecodeError:
                continue
    
    # For question generation, try to extract questions from various formats
    if any(keyword in prompt.lower() for keyword in ['generate', 'questions', 'interview']):
        app.logger.info(f"Attempting to extract questions from content: {content[:200]}...")
        
        # Try to extract questions from malformed JSON-like format
        questions = re.findall(r'"([^"]+)"', content)
        if len(questions) >= 3:  # At least 3 questions found
            app.logger.info(f"Extracted {len(questions)} questions from quoted strings")
            return questions
        
        # Try to extract questions from numbered format
        numbered_questions = re.findall(r'\d+\.\s*([^\n]+)', content)
        if len(numbered_questions) >= 3:
            app.logger.info(f"Extracted {len(numbered_questions)} questions from numbered format")
            return numbered_questions
        
        # Try to extract questions from bullet format
        bullet_questions = re.findall(r'[-*]\s*([^\n]+)', content)
        if len(bullet_questions) >= 3:
            app.logger.info(f"Extracted {len(bullet_questions)} questions from bullet format")
            return bullet_questions
        
        # Try to extract questions from line-by-line format
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        valid_questions = []
        for line in lines:
            # Skip lines that look like metadata or formatting
            if (not line.startswith('[') and not line.startswith('{') and 
                not line.startswith('```') and not line.startswith('Generate') and
                len(line) > 20 and '?' in line):
                valid_questions.append(line)
        
        if len(valid_questions) >= 3:
            app.logger.info(f"Extracted {len(valid_questions)} questions from line format")
            return valid_questions
    
    # For feedback/summary generation, try to extract structured data
    if any(keyword in prompt.lower() for keyword in ['feedback', 'summary', 'evaluate', 'score']):
        app.logger.info(f"Attempting to extract structured data from content: {content[:200]}...")
        
        # Try to extract key-value pairs
        feedback_data = {}
        
        # Look for score
        score_match = re.search(r'(?:score|rating)[\s:]*(\d+)', content, re.IGNORECASE)
        if score_match:
            feedback_data['score'] = int(score_match.group(1))
        
        # Look for feedback text
        feedback_match = re.search(r'(?:feedback|evaluation|assessment)[\s:]*([^.]+)', content, re.IGNORECASE)
        if feedback_match:
            feedback_data['feedback'] = feedback_match.group(1).strip()
        
        # Look for suggestions
        suggestions_match = re.search(r'(?:suggestion|improvement|recommendation)[\s:]*([^.]+)', content, re.IGNORECASE)
        if suggestions_match:
            feedback_data['suggestions'] = suggestions_match.group(1).strip()
        
        if feedback_data:
            app.logger.info(f"Extracted structured feedback data: {feedback_data}")
            return feedback_data
    
    # Try to extract any quoted strings as final fallback
    quoted_strings = re.findall(r'"([^"]+)"', content)
    if len(quoted_strings) >= 2:
        app.logger.info(f"Extracted {len(quoted_strings)} strings from content")
        return quoted_strings
    
    app.logger.warning(f"Could not parse content: {content[:100]}...")
    return None

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
                # Intelligent mock feedback based on answer content
                if 'wrong' in prompt.lower() or 'incorrect' in prompt.lower() or 'error' in prompt.lower():
                    return {
                        "feedback": "This answer contains several technical misconceptions that need correction. The fundamental understanding appears to be incorrect.",
                        "score": 2,
                        "suggestions": "Study the basics of this topic and understand the correct concepts before attempting to answer.",
                        "corrections": "The main issues are: [Technical errors would be identified here]. The correct approach is: [Correct information would be provided here]."
                    }
                elif 'good' in prompt.lower() or 'excellent' in prompt.lower():
                    return {
                        "feedback": "Excellent technical depth and clear examples. This demonstrates strong understanding of the concepts.",
                        "score": 9,
                        "suggestions": "Continue building on this solid foundation with more advanced topics.",
                        "corrections": ""
                    }
                else:
                    return {
                        "feedback": "Good structure and clear communication. Consider adding specific examples to strengthen your response.",
                        "score": 7,
                        "suggestions": "Add concrete examples with metrics and outcomes.",
                        "corrections": ""
                    }
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
                    app.logger.error(f"All OpenRouter models failed. Last error: {response.status_code} - {response.text}")
                    # If it's a 401 error, suggest checking API key
                    if response.status_code == 401:
                        app.logger.error("401 Unauthorized - Check your OpenRouter API key")
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
            parsed_result = _parse_json_like(content, prompt)
            if parsed_result is not None:
                return parsed_result
            else:
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

@app.route('/test_scoring')
def test_scoring():
    """Test the improved scoring system"""
    try:
        # Test with a good answer
        good_answer_prompt = (
            "You are an expert interviewer evaluating a technical interview answer for a Software Engineer position.\n\n"
            "Question: Explain how you would optimize a slow database query.\n"
            "Answer: I would first analyze the query execution plan using EXPLAIN to identify bottlenecks. "
            "Then I'd add appropriate indexes on the columns used in WHERE and JOIN clauses. "
            "I'd also consider query rewriting to avoid subqueries and use proper JOINs. "
            "In my previous project, I reduced query time from 5 seconds to 200ms by adding a composite index on user_id and created_date columns.\n\n"
            "Technical Interview Scoring Criteria:\n"
            "- 9-10: Excellent technical depth, clear examples, demonstrates expertise, all information correct\n"
            "- 7-8: Good technical understanding, some examples, mostly correct with minor inaccuracies\n"
            "- 5-6: Basic technical knowledge, limited examples, some gaps or partially incorrect\n"
            "- 3-4: Weak technical understanding, few/no examples, major gaps or significant errors\n"
            "- 1-2: Poor technical knowledge, incorrect information, no examples, fundamental misconceptions\n\n"
            "As an expert interviewer, evaluate this answer holistically and assign a fair score based on:\n"
            "- Technical accuracy and correctness\n"
            "- Depth of understanding demonstrated\n"
            "- Use of specific examples and metrics\n"
            "- Clarity and structure of response\n"
            "- Relevance to the question asked\n"
            "- Demonstration of practical experience\n\n"
            "Consider the context and provide constructive feedback.\n"
            "If there are technical errors, explain what's wrong and provide the correct information.\n\n"
            "Respond ONLY in this JSON format:\n"
            "{\n"
            "  \"feedback\": \"2-3 sentence evaluation highlighting strengths, weaknesses, and areas for improvement\",\n"
            "  \"score\": 7,\n"
            "  \"suggestions\": \"One specific actionable improvement tip\",\n"
            "  \"corrections\": \"If there are technical errors, briefly explain the correct approach\"\n"
            "}"
        )
        
        result = get_ai_response(good_answer_prompt, expect_json=True, max_tokens=300)
        
        return jsonify({
            'status': 'success',
            'test_scoring_result': result,
            'expected_score_range': '7-9 (should be high due to specific example and technical depth)'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/test_wrong_answer')
def test_wrong_answer():
    """Test how AI handles wrong answers"""
    try:
        # Test with a wrong answer
        wrong_answer_prompt = (
            "You are an expert interviewer evaluating a technical interview answer for a Software Engineer position.\n\n"
            "Question: What is the difference between SQL and NoSQL databases?\n"
            "Answer: SQL databases are faster than NoSQL databases because they use tables. "
            "NoSQL databases are slower and only store JSON files. "
            "You should always use SQL for everything because it's better. "
            "NoSQL is just a trend and doesn't work well.\n\n"
            "Technical Interview Scoring Criteria:\n"
            "- 9-10: Excellent technical depth, clear examples, demonstrates expertise, all information correct\n"
            "- 7-8: Good technical understanding, some examples, mostly correct with minor inaccuracies\n"
            "- 5-6: Basic technical knowledge, limited examples, some gaps or partially incorrect\n"
            "- 3-4: Weak technical understanding, few/no examples, major gaps or significant errors\n"
            "- 1-2: Poor technical knowledge, incorrect information, no examples, fundamental misconceptions\n\n"
            "As an expert interviewer, evaluate this answer holistically and assign a fair score based on:\n"
            "- Technical accuracy and correctness\n"
            "- Depth of understanding demonstrated\n"
            "- Use of specific examples and metrics\n"
            "- Clarity and structure of response\n"
            "- Relevance to the question asked\n"
            "- Demonstration of practical experience\n\n"
            "Consider the context and provide constructive feedback.\n"
            "If there are technical errors, explain what's wrong and provide the correct information.\n\n"
            "Respond ONLY in this JSON format:\n"
            "{\n"
            "  \"feedback\": \"2-3 sentence evaluation highlighting strengths, weaknesses, and areas for improvement\",\n"
            "  \"score\": 7,\n"
            "  \"suggestions\": \"One specific actionable improvement tip\",\n"
            "  \"corrections\": \"If there are technical errors, briefly explain the correct approach\"\n"
            "}"
        )
        
        result = get_ai_response(wrong_answer_prompt, expect_json=True, max_tokens=300)
        
        return jsonify({
            'status': 'success',
            'test_wrong_answer_result': result,
            'expected_score_range': '1-3 (should be low due to multiple technical errors and misconceptions)',
            'note': 'This answer contains several technical errors and should receive a low score with corrections'
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

@app.route('/test_question_generation')
def test_question_generation():
    """Test question generation with current settings"""
    try:
        job_role = session.get('job_role', 'Software Engineer')
        interview_type = session.get('interview_type', 'Technical')
        domain = session.get('domain', 'General')
        
        if interview_type == 'Technical':
            prompt = (
                f"You are an expert interviewer. Generate exactly 5 technical interview questions for a {job_role} position in {domain}. "
                f"Make them specific, challenging, and relevant to the role. "
                f"CRITICAL: Respond ONLY with a valid JSON array of exactly 5 strings. "
                f"Example: [\"What is your experience with React hooks and state management?\", \"How would you optimize a slow database query?\", \"Explain the difference between REST and GraphQL APIs.\", \"Describe your approach to testing frontend components.\", \"How do you handle cross-browser compatibility issues?\"]"
            )
        else:
            prompt = (
                f"You are an expert interviewer. Generate exactly 5 behavioral interview questions for a {job_role} position. "
                f"Focus on leadership, teamwork, problem-solving, and past experiences. "
                f"CRITICAL: Respond ONLY with a valid JSON array of exactly 5 strings. "
                f"Example: [\"Tell me about a time you led a team through a difficult project.\", \"Describe a situation where you had to resolve a conflict.\", \"Give an example of how you handled a tight deadline.\", \"Tell me about a time you failed and what you learned.\", \"Describe your approach to mentoring junior team members.\"]"
            )
        
        result = get_ai_response(prompt, expect_json=True, max_tokens=800)
        
        return jsonify({
            'status': 'success',
            'prompt': prompt,
            'raw_response': result,
            'parsed_successfully': isinstance(result, list) and len(result) >= 3,
            'question_count': len(result) if isinstance(result, list) else 0
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/test_api_key')
def test_api_key():
    """Test if the OpenRouter API key is valid"""
    openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
    
    if not openrouter_api_key:
        return jsonify({
            'status': 'error',
            'message': 'No OpenRouter API key found in environment'
        })
    
    try:
        # Test with a simple request
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5000",
            "X-Title": "LLM Interview Sim"
        }
        payload = {
            "model": "mistralai/mistral-7b-instruct:free",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 5
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        return jsonify({
            'status': 'success' if response.status_code == 200 else 'error',
            'status_code': response.status_code,
            'response_text': response.text,
            'api_key_length': len(openrouter_api_key),
            'api_key_prefix': openrouter_api_key[:10] + '...' if len(openrouter_api_key) > 10 else openrouter_api_key,
            'message': 'API key is valid' if response.status_code == 200 else 'API key authentication failed'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error testing API key: {str(e)}'
        })

@app.route('/configure', methods=['POST'])
def configure_interview():
    try:
        data = request.get_json()
        app.logger.debug(f"Received data: {data}")

        if not data:
            app.logger.error("No data received in configure_interview")
            return jsonify({'status': 'error', 'message': 'No data received'}), 400

        # Clear any existing session data to avoid size issues
        session.clear()
        
        # Set session data (minimal to avoid cookie size limits)
        session['job_role'] = data.get('job_role', 'Software Engineer')
        session['interview_type'] = data.get('interview_type', 'Technical')
        session['domain'] = data.get('domain', 'General')
        session['interview_started'] = True
        session['current_question_index'] = 0
        session['user_answers'] = []
        session['feedback_scores'] = []
        session['feedback_received'] = False

        # Generate questions using AI
        if session['interview_type'] == 'Technical':
            prompt = (
                f"You are an expert interviewer. Generate exactly 5 technical interview questions for a {session['job_role']} position in {session['domain']}. "
                f"Make them specific, challenging, and relevant to the role. "
                f"CRITICAL: Respond ONLY with a valid JSON array of exactly 5 strings. "
                f"Example: [\"What is your experience with React hooks and state management?\", \"How would you optimize a slow database query?\", \"Explain the difference between REST and GraphQL APIs.\", \"Describe your approach to testing frontend components.\", \"How do you handle cross-browser compatibility issues?\"]"
            )
        else:
            prompt = (
                f"You are an expert interviewer. Generate exactly 5 behavioral interview questions for a {session['job_role']} position. "
                f"Focus on leadership, teamwork, problem-solving, and past experiences. "
                f"CRITICAL: Respond ONLY with a valid JSON array of exactly 5 strings. "
                f"Example: [\"Tell me about a time you led a team through a difficult project.\", \"Describe a situation where you had to resolve a conflict.\", \"Give an example of how you handled a tight deadline.\", \"Tell me about a time you failed and what you learned.\", \"Describe your approach to mentoring junior team members.\"]"
            )

        questions_response = get_ai_response(prompt, expect_json=True, max_tokens=800)
        app.logger.debug(f"Questions response: {questions_response}")
        
        # Handle response - be more persistent with AI when it's enabled
        fake_ai = os.getenv('FAKE_AI', 'false').lower() in ['1', 'true', 'yes']
        
        if isinstance(questions_response, dict) and questions_response.get('error'):
            app.logger.warning(f"Question generation failed, trying AI fallback. Detail: {questions_response}")
            
            # Try multiple AI fallback approaches when AI is enabled
            if not fake_ai:
                fallback_attempts = [
                    f"Generate 5 {session['interview_type'].lower()} interview questions for {session['job_role']}. Return as JSON array.",
                    f"Create 5 interview questions for {session['job_role']} position. Format: [\"Q1\", \"Q2\", \"Q3\", \"Q4\", \"Q5\"]",
                    f"List 5 {session['interview_type'].lower()} questions for {session['job_role']}. Use JSON format."
                ]
                
                for i, fallback_prompt in enumerate(fallback_attempts):
                    app.logger.info(f"Trying AI fallback attempt {i+1}")
                    fallback_questions = get_ai_response(fallback_prompt, expect_json=True, max_tokens=600)
                    
                    if isinstance(fallback_questions, list) and len(fallback_questions) >= 3:
                        session['questions'] = fallback_questions
                        app.logger.info(f"AI fallback attempt {i+1} successful")
                        break
                else:
                    # If all AI attempts fail, return error instead of hardcoded
                    app.logger.error("All AI attempts failed for question generation")
                    return jsonify({'status': 'error', 'message': 'Failed to generate questions. Please try again.'}), 500
            else:
                # In FAKE_AI mode, use hardcoded fallback
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
            if not fake_ai:
                # In real AI mode, try to extract questions from the response
                if isinstance(questions_response, str):
                    # Try to parse the string response
                    parsed = _parse_json_like(questions_response, prompt)
                    if isinstance(parsed, list) and len(parsed) >= 3:
                        session['questions'] = parsed
                    else:
                        return jsonify({'status': 'error', 'message': 'Failed to parse AI response. Please try again.'}), 500
                else:
                    return jsonify({'status': 'error', 'message': 'Invalid AI response format. Please try again.'}), 500
            else:
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
        interview_type = session.get('interview_type', 'Technical')
        
        if interview_type == 'Technical':
            scoring_criteria = """
            Technical Interview Scoring Criteria:
            - 9-10: Excellent technical depth, clear examples, demonstrates expertise, all information correct
            - 7-8: Good technical understanding, some examples, mostly correct with minor inaccuracies
            - 5-6: Basic technical knowledge, limited examples, some gaps or partially incorrect
            - 3-4: Weak technical understanding, few/no examples, major gaps or significant errors
            - 1-2: Poor technical knowledge, incorrect information, no examples, fundamental misconceptions
            """
        else:
            scoring_criteria = """
            Behavioral Interview Scoring Criteria:
            - 9-10: Excellent STAR method, specific examples, clear outcomes, demonstrates strong competencies
            - 7-8: Good structure, relevant examples, shows impact, minor gaps in examples
            - 5-6: Basic structure, some examples, limited impact shown, generic responses
            - 3-4: Weak structure, vague examples, unclear outcomes, doesn't address the question well
            - 1-2: Poor structure, no examples, no clear outcomes, completely off-topic or inappropriate
            """
        
        prompt = (
            f"You are an expert interviewer evaluating a {interview_type.lower()} interview answer for a {session.get('job_role')} position.\n\n"
            f"Question: {question}\n"
            f"Answer: {user_answer}\n\n"
            f"{scoring_criteria}\n"
            "As an expert interviewer, evaluate this answer holistically and assign a fair score based on:\n"
            "- Technical accuracy and correctness\n"
            "- Depth of understanding demonstrated\n"
            "- Use of specific examples and metrics\n"
            "- Clarity and structure of response\n"
            "- Relevance to the question asked\n"
            "- Demonstration of practical experience\n\n"
            "Consider the context:\n"
            "- Is this a junior or senior level position?\n"
            "- What level of detail is expected for this question?\n"
            "- Are there any misconceptions that need correction?\n"
            "- Does the answer show genuine understanding or just memorization?\n\n"
            "Provide constructive feedback that helps the candidate improve while being honest about their performance.\n"
            "If there are technical errors, explain what's wrong and provide the correct information.\n\n"
            "Respond ONLY in this JSON format:\n"
            "{\n"
            "  \"feedback\": \"2-3 sentence evaluation highlighting strengths, weaknesses, and areas for improvement\",\n"
            "  \"score\": 7,\n"
            "  \"suggestions\": \"One specific actionable improvement tip\",\n"
            "  \"corrections\": \"If there are technical errors, briefly explain the correct approach\"\n"
            "}"
        )
        feedback = get_ai_response(prompt, expect_json=True)
        
        # Normalize feedback structure - be more persistent when AI is enabled
        fake_ai = os.getenv('FAKE_AI', 'false').lower() in ['1', 'true', 'yes']
        
        if isinstance(feedback, dict) and not feedback.get('error'):
            normalized_feedback_text = feedback.get('feedback') or json.dumps(feedback)
            normalized_score = feedback.get('score')
            normalized_corrections = feedback.get('corrections', '')
        else:
            # Try multiple AI fallback approaches when AI is enabled
            if not fake_ai:
                app.logger.warning(f"Feedback generation failed, trying AI fallback. Detail: {feedback}")
                
                fallback_attempts = [
                    f"Evaluate this answer: {user_answer}. Give feedback, score (1-10), and suggestions. Use JSON format.",
                    f"Rate this interview answer: {user_answer}. Provide feedback and score. JSON format required.",
                    f"Assess this response: {user_answer}. Give evaluation and score. Return as JSON."
                ]
                
                for i, fallback_prompt in enumerate(fallback_attempts):
                    app.logger.info(f"Trying AI feedback fallback attempt {i+1}")
                    fallback_feedback = get_ai_response(fallback_prompt, expect_json=True, max_tokens=500)
                    
                    if isinstance(fallback_feedback, dict) and not fallback_feedback.get('error'):
                        normalized_feedback_text = fallback_feedback.get('feedback', 'Good response with room for improvement.')
                        normalized_score = fallback_feedback.get('score', 7)
                        normalized_corrections = fallback_feedback.get('corrections', '')
                        app.logger.info(f"AI feedback fallback attempt {i+1} successful")
                        break
                else:
                    # If all AI attempts fail, return error instead of hardcoded
                    app.logger.error("All AI attempts failed for feedback generation")
                    return jsonify({'status': 'error', 'message': 'Failed to generate feedback. Please try again.'}), 500
            else:
                # In FAKE_AI mode, use hardcoded fallback
                app.logger.warning(f"Feedback generation failed or invalid, falling back. Detail: {feedback}")
                normalized_feedback_text = "Good structure and clear communication. Consider adding specific examples to strengthen your response."
                normalized_score = 7
                normalized_corrections = ""

        # Store only essential data to avoid session size limits
        if 'feedback_scores' not in session:
            session['feedback_scores'] = []
        
        # Only store the score, not the full feedback object
        session['feedback_scores'].append(normalized_score)

        # Next or finish
        if question_index < len(session['questions']) - 1:
            session['current_question_index'] = question_index + 1
            next_question = session['questions'][session['current_question_index']]
            return jsonify({
                'status': 'next_question',
                'feedback': normalized_feedback_text,
                'score': normalized_score,
                'corrections': normalized_corrections,
                'question': next_question,
                'question_index': session['current_question_index'] + 1,
                'total_questions': len(session['questions'])
            })
        else:
            # Get all answers for context
            all_answers = session.get('user_answers', [])
            all_questions = session.get('questions', [])
            
            summary_prompt = (
                f"Generate a comprehensive interview summary for a {session['interview_type']} interview for {session['job_role']} position.\n\n"
                "Interview Questions and Answers:\n"
            )
            
            for i, (q, a) in enumerate(zip(all_questions, all_answers), 1):
                summary_prompt += f"Q{i}: {q}\nA{i}: {a}\n\n"
            
            summary_prompt += (
                "You are an expert interviewer providing a comprehensive evaluation of this interview performance.\n\n"
                "Based on the actual interview responses above, provide:\n"
                "- 3 specific strengths observed in the answers (be specific, not generic)\n"
                "- 3 concrete areas for improvement based on the actual responses\n"
                "- 3 practical resources for improvement\n"
                "- Overall score (1-10) based on the quality of all answers\n\n"
                "Scoring Guidelines:\n"
                "- 9-10: Excellent answers with specific examples, clear structure, demonstrates expertise\n"
                "- 7-8: Good answers with some examples and clear communication\n"
                "- 5-6: Average answers with basic structure but limited examples\n"
                "- 3-4: Below average answers with weak structure and few examples\n"
                "- 1-2: Poor answers with no structure or examples\n\n"
                "As an expert interviewer, evaluate holistically considering:\n"
                "- Technical accuracy and correctness\n"
                "- Depth of understanding demonstrated\n"
                "- Use of specific examples and metrics\n"
                "- Clarity and structure of responses\n"
                "- Relevance to questions asked\n"
                "- Demonstration of practical experience\n\n"
                "Be honest and specific. Base your evaluation on what was actually said in the answers.\n\n"
                "Respond ONLY in this JSON format:\n"
                "{\n"
                "  \"strengths\": [\"Specific strength based on actual answers\", \"Another specific strength\", \"Third specific strength\"],\n"
                "  \"improvements\": [\"Concrete improvement based on actual gaps\", \"Another concrete improvement\", \"Third concrete improvement\"],\n"
                "  \"resources\": [\"Practical resource 1\", \"Practical resource 2\", \"Practical resource 3\"],\n"
                "  \"overall_score\": 7\n"
                "}"
            )
            summary_resp = get_ai_response(summary_prompt, expect_json=True)
            if isinstance(summary_resp, dict) and not summary_resp.get('error'):
                # Store only essential summary data to avoid session size limits
                session['overall_score'] = summary_resp.get('overall_score', 7)
                session['summary_generated'] = True
                interview_summary = summary_resp
            else:
                # Try multiple AI fallback approaches when AI is enabled
                if not fake_ai:
                    app.logger.warning(f"Summary generation failed, trying AI fallback. Detail: {summary_resp}")
                    
                    fallback_attempts = [
                        f"Generate interview summary for {session['job_role']} position. Give 3 strengths, 3 improvements, 3 resources, overall score. JSON format.",
                        f"Create interview evaluation for {session['interview_type']} interview. Provide strengths, improvements, resources, score. Use JSON.",
                        f"Summarize interview performance for {session['job_role']}. Include strengths, improvements, resources, score. Return JSON."
                    ]
                    
                    for i, fallback_prompt in enumerate(fallback_attempts):
                        app.logger.info(f"Trying AI summary fallback attempt {i+1}")
                        fallback_summary = get_ai_response(fallback_prompt, expect_json=True, max_tokens=400)
                        
                        if isinstance(fallback_summary, dict) and not fallback_summary.get('error'):
                            session['overall_score'] = fallback_summary.get('overall_score', normalized_score if isinstance(normalized_score, (int, float)) else 7)
                            session['summary_generated'] = True
                            interview_summary = fallback_summary
                            app.logger.info(f"AI summary fallback attempt {i+1} successful")
                            break
                    else:
                        # If all AI attempts fail, return error instead of hardcoded
                        app.logger.error("All AI attempts failed for summary generation")
                        return jsonify({'status': 'error', 'message': 'Failed to generate summary. Please try again.'}), 500
                else:
                    # In FAKE_AI mode, use hardcoded fallback
                    app.logger.warning("AI fallback also failed, using hardcoded summary")
                    session['overall_score'] = normalized_score if isinstance(normalized_score, (int, float)) else 7
                    session['summary_generated'] = True
                    interview_summary = {
                        'strengths': ['Clear communication style', 'Good problem-solving approach', 'Structured thinking'],
                        'improvements': ['Provide more specific examples', 'Include metrics and outcomes', 'Expand technical depth'],
                        'resources': ['Practice coding problems on LeetCode', 'Study system design patterns', 'Review industry best practices'],
                        'overall_score': session['overall_score']
                    }
            session['feedback_received'] = True

            return jsonify({
                'status': 'complete',
                'feedback': normalized_feedback_text,
                'score': normalized_score,
                'corrections': normalized_corrections,
                'summary': interview_summary
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

        # Summary - Try to generate AI summary for PDF
        y_position = height - 230
        summary = None
        
        # Try to generate AI summary for PDF if we have answers
        if session.get('user_answers') and len(session.get('user_answers', [])) > 0:
            try:
                pdf_prompt = (
                    f"Generate a brief interview summary for a {session.get('interview_type', 'Technical')} interview for {session.get('job_role', 'Software Engineer')} position. "
                    f"Provide 3 strengths, 3 improvements, 3 resources, and an overall score (1-10). "
                    f"Respond in JSON format with keys: strengths, improvements, resources, overall_score."
                )
                pdf_summary = get_ai_response(pdf_prompt, expect_json=True, max_tokens=400)
                if isinstance(pdf_summary, dict) and not pdf_summary.get('error'):
                    summary = pdf_summary
            except Exception as e:
                app.logger.warning(f"Failed to generate AI summary for PDF: {e}")
        
        # Fallback to hardcoded summary
        if not summary:
            summary = {
                'strengths': ['Clear communication style', 'Good problem-solving approach', 'Structured thinking'],
                'improvements': ['Provide more specific examples', 'Include metrics and outcomes', 'Expand technical depth'],
                'resources': ['Practice coding problems on LeetCode', 'Study system design patterns', 'Review industry best practices'],
                'overall_score': session.get('overall_score', 7)
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
    except Exception as e:
        app.logger.error(f"Error in export_pdf: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/summary')
def summary_page():
    """Render the summary page"""
    try:
        if not session.get('feedback_received'):
            return redirect('/')
        
        # Try to generate AI summary for the summary page
        summary_content = None
        if session.get('user_answers') and len(session.get('user_answers', [])) > 0:
            try:
                summary_prompt = (
                    f"Generate a comprehensive interview summary for a {session.get('interview_type', 'Technical')} interview for {session.get('job_role', 'Software Engineer')} position. "
                    f"Based on the interview responses, provide 3 specific strengths, 3 concrete improvements, 3 practical resources, and an overall score (1-10). "
                    f"Respond in JSON format with keys: strengths, improvements, resources, overall_score."
                )
                summary_content = get_ai_response(summary_prompt, expect_json=True, max_tokens=500)
            except Exception as e:
                app.logger.warning(f"Failed to generate AI summary for summary page: {e}")
        
        # Generate summary data from session
        summary_data = {
            'job_role': session.get('job_role', 'Software Engineer'),
            'interview_type': session.get('interview_type', 'Technical'),
            'domain': session.get('domain', 'General'),
            'overall_score': session.get('overall_score', 7),
            'feedback_scores': session.get('feedback_scores', []),
            'questions': session.get('questions', []),
            'user_answers': session.get('user_answers', []),
            'summary_generated': session.get('summary_generated', False),
            'ai_summary': summary_content if isinstance(summary_content, dict) and not summary_content.get('error') else None
        }
        
        return render_template('summary.html', summary=summary_data)
    except Exception as e:
        app.logger.error(f"Error in summary_page: {str(e)}", exc_info=True)
        return redirect('/')

@app.route('/interview_tips')
def get_interview_tips():
    """Generate AI-based interview tips"""
    try:
        job_role = session.get('job_role', 'Software Engineer')
        interview_type = session.get('interview_type', 'Technical')
        
        tips_prompt = (
            f"Generate 5 practical interview tips for a {interview_type.lower()} interview for a {job_role} position. "
            f"Make them specific, actionable, and relevant to the role. "
            f"Respond as a JSON array of strings, each tip being one string."
        )
        
        tips_response = get_ai_response(tips_prompt, expect_json=True, max_tokens=400)
        
        if isinstance(tips_response, list) and len(tips_response) >= 3:
            return jsonify({
                'status': 'success',
                'tips': tips_response
            })
        else:
            # Try multiple AI fallback approaches when AI is enabled
            fake_ai = os.getenv('FAKE_AI', 'false').lower() in ['1', 'true', 'yes']
            
            if not fake_ai:
                app.logger.warning(f"Tips generation failed, trying AI fallback. Detail: {tips_response}")
                
                fallback_attempts = [
                    f"Give 5 interview tips for {job_role} position. Return as JSON array.",
                    f"List 5 tips for {interview_type.lower()} interviews. Use JSON format.",
                    f"Provide 5 interview advice for {job_role}. Return as JSON array."
                ]
                
                for i, fallback_prompt in enumerate(fallback_attempts):
                    app.logger.info(f"Trying AI tips fallback attempt {i+1}")
                    fallback_tips = get_ai_response(fallback_prompt, expect_json=True, max_tokens=300)
                    
                    if isinstance(fallback_tips, list) and len(fallback_tips) >= 3:
                        return jsonify({
                            'status': 'success',
                            'tips': fallback_tips
                        })
                else:
                    # If all AI attempts fail, return error instead of hardcoded
                    app.logger.error("All AI attempts failed for tips generation")
                    return jsonify({'status': 'error', 'message': 'Failed to generate tips. Please try again.'}), 500
            else:
                # In FAKE_AI mode, use hardcoded fallback
                fallback_tips = [
                    "Research the company and role thoroughly before the interview",
                    "Prepare specific examples using the STAR method (Situation, Task, Action, Result)",
                    "Practice explaining technical concepts in simple terms",
                    "Ask thoughtful questions about the team, projects, and company culture",
                    "Follow up with a thank you email within 24 hours"
                ]
                return jsonify({
                    'status': 'success',
                    'tips': fallback_tips
                })
            
    except Exception as e:
        app.logger.error(f"Error generating interview tips: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    print("Starting working interview app...")
    print(f"FAKE_AI mode: {os.getenv('FAKE_AI', 'false')}")
    app.run(debug=True, port=5000)
