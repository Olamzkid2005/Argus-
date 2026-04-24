import sys
import os
import json
import tempfile
import importlib.util
from unittest.mock import MagicMock, patch

def load_sbom_functions():
    """Load SBOM functions directly from repo_scan.py without external dependencies"""
    file_path = '/Users/mac/Documents/Argus-/argus-workers/tasks/repo_scan.py'
    
    # Create mocked modules for all external dependencies
    mock_celery = MagicMock()
    mock_celery_app = MagicMock()
    mock_psycopg2 = MagicMock()
    mock_subprocess = MagicMock()
    mock_logging = MagicMock()
    mock_importlib = MagicMock()
    
    # Mock the loader module
    mock_loader = MagicMock()
    mock_orchestrator = MagicMock()
    mock_tracing = MagicMock()
    
    # Set up the mock load_module to return mock modules
    def mock_load_module(name):
        if name == "orchestrator":
            return mock_orchestrator
        if name == "tracing":
            return mock_tracing
        return MagicMock()
    
    mock_loader.load_module = mock_load_module
    
    # Create a namespace with all required imports mocked
    namespace = {
        'os': os,
        'sys': sys,
        'importlib': __import__('importlib'),
        'importlib.util': __import__('importlib.util'),
        'json': json,
        'datetime': __import__('datetime').datetime,
        'uuid': __import__('uuid'),
        'logging': __import__('logging'),
        'psycopg2': mock_psycopg2,
        'subprocess': mock_subprocess,
        'celery_app': MagicMock(),
        'celery': mock_celery,
        '__name__': '__main__',
        # Add the mock loader
        'loader': mock_loader,
        'load_module': mock_load_module,
    }
    
    # Execute the code in the mocked namespace - use 'exec' with separate globals
    with open(file_path) as f:
        code = f.read()
    
    # Replace the problematic _load_module call before execution
    code = code.replace('_load_module', 'load_module')
    
    # Execute the code in the mocked namespace
    exec(code, namespace)
    
    return (
        namespace.get('generate_cyclonedx_sbom'),
        namespace.get('generate_spdx_sbom'),
        namespace.get('save_sbom')
    )

generate_cyclonedx_sbom, generate_spdx_sbom, save_sbom = load_sbom_functions()


class TestCycloneDXSBOM:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.dependencies = [
            {
                'name': 'requests',
                'version': '2.28.0',
                'ecosystem': 'pip',
                'cve': 'CVE-2023-12345'
            },
            {
                'name': 'flask',
                'version': '2.0.0',
                'ecosystem': 'pip'
            }
        ]
    
    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_generates_valid_cyclonedx(self):
        sbom = generate_cyclonedx_sbom(self.temp_dir, self.dependencies)
        assert sbom['bomFormat'] == 'CycloneDX'
        assert sbom['specVersion'] == '1.4'
        assert len(sbom['components']) == 2
        assert sbom['components'][0]['name'] == 'requests'
        assert len(sbom['components'][0]['externalReferences']) == 1
    
    def test_cyclonedx_serial_number_valid(self):
        sbom = generate_cyclonedx_sbom(self.temp_dir, self.dependencies)
        assert sbom['serialNumber'].startswith('urn:uuid:')
    
    def test_save_cyclonedx(self):
        sbom = generate_cyclonedx_sbom(self.temp_dir, self.dependencies)
        path = save_sbom(sbom, self.temp_dir, format='cyclonedx')
        assert os.path.exists(path)
        with open(path) as f:
            loaded = json.load(f)
        assert loaded['bomFormat'] == 'CycloneDX'
        os.remove(path)


class TestSPDXSBOM:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.dependencies = [
            {
                'name': 'requests',
                'version': '2.28.0',
                'ecosystem': 'pip',
                'cve': 'CVE-2023-12345'
            }
        ]
    
    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_generates_valid_spdx(self):
        sbom = generate_spdx_sbom(self.temp_dir, self.dependencies)
        assert sbom['spdxVersion'] == 'SPDX-2.3'
        assert sbom['name'] == f'SBOM-{os.path.basename(self.temp_dir)}'
        assert len(sbom['packages']) == 1
        assert sbom['packages'][0]['name'] == 'requests'
    
    def test_save_spdx(self):
        sbom = generate_spdx_sbom(self.temp_dir, self.dependencies)
        path = save_sbom(sbom, self.temp_dir, format='spdx')
        assert os.path.exists(path)
        with open(path) as f:
            loaded = json.load(f)
        assert loaded['spdxVersion'] == 'SPDX-2.3'
        os.remove(path)


class TestSaveSBOM:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.dependencies = [{'name': 'test', 'version': '1.0', 'ecosystem': 'generic'}]
    
    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_invalid_format_raises_error(self):
        sbom = generate_cyclonedx_sbom(self.temp_dir, self.dependencies)
        try:
            save_sbom(sbom, self.temp_dir, format='invalid')
        except ValueError as e:
            assert 'Unsupported SBOM format' in str(e)
        else:
            assert False, "Expected ValueError"
