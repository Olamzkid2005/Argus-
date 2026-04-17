"""
Tests for Parser Layer
"""
import pytest
import json
from parsers.parser import Parser, ParserError, NucleiParser, HttpxParser


class TestNucleiParser:
    """Test suite for Nuclei parser"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.parser = NucleiParser()
    
    def test_parse_valid_json_line(self):
        """Test parsing valid nuclei JSON output"""
        output = json.dumps({
            "info": {
                "name": "SQL Injection",
                "severity": "high"
            },
            "matched-at": "https://example.com/api",
            "template-id": "sqli-test",
            "matcher-name": "sql-error"
        })
        
        findings = self.parser.parse(output)
        
        assert len(findings) == 1
        assert findings[0]["type"] == "SQL Injection"
        assert findings[0]["severity"] == "HIGH"
        assert findings[0]["endpoint"] == "https://example.com/api"
        assert findings[0]["tool"] == "nuclei"
    
    def test_parse_multiple_json_lines(self):
        """Test parsing multiple JSON lines"""
        line1 = json.dumps({"info": {"name": "XSS", "severity": "medium"}, "matched-at": "https://example.com/1"})
        line2 = json.dumps({"info": {"name": "IDOR", "severity": "high"}, "matched-at": "https://example.com/2"})
        output = f"{line1}\n{line2}"
        
        findings = self.parser.parse(output)
        
        assert len(findings) == 2
        assert findings[0]["type"] == "XSS"
        assert findings[1]["type"] == "IDOR"
    
    def test_parse_skips_empty_lines(self):
        """Test that empty lines are skipped"""
        output = "\n\n" + json.dumps({"info": {"name": "Test", "severity": "low"}, "matched-at": "https://example.com"}) + "\n\n"
        
        findings = self.parser.parse(output)
        
        assert len(findings) == 1
    
    def test_parse_handles_invalid_json(self):
        """Test that invalid JSON lines are skipped"""
        output = "invalid json\n" + json.dumps({"info": {"name": "Test", "severity": "low"}, "matched-at": "https://example.com"})
        
        findings = self.parser.parse(output)
        
        assert len(findings) == 1


class TestHttpxParser:
    """Test suite for Httpx parser"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.parser = HttpxParser()
    
    def test_parse_json_output(self):
        """Test parsing httpx JSON output"""
        output = json.dumps({
            "url": "https://example.com",
            "status_code": 200,
            "content_length": 1234,
            "content_type": "text/html",
            "title": "Example Domain"
        })
        
        findings = self.parser.parse(output)
        
        assert len(findings) == 1
        assert findings[0]["type"] == "HTTP_ENDPOINT"
        assert findings[0]["endpoint"] == "https://example.com"
        assert findings[0]["evidence"]["status_code"] == 200
    
    def test_parse_plain_url_list(self):
        """Test parsing plain URL list"""
        output = "https://example.com/page1\nhttps://example.com/page2"
        
        findings = self.parser.parse(output)
        
        assert len(findings) == 2
        assert findings[0]["endpoint"] == "https://example.com/page1"
        assert findings[1]["endpoint"] == "https://example.com/page2"
    
    def test_parse_ignores_non_http_lines(self):
        """Test that non-HTTP lines are ignored"""
        output = "not a url\nhttps://example.com\nsome text"
        
        findings = self.parser.parse(output)
        
        assert len(findings) == 1
        assert findings[0]["endpoint"] == "https://example.com"


class TestParser:
    """Test suite for main Parser class"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.parser = Parser()
    
    def test_parse_routes_to_nuclei_parser(self):
        """Test that nuclei output is routed correctly"""
        output = json.dumps({"info": {"name": "Test", "severity": "low"}, "matched-at": "https://example.com"})
        
        findings = self.parser.parse("nuclei", output)
        
        assert len(findings) == 1
        assert findings[0]["tool"] == "nuclei"
    
    def test_parse_routes_to_httpx_parser(self):
        """Test that httpx output is routed correctly"""
        output = "https://example.com"
        
        findings = self.parser.parse("httpx", output)
        
        assert len(findings) == 1
        assert findings[0]["tool"] == "httpx"
    
    def test_parse_raises_error_for_unknown_tool(self):
        """Test that unknown tool raises ParserError"""
        with pytest.raises(ParserError):
            self.parser.parse("unknown_tool", "output")
    
    def test_parse_case_insensitive(self):
        """Test that tool name is case insensitive"""
        output = "https://example.com"
        
        findings = self.parser.parse("HTTPX", output)
        
        assert len(findings) == 1
