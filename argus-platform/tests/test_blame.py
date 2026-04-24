"""
Tests for git blame functionality
"""

import subprocess
from unittest.mock import patch, MagicMock
import pytest


def get_blame_for_finding(repo_path, finding):
    """
    Run git blame on the file/line associated with a finding.
    Returns blame info: author, commit, date, etc.
    """
    if 'file_path' not in finding or 'line_number' not in finding:
        return None
    
    file_path = finding['file_path']
    line_number = finding.get('line_number', 1)
    
    try:
        result = subprocess.run(
            ['git', 'blame', '-L', f'{line_number},{line_number}',
             '--porcelain', file_path],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            blame_info = {}
            for line in result.stdout.split('\n'):
                if line.startswith('author '):
                    blame_info['author'] = line.split(' ', 1)[1]
                elif line.startswith('author-time '):
                    blame_info['author_time'] = line.split(' ')[1]
                elif line.startswith('committer-time '):
                    blame_info['committer_time'] = line.split(' ')[1]
                elif line.startswith('commit '):
                    blame_info['commit_hash'] = line.split(' ')[1]
                elif line.startswith('summary '):
                    blame_info['summary'] = line.split(' ', 1)[1]
            
            return blame_info
    
    except Exception as e:
        pass
    
    return None


def enrich_findings_with_blame(repo_path, findings):
    """
    Add blame information to all findings that have file/line info.
    """
    for finding in findings:
        if finding.get('type') in ['COMMITTED_SECRET', 'STATIC_ANALYSIS_FINDING']:
            blame = get_blame_for_finding(repo_path, finding)
            if blame:
                finding['blame'] = blame
                finding['introduced_by'] = blame.get('author', 'unknown')
                finding['introduced_at'] = blame.get('author_time', '')
                finding['introduced_in_commit'] = blame.get('commit_hash', '')
    
    return findings


class TestGetBlameForFinding:
    """Tests for get_blame_for_finding function"""
    
    def test_successful_blame(self):
        """Test successful git blame parsing"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """author John Doe
author-mail <john@example.com>
author-time 1234567890
committer John Doe
committer-mail <john@example.com>
committer-time 1234567890
commit abc123def456
summary Fix vulnerability

"""
        
        with patch('subprocess.run', return_value=mock_result):
            finding = {'file_path': 'test.py', 'line_number': 10}
            result = get_blame_for_finding('/fake/repo', finding)
            
            assert result is not None
            assert result['author'] == 'John Doe'
            assert result['author_time'] == '1234567890'
            assert result['commit_hash'] == 'abc123def456'
            assert result['summary'] == 'Fix vulnerability'
    
    def test_no_file_path(self):
        """Test finding without file_path returns None"""
        finding = {'line_number': 10}
        result = get_blame_for_finding('/fake/repo', finding)
        assert result is None
    
    def test_no_line_number(self):
        """Test finding without line_number returns None"""
        finding = {'file_path': 'test.py'}
        result = get_blame_for_finding('/fake/repo', finding)
        assert result is None
    
    def test_empty_finding(self):
        """Test empty finding returns None"""
        finding = {}
        result = get_blame_for_finding('/fake/repo', finding)
        assert result is None
    
    def test_git_blame_command(self):
        """Test that git blame is called with correct arguments"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        
        with patch('subprocess.run', return_value=mock_result) as mock_run:
            finding = {'file_path': 'src/main.py', 'line_number': 42}
            get_blame_for_finding('/fake/repo', finding)
            
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args == ['git', 'blame', '-L', '42,42', '--porcelain', 'src/main.py']
    
    def test_git_blame_timeout(self):
        """Test handling of git blame timeout"""
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('git', 30)):
            finding = {'file_path': 'test.py', 'line_number': 10}
            result = get_blame_for_finding('/fake/repo', finding)
            assert result is None


class TestEnrichFindingsWithBlame:
    """Tests for enrich_findings_with_blame function"""
    
    def test_enrich_committed_secret(self):
        """Test enrichment of COMMITTED_SECRET finding"""
        # Mock subprocess.run to return blame info
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """author Jane Doe
author-time 1234567890
commit abc123
summary Add secret

"""
        
        with patch('subprocess.run', return_value=mock_result):
            findings = [
                {'type': 'COMMITTED_SECRET', 'file_path': 'test.py', 'line_number': 10}
            ]
            result = enrich_findings_with_blame('/fake/repo', findings)
            
            assert 'blame' in result[0]
            assert result[0]['introduced_by'] == 'Jane Doe'
            assert result[0]['introduced_at'] == '1234567890'
            assert result[0]['introduced_in_commit'] == 'abc123'
    
    def test_enrich_static_analysis_finding(self):
        """Test enrichment of STATIC_ANALYSIS_FINDING"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """author Bob Smith
author-time 9876543210
commit def456

"""
        
        with patch('subprocess.run', return_value=mock_result):
            findings = [
                {'type': 'STATIC_ANALYSIS_FINDING', 'file_path': 'app.py', 'line_number': 5}
            ]
            result = enrich_findings_with_blame('/fake/repo', findings)
            
            assert result[0]['introduced_by'] == 'Bob Smith'
            assert result[0]['introduced_at'] == '9876543210'
    
    def test_no_enrichment_for_other_types(self):
        """Test that non-matching finding types are not enriched"""
        findings = [
            {'type': 'OTHER_TYPE', 'file_path': 'test.py', 'line_number': 10}
        ]
        result = enrich_findings_with_blame('/fake/repo', findings)
        
        assert 'blame' not in result[0]
        assert 'introduced_by' not in result[0]
    
    def test_enrichment_without_blame(self):
        """Test enrichment when blame returns None"""
        mock_result = MagicMock()
        mock_result.returncode = 1  # Git blame fails
        
        with patch('subprocess.run', return_value=mock_result):
            findings = [
                {'type': 'COMMITTED_SECRET', 'file_path': 'test.py', 'line_number': 10}
            ]
            result = enrich_findings_with_blame('/fake/repo', findings)
            
            assert 'blame' not in result[0]
            assert 'introduced_by' not in result[0]
    
    def test_multiple_findings(self):
        """Test enrichment of multiple findings"""
        call_count = 0
        def mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            mock_result.returncode = 0
            if call_count == 1:
                mock_result.stdout = """author Author1
author-time 111
commit aaa

"""
            else:
                mock_result.stdout = """author Author2
author-time 222
commit bbb

"""
            return mock_result
        
        with patch('subprocess.run', side_effect=mock_run):
            findings = [
                {'type': 'COMMITTED_SECRET', 'file_path': 'a.py', 'line_number': 10},
                {'type': 'STATIC_ANALYSIS_FINDING', 'file_path': 'b.py', 'line_number': 20},
                {'type': 'OTHER', 'file_path': 'c.py', 'line_number': 30}
            ]
            result = enrich_findings_with_blame('/fake/repo', findings)
            
            assert result[0]['introduced_by'] == 'Author1'
            assert result[1]['introduced_by'] == 'Author2'
            assert 'introduced_by' not in result[2]
