#!/usr/bin/env python3
"""
Test script to verify the AI Interview Simulator functionality
"""

import os
import sys
import json
from unittest.mock import patch, MagicMock

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that all required modules can be imported"""
    try:
        from working_app import app, get_ai_response, _parse_json_like
        print("✓ All imports successful")
        return True
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False

def test_json_parsing():
    """Test the JSON parsing function"""
    try:
        from working_app import _parse_json_like
        
        # Test valid JSON
        result = _parse_json_like('{"test": "value"}')
        assert result == {"test": "value"}, "Valid JSON parsing failed"
        
        # Test malformed JSON with code blocks
        result = _parse_json_like('```json\n{"test": "value"}\n```')
        assert result == {"test": "value"}, "Code block JSON parsing failed"
        
        # Test question extraction
        result = _parse_json_like('1. What is your experience?\n2. How do you debug?\n3. Tell me about a project.', 'generate questions')
        assert isinstance(result, list), "Question extraction failed"
        
        print("✓ JSON parsing functions work correctly")
        return True
    except Exception as e:
        print(f"✗ JSON parsing test failed: {e}")
        return False

def test_ai_response_mock():
    """Test AI response function with mocked responses"""
    try:
        from working_app import get_ai_response
        
        # Test with FAKE_AI enabled
        with patch.dict(os.environ, {'FAKE_AI': 'true'}):
            # Test question generation
            result = get_ai_response("Generate 5 questions", expect_json=True)
            assert isinstance(result, list), "Question generation should return a list"
            assert len(result) >= 3, "Should return at least 3 questions"
            
            # Test feedback generation
            result = get_ai_response("Provide feedback", expect_json=True)
            assert isinstance(result, dict), "Feedback should return a dict"
            assert 'feedback' in result, "Feedback should contain 'feedback' key"
            
        print("✓ AI response function works with mock data")
        return True
    except Exception as e:
        print(f"✗ AI response test failed: {e}")
        return False

def test_flask_routes():
    """Test that Flask routes are properly configured"""
    try:
        from working_app import app
        
        # Get all routes
        routes = []
        for rule in app.url_map.iter_rules():
            routes.append(rule.rule)
        
        expected_routes = ['/', '/interview', '/summary', '/configure', '/submit_answer', '/current_question']
        
        for route in expected_routes:
            assert route in routes, f"Missing route: {route}"
        
        print("✓ All required Flask routes are configured")
        return True
    except Exception as e:
        print(f"✗ Flask routes test failed: {e}")
        return False

def test_template_files():
    """Test that all template files exist and are readable"""
    try:
        template_files = ['base.html', 'index.html', 'interview.html', 'summary.html']
        
        for template in template_files:
            template_path = os.path.join('templates', template)
            assert os.path.exists(template_path), f"Template file missing: {template}"
            
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
                assert len(content) > 0, f"Template file is empty: {template}"
        
        print("✓ All template files exist and are readable")
        return True
    except Exception as e:
        print(f"✗ Template files test failed: {e}")
        return False

def test_static_files():
    """Test that static files exist"""
    try:
        static_files = ['css/style.css', 'favico.ico']
        
        for static_file in static_files:
            static_path = os.path.join('static', static_file)
            assert os.path.exists(static_path), f"Static file missing: {static_file}"
        
        print("✓ All static files exist")
        return True
    except Exception as e:
        print(f"✗ Static files test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("Testing AI Interview Simulator...")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_json_parsing,
        test_ai_response_mock,
        test_flask_routes,
        test_template_files,
        test_static_files
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"✗ Test {test.__name__} failed with exception: {e}")
    
    print("=" * 50)
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed! The AI Interview Simulator is ready to use.")
        return True
    else:
        print("❌ Some tests failed. Please check the errors above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
