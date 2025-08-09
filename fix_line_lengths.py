#!/usr/bin/env python3
"""Fix line length issues in Python files."""

import re
import sys
from pathlib import Path


def split_long_string(line: str, max_length: int = 120) -> list[str]:
    """Split a long string literal or f-string across multiple lines."""
    if len(line) <= max_length:
        return [line]
    
    # Find the indentation
    indent_match = re.match(r'^(\s*)', line)
    indent = indent_match.group(1) if indent_match else ''
    
    # Check if it's a logging statement
    if 'logger.' in line or 'logging.' in line:
        # Handle f-strings in logging
        if 'f"' in line or "f'" in line:
            # Find the f-string boundaries
            string_match = re.search(r'(f["\'])(.*?)(["\'])', line)
            if string_match:
                prefix = line[:string_match.start()]
                quote = string_match.group(1)
                content = string_match.group(2)
                suffix = line[string_match.end():]
                
                # Split at logical points (| or space near middle)
                split_points = []
                for match in re.finditer(r' \| | - | ', content):
                    pos = match.start()
                    if 40 < pos < len(content) - 40:
                        split_points.append(pos)
                
                if split_points:
                    split_at = split_points[len(split_points)//2]
                    part1 = content[:split_at]
                    part2 = content[split_at:]
                    
                    return [
                        f'{prefix}{quote}{part1}" ',
                        f'{indent}{quote}{part2}{quote[-1]}{suffix}'
                    ]
    
    # Check if it's a long comment
    if line.strip().startswith('#'):
        # Split comment at word boundaries
        stripped = line.strip()
        if len(stripped) > max_length:
            words = stripped.split()
            lines = []
            current = words[0]  # Start with '#'
            
            for word in words[1:]:
                if len(current + ' ' + word) <= max_length:
                    current += ' ' + word
                else:
                    lines.append(indent + current)
                    current = '#' + (' ' * (len(words[0]) - 1)) + word
            
            if current:
                lines.append(indent + current)
            return lines
    
    # Check if it's a function call with many parameters
    if '(' in line and ')' in line:
        # Find commas outside of strings
        in_string = False
        quote_char = None
        commas = []
        
        for i, char in enumerate(line):
            if char in ('"', "'") and (i == 0 or line[i-1] != '\\'):
                if not in_string:
                    in_string = True
                    quote_char = char
                elif char == quote_char:
                    in_string = False
                    quote_char = None
            elif char == ',' and not in_string:
                commas.append(i)
        
        # Split at a comma near the middle
        if commas:
            for comma_pos in commas:
                if comma_pos > 60:
                    return [
                        line[:comma_pos + 1],
                        indent + '    ' + line[comma_pos + 1:].lstrip()
                    ]
    
    return [line]


def fix_file(file_path: Path) -> int:
    """Fix line length issues in a Python file."""
    with open(file_path, 'r') as f:
        lines = f.readlines()
    
    new_lines = []
    changes = 0
    
    for line in lines:
        if len(line.rstrip()) > 120:
            split = split_long_string(line.rstrip())
            if len(split) > 1:
                new_lines.extend([l + '\n' for l in split])
                changes += 1
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    
    if changes > 0:
        with open(file_path, 'w') as f:
            f.writelines(new_lines)
    
    return changes


def main():
    if len(sys.argv) < 2:
        print("Usage: python fix_line_lengths.py <file_path> [file_path ...]")
        sys.exit(1)
    
    total_changes = 0
    for file_arg in sys.argv[1:]:
        file_path = Path(file_arg)
        if file_path.exists() and file_path.suffix == '.py':
            changes = fix_file(file_path)
            if changes > 0:
                print(f"Fixed {changes} long lines in {file_path}")
            total_changes += changes
    
    print(f"Total: Fixed {total_changes} long lines")


if __name__ == "__main__":
    main()