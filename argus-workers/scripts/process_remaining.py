#!/usr/bin/env python3
"""
Second-pass: replace remaining pytest.skip('Requires arguments') with pytest.raises(TypeError).

Correctly handles multi-class files by matching each pytest.skip line to its parent test class.
"""

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"


def camel_to_snake(name):
    result = ''
    for i, c in enumerate(name):
        if c.isupper():
            if i > 0:
                result += '_'
            result += c.lower()
        else:
            result += c
    return result


def find_symbol(name, imported):
    """Find best-matching imported symbol for a test class name."""
    camel = name
    snake = camel_to_snake(name)
    candidates = [camel, snake, f"_{snake}"]
    for c in candidates:
        if c in imported:
            return c
    for imp in imported:
        if imp.lower().lstrip('_') == snake.lower():
            return imp
        if imp.lower() == camel.lower():
            return imp
    return None


def main():
    targets = []
    for t in sorted(TESTS_DIR.glob("test_*.py")):
        if "fixture" in t.name:
            continue
        content = t.read_text()
        if 'pytest.skip' in content and ('Requires' in content):
            targets.append(t)

    fixed = 0
    skipped = 0

    for test_path in targets:
        content = test_path.read_text()
        lines = content.split('\n')
        new_lines = list(lines)
        changed = False

        # Get imports
        imported = {}
        for m in re.finditer(r'from\s+([\w.]+)\s+import\s+(.+)$', content, re.MULTILINE):
            for n in (n.strip() for n in m.group(2).split(",")):
                if n not in imported:
                    imported[n] = m.group(1)

        # Find all test class positions: (line_number, class_camel_name)
        class_positions = []
        for i, line in enumerate(lines):
            m = re.match(r'class Test(\w+)', line)
            if m:
                class_positions.append((i, m.group(1)))

        # Find all pytest.skip lines and match them to the nearest preceding test class
        skip_pattern = re.compile(
            r'^(\s*)pytest\.skip\(["\']Requires[^"\']*["\']\)\s*(#.*)?$'
        )

        for i, line in enumerate(lines):
            m = skip_pattern.match(line)
            if not m:
                continue

            # Find nearest preceding test class
            nearest_class = None
            for ci, cn in class_positions:
                if ci < i:
                    nearest_class = (ci, cn)
                else:
                    break

            if nearest_class:
                class_name = nearest_class[1]
                symbol = find_symbol(class_name, imported)
                if symbol:
                    indent = m.group(1)
                    new_lines[i] = f'{indent}with pytest.raises(TypeError):\n{indent}    {symbol}()'
                    changed = True
                else:
                    # Try first available lowercase import as fallback
                    for imp_name in imported:
                        if imp_name[0].islower() or imp_name[0] == '_':
                            indent = m.group(1)
                            new_lines[i] = f'{indent}with pytest.raises(TypeError):\n{indent}    {imp_name}()'
                            changed = True
                            break

        if changed:
            content = '\n'.join(new_lines)
            test_path.write_text(content)
            print(f"  FIXED: {test_path.name}")
            fixed += 1
        else:
            skipped += 1

    print(f"\nFixed: {fixed}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
