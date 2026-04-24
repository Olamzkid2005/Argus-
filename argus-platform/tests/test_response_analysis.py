import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from web_scanner import analyze_status_code, analyze_content_type, analyze_response_size, fingerprint_technology


class MockResponse:
    def __init__(self, content):
        self.content = content


def test_analyze_status_code():
    # Test 200
    result = analyze_status_code(200, '')
    assert result['status'] == 200
    assert result['category'] == 'success'
    assert not result['anomaly']

    # Test 401
    result = analyze_status_code(401, '')
    assert result['category'] == 'unauthorized'
    assert result['anomaly']

    # Test 403
    result = analyze_status_code(403, '')
    assert result['category'] == 'forbidden'

    # Test 404
    result = analyze_status_code(404, '')
    assert result['category'] == 'not_found'

    # Test 500
    result = analyze_status_code(500, '')
    assert result['category'] == 'server_error'
    assert result['anomaly']
    assert 'Server error detected' in result['details']


def test_analyze_content_type():
    # JSON
    headers = {'content-type': 'application/json; charset=utf-8'}
    result = analyze_content_type(headers)
    assert result['type'] == 'json'
    assert result['charset'] == 'utf-8'

    # HTML
    headers = {'content-type': 'text/html'}
    result = analyze_content_type(headers)
    assert result['type'] == 'html'

    # XML
    headers = {'content-type': 'application/xml'}
    result = analyze_content_type(headers)
    assert result['type'] == 'xml'

    # No content-type
    headers = {}
    result = analyze_content_type(headers)
    assert result['content_type'] == ''
    assert result['type'] is None


def test_analyze_response_size():
    # Empty response
    resp = MockResponse(b'')
    result = analyze_response_size(resp)
    assert result['size'] == 0
    assert result['size_category'] == 'empty'
    assert result['anomaly']

    # Very small
    resp = MockResponse(b'a' * 50)
    result = analyze_response_size(resp)
    assert result['size_category'] == 'very_small'

    # Normal
    resp = MockResponse(b'a' * 200)
    result = analyze_response_size(resp)
    assert result['size_category'] == 'normal'

    # Very large (>1MB)
    resp = MockResponse(b'a' * 2000000)
    result = analyze_response_size(resp)
    assert result['size_category'] == 'very_large'


def test_fingerprint_technology():
    # Server header
    headers = {'server': 'nginx'}
    result = fingerprint_technology(headers, '')
    assert result['server'] == 'nginx'

    # X-Powered-By
    headers = {'x-powered-by': 'Express'}
    result = fingerprint_technology(headers, '')
    assert result['x-powered-by'] == 'Express'

    # CDN detection (cf-ray)
    headers = {'cf-ray': '12345'}
    result = fingerprint_technology(headers, '')
    assert result['cdn'] == 'Cf Ray'

    # Framework detection
    result = fingerprint_technology({}, 'This page uses Laravel')
    assert 'Laravel' in result['frameworks']

    result = fingerprint_technology({}, 'Built with Django')
    assert 'Django' in result['frameworks']

    result = fingerprint_technology({'x-powered-by': 'Node.js'}, 'Express framework')
    assert 'Express/Node.js' in result['frameworks']
