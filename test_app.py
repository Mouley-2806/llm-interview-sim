from flask import Flask, render_template, request, jsonify, session
import os

app = Flask(__name__)
app.secret_key = 'test-secret-key'

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Interview</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .form-group { margin: 20px 0; }
            input, select { padding: 10px; margin: 5px; width: 300px; }
            button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; }
        </style>
    </head>
    <body>
        <h1>Test Interview App</h1>
        <form id="test-form">
            <div class="form-group">
                <label>Job Role:</label><br>
                <input type="text" id="job_role" value="Software Engineer" required>
            </div>
            <div class="form-group">
                <label>Interview Type:</label><br>
                <select id="interview_type">
                    <option value="Technical">Technical</option>
                    <option value="Behavioral">Behavioral</option>
                </select>
            </div>
            <div class="form-group">
                <label>Domain:</label><br>
                <input type="text" id="domain" value="React">
            </div>
            <button type="submit">Start Test Interview</button>
        </form>
        
        <div id="result" style="margin-top: 20px; padding: 20px; background: #f0f0f0; display: none;">
            <h3>Test Result:</h3>
            <p id="result-text"></p>
        </div>

        <script>
            document.getElementById('test-form').addEventListener('submit', function(e) {
                e.preventDefault();
                
                const data = {
                    job_role: document.getElementById('job_role').value,
                    interview_type: document.getElementById('interview_type').value,
                    domain: document.getElementById('domain').value
                };
                
                console.log('Sending data:', data);
                
                fetch('/test_configure', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                })
                .then(response => {
                    console.log('Response status:', response.status);
                    return response.json();
                })
                .then(data => {
                    console.log('Response data:', data);
                    document.getElementById('result').style.display = 'block';
                    document.getElementById('result-text').textContent = JSON.stringify(data, null, 2);
                })
                .catch(error => {
                    console.error('Error:', error);
                    document.getElementById('result').style.display = 'block';
                    document.getElementById('result-text').textContent = 'Error: ' + error.message;
                });
            });
        </script>
    </body>
    </html>
    '''

@app.route('/test_configure', methods=['POST'])
def test_configure():
    try:
        data = request.get_json()
        print(f"Received data: {data}")
        
        if not data:
            return jsonify({'status': 'error', 'message': 'No data received'}), 400
        
        # Simple response
        return jsonify({
            'status': 'success',
            'message': 'Test configuration successful',
            'received_data': data,
            'session_id': session.get('_id', 'no-session')
        })
        
    except Exception as e:
        print(f"Error in test_configure: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    print("Starting test server...")
    app.run(debug=True, port=5001)
