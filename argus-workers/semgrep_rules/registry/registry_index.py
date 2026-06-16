import os

_rules_dir = os.path.dirname(os.path.abspath(__file__))

REGISTRY_MAP = {
    # PHP
    "p/php": [
        os.path.join(_rules_dir, "php-ssl.yaml"),
        os.path.join(_rules_dir, "php-xss.yaml"),
        os.path.join(_rules_dir, "php-sqli.yaml"),
        os.path.join(_rules_dir, "php-csrf.yaml"),
        os.path.join(_rules_dir, "php-xxe.yaml"),
        os.path.join(_rules_dir, "php-rce.yaml"),
        os.path.join(_rules_dir, "php-session.yaml"),
        os.path.join(_rules_dir, "php-security.yaml"),
    ],
    # JavaScript
    "p/javascript": [
        os.path.join(_rules_dir, "javascript-security.yaml"),
    ],
    # Secrets (always included)
    "p/secrets": [
        os.path.join(_rules_dir, "secrets.yaml"),
    ],
}

def resolve(config_name):
    """Resolve a config name like 'p/php' to a list of local file paths."""
    resolved = REGISTRY_MAP.get(config_name, [])
    if not resolved:
        # Not a registry config, return as-is (could be a file path)
        return [config_name] if os.path.isfile(config_name) or os.path.isdir(config_name) else []
    return [f for f in resolved if os.path.isfile(f)]
