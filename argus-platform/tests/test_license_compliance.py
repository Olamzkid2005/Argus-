import os
import json
import tempfile
import shutil
import pytest
from tasks.repo_scan import (
    detect_license,
    _match_license,
    check_license_compliance,
    LICENSE_PATTERNS,
    LICENSE_POLICY
)

class TestLicensePatternMatching:
    def test_match_mit_license(self):
        content = "MIT License\n\nPermission is hereby granted..."
        assert _match_license(content) == 'MIT'
    
    def test_match_apache2_license(self):
        content = "Apache License\nVersion 2.0\n\nCopyright..."
        assert _match_license(content) == 'Apache-2.0'
    
    def test_match_gpl2_license(self):
        content = "GNU General Public License version 2\n..."
        assert _match_license(content) == 'GPL-2.0'
    
    def test_match_gpl3_license(self):
        content = "GPLv3\n\nThis program is free software..."
        assert _match_license(content) == 'GPL-3.0'
    
    def test_match_unknown_license(self):
        content = "Proprietary License\nAll rights reserved."
        assert _match_license(content) == 'UNKNOWN'

class TestDetectLicense:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        shutil.rmtree(self.temp_dir)
    
    def test_detect_from_license_file(self):
        license_path = os.path.join(self.temp_dir, 'LICENSE')
        with open(license_path, 'w') as f:
            f.write("MIT License\n\nPermission is hereby granted...")
        assert detect_license(self.temp_dir) == 'MIT'
    
    def test_detect_from_license_txt_file(self):
        license_path = os.path.join(self.temp_dir, 'LICENSE.txt')
        with open(license_path, 'w') as f:
            f.write("Apache License\nVersion 2.0\n\nCopyright...")
        assert detect_license(self.temp_dir) == 'Apache-2.0'
    
    def test_detect_from_package_json(self):
        package_path = os.path.join(self.temp_dir, 'package.json')
        with open(package_path, 'w') as f:
            json.dump({'license': 'ISC'}, f)
        assert detect_license(self.temp_dir) == 'ISC'
    
    def test_detect_unknown_license(self):
        assert detect_license(self.temp_dir) == 'UNKNOWN'

class TestLicenseComplianceChecking:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        shutil.rmtree(self.temp_dir)
    
    def test_blocked_license(self):
        license_path = os.path.join(self.temp_dir, 'LICENSE')
        with open(license_path, 'w') as f:
            f.write("GNU General Public License version 2")
        
        findings = check_license_compliance(self.temp_dir)
        assert len(findings) == 1
        assert findings[0]['license'] == 'GPL-2.0'
        assert findings[0]['severity'] == 'HIGH'
        assert findings[0]['compliance_status'] == 'blocked'
    
    def test_warn_license(self):
        license_path = os.path.join(self.temp_dir, 'LICENSE')
        with open(license_path, 'w') as f:
            f.write("GNU Lesser General Public License")
        
        findings = check_license_compliance(self.temp_dir)
        assert len(findings) == 1
        assert findings[0]['license'] == 'LGPL'
        assert findings[0]['severity'] == 'MEDIUM'
        assert findings[0]['compliance_status'] == 'warn'
    
    def test_allowed_license(self):
        license_path = os.path.join(self.temp_dir, 'LICENSE')
        with open(license_path, 'w') as f:
            f.write("MIT License")
        
        findings = check_license_compliance(self.temp_dir)
        assert len(findings) == 1
        assert findings[0]['license'] == 'MIT'
        assert findings[0]['severity'] == 'LOW'
        assert findings[0]['compliance_status'] == 'allowed'
    
    def test_unknown_license_no_findings(self):
        findings = check_license_compliance(self.temp_dir)
        assert len(findings) == 0

class TestLicensePolicyEnvVars:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_env = {}
    
    def teardown_method(self):
        shutil.rmtree(self.temp_dir)
        # Restore original env vars
        for key, val in self.original_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
    
    def _set_env(self, key, value):
        self.original_env[key] = os.environ.get(key)
        os.environ[key] = value
    
    def test_custom_blocked_policy(self):
        self._set_env('ARGUS_LICENSE_POLICY_BLOCKED', 'MIT')
        self._set_env('ARGUS_LICENSE_POLICY_ALLOWED', '')
        self._set_env('ARGUS_LICENSE_POLICY_WARN', '')
        
        license_path = os.path.join(self.temp_dir, 'LICENSE')
        with open(license_path, 'w') as f:
            f.write("MIT License")
        
        from tasks.repo_scan import _load_license_policy
        custom_policy = _load_license_policy()
        findings = check_license_compliance(self.temp_dir, custom_policy)
        
        assert len(findings) == 1
        assert findings[0]['compliance_status'] == 'blocked'
