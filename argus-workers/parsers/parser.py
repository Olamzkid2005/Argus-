"""
Parser Layer - Converts CLI tool output to JSON

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 20.5, 21.1, 21.2
"""
import json
from typing import List, Dict, Optional
from abc import ABC, abstractmethod
import time
import os

from tracing import get_trace_id, StructuredLogger, ExecutionSpan


class ParserError(Exception):
    """Raised when parsing fails"""
    pass


class BaseParser(ABC):
    """Base class for tool output parsers"""
    
    @abstractmethod
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse tool output into structured findings
        
        Args:
            raw_output: Raw tool output string
            
        Returns:
            List of finding dictionaries
        """
        pass


class NucleiParser(BaseParser):
    """Parser for nuclei JSON output"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse nuclei JSON lines output
        
        Args:
            raw_output: Nuclei output (JSON lines format)
            
        Returns:
            List of findings
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            try:
                data = json.loads(line)
                
                # Extract finding information
                finding = {
                    "type": data.get("info", {}).get("name", "UNKNOWN"),
                    "severity": data.get("info", {}).get("severity", "INFO").upper(),
                    "endpoint": data.get("matched-at", ""),
                    "evidence": {
                        "template_id": data.get("template-id"),
                        "matcher_name": data.get("matcher-name"),
                        "extracted_results": data.get("extracted-results", []),
                        "curl_command": data.get("curl-command"),
                    },
                    "confidence": 0.8,  # Default confidence for nuclei
                    "tool": "nuclei",
                }
                
                findings.append(finding)
                
            except json.JSONDecodeError:
                # Skip lines that aren't valid JSON
                continue
            except Exception as e:
                # Log error but continue processing
                print(f"Error parsing nuclei line: {e}")
                continue
        
        return findings


class HttpxParser(BaseParser):
    """Parser for httpx output"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse httpx output
        
        Args:
            raw_output: Httpx output (URL list or JSON)
            
        Returns:
            List of findings (endpoints)
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            try:
                # Try parsing as JSON first
                data = json.loads(line)
                
                finding = {
                    "type": "HTTP_ENDPOINT",
                    "severity": "INFO",
                    "endpoint": data.get("url", ""),
                    "evidence": {
                        "status_code": data.get("status_code"),
                        "content_length": data.get("content_length"),
                        "content_type": data.get("content_type"),
                        "title": data.get("title"),
                    },
                    "confidence": 1.0,  # High confidence for discovered endpoints
                    "tool": "httpx",
                }
                
                findings.append(finding)
                
            except json.JSONDecodeError:
                # Not JSON, treat as plain URL
                if line.startswith("http://") or line.startswith("https://"):
                    finding = {
                        "type": "HTTP_ENDPOINT",
                        "severity": "INFO",
                        "endpoint": line.strip(),
                        "evidence": {},
                        "confidence": 1.0,
                        "tool": "httpx",
                    }
                    findings.append(finding)
        
        return findings


class SqlmapParser(BaseParser):
    """Parser for sqlmap output"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse sqlmap output
        
        Args:
            raw_output: Sqlmap output
            
        Returns:
            List of SQL injection findings
        """
        findings = []
        
        # Look for SQL injection indicators in output
        if "sqlmap identified the following injection point" in raw_output.lower():
            finding = {
                "type": "SQL_INJECTION",
                "severity": "CRITICAL",
                "endpoint": "",  # Will be filled by normalizer
                "evidence": {
                    "raw_output": raw_output[:1000],  # First 1000 chars
                },
                "confidence": 0.9,  # High confidence for sqlmap
                "tool": "sqlmap",
            }
            findings.append(finding)
        
        return findings


class FfufParser(BaseParser):
    """Parser for ffuf output"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse ffuf JSON output
        
        Args:
            raw_output: Ffuf output (JSON format)
            
        Returns:
            List of findings
        """
        findings = []
        
        try:
            data = json.loads(raw_output)
            
            for result in data.get("results", []):
                finding = {
                    "type": "DIRECTORY_FOUND",
                    "severity": "INFO",
                    "endpoint": result.get("url", ""),
                    "evidence": {
                        "status_code": result.get("status"),
                        "length": result.get("length"),
                        "words": result.get("words"),
                        "lines": result.get("lines"),
                    },
                    "confidence": 0.7,
                    "tool": "ffuf",
                }
                findings.append(finding)
                
        except json.JSONDecodeError:
            # Ffuf output not in JSON format
            pass
        
        return findings


class Parser:
    """
    Main parser class that routes to appropriate tool parser
    """
    
    def __init__(self, connection_string: str = None):
        """
        Initialize Parser with optional database connection for tracing.
        
        Args:
            connection_string: Database connection string
        """
        self.parsers = {
            "nuclei": NucleiParser(),
            "httpx": HttpxParser(),
            "sqlmap": SqlmapParser(),
            "ffuf": FfufParser(),
        }
        
        # Initialize tracing
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        self.logger = StructuredLogger(self.connection_string)
        self.span_recorder = ExecutionSpan(self.connection_string)
    
    def parse(self, tool_name: str, raw_output: str) -> List[Dict]:
        """
        Route to appropriate parser based on tool name
        
        Args:
            tool_name: Name of the tool
            raw_output: Raw tool output
            
        Returns:
            List of parsed findings
            
        Raises:
            ParserError: If no parser exists for tool
        """
        parser = self.parsers.get(tool_name.lower())
        
        if not parser:
            raise ParserError(f"No parser found for tool: {tool_name}")
        
        # Record start time
        start_time = time.time()
        
        # Execute with span tracing
        with self.span_recorder.span(ExecutionSpan.SPAN_PARSING, {"tool": tool_name}):
            try:
                findings = parser.parse(raw_output)
                
                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Log parser completion
                self.logger.log_parser_completed(
                    tool_name=tool_name,
                    findings_count=len(findings),
                    parse_time_ms=duration_ms
                )
                
                return findings
                
            except Exception as e:
                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Log parser failure
                self.logger.log(
                    "parser_failed",
                    f"Parser failed for {tool_name}: {str(e)}",
                    {
                        "tool_name": tool_name,
                        "error": str(e),
                        "parse_time_ms": duration_ms,
                    }
                )
                
                raise ParserError(f"Failed to parse {tool_name} output: {e}")
