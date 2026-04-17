# Argus Workers Test Suite

Comprehensive test suite for the Argus Pentest Platform Python workers.

## Test Coverage

### Core Components
- **Tool Runner** (`test_tool_runner.py`) - Safety validation, subprocess execution, timeout handling
- **Parser Layer** (`test_parser.py`) - Tool output parsing for nuclei, httpx, sqlmap, ffuf
- **Normalizer** (`test_normalizer.py`) - Schema validation, type/severity normalization, confidence scoring
- **Scope Validator** (`test_scope_validator.py`) - Domain matching, wildcard support, IP range validation

### Intelligence & Decision Making
- **Intelligence Engine** (`test_intelligence_engine.py`) - Confidence scoring, action generation, pattern detection
- **Loop Budget Manager** (`test_loop_budget_manager.py`) - Budget enforcement, cycle/depth/cost tracking
- **State Machine** (`test_state_machine.py`) - State transition validation, loop-back handling

### Risk Analysis
- **Attack Graph** (`test_attack_graph.py`) - Risk scoring, confidence decay, exposure weighting

## Running Tests

### Prerequisites

Install test dependencies:
```bash
cd argus-workers
pip install pytest pytest-cov pytest-mock
```

### Run All Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_tool_runner.py

# Run specific test class
pytest tests/test_tool_runner.py::TestToolRunner

# Run specific test method
pytest tests/test_tool_runner.py::TestToolRunner::test_is_dangerous_detects_rm_rf
```

### Run Tests by Category

```bash
# Core pipeline tests
pytest tests/test_tool_runner.py tests/test_parser.py tests/test_normalizer.py

# Intelligence tests
pytest tests/test_intelligence_engine.py tests/test_loop_budget_manager.py

# Security tests
pytest tests/test_scope_validator.py tests/test_tool_runner.py
```

### Test Output Options

```bash
# Show print statements
pytest -s

# Stop on first failure
pytest -x

# Run last failed tests
pytest --lf

# Run tests in parallel (requires pytest-xdist)
pytest -n auto
```

## Test Structure

Each test file follows this structure:

```python
class TestComponentName:
    """Test suite for ComponentName"""
    
    def setup_method(self):
        """Setup test fixtures before each test"""
        pass
    
    def teardown_method(self):
        """Cleanup after each test"""
        pass
    
    def test_specific_behavior(self):
        """Test description"""
        # Arrange
        # Act
        # Assert
        pass
```

## Writing New Tests

### Test Naming Convention
- Test files: `test_<component_name>.py`
- Test classes: `Test<ComponentName>`
- Test methods: `test_<behavior_description>`

### Example Test

```python
def test_normalize_type_standardizes_sqli(self):
    """Test that SQL injection variants are standardized"""
    normalizer = FindingNormalizer()
    
    result = normalizer._normalize_type("sqli", "nuclei")
    
    assert result == "SQL_INJECTION"
```

### Using Fixtures

```python
def test_with_fixture(self, sample_finding):
    """Test using a fixture"""
    assert sample_finding["type"] == "SQL_INJECTION"
```

### Mocking Database Connections

```python
from unittest.mock import Mock, patch

def test_with_mock_db(self):
    """Test with mocked database"""
    with patch('module.psycopg2.connect') as mock_connect:
        mock_conn = Mock()
        mock_connect.return_value = mock_conn
        
        # Your test code here
```

## Coverage Goals

- **Overall Coverage:** > 80%
- **Critical Components:** > 90%
  - Tool Runner
  - Scope Validator
  - Normalizer
  - Intelligence Engine

## Continuous Integration

Tests are automatically run on:
- Every commit to main branch
- Every pull request
- Nightly builds

## Troubleshooting

### Import Errors
If you get import errors, ensure the parent directory is in your Python path:
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Database Connection Errors
Tests use mocked database connections. If you see connection errors, check that mocks are properly configured.

### Missing Dependencies
Install all test dependencies:
```bash
pip install -r requirements.txt
pip install pytest pytest-cov pytest-mock
```

## Test Maintenance

- Update tests when modifying component behavior
- Add tests for new features before implementation (TDD)
- Keep test data realistic but minimal
- Use fixtures for common test data
- Mock external dependencies (database, Redis, file system)

## Performance Testing

For performance-critical components, use pytest-benchmark:
```bash
pip install pytest-benchmark

# Run benchmark tests
pytest tests/test_performance.py --benchmark-only
```

## Security Testing

Security-focused tests are marked with `@pytest.mark.security`:
```bash
# Run only security tests
pytest -m security
```
