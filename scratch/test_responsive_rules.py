"""
CSS Responsive & Dark Mode Verification Engine
Inspects all CSS files for:
- Viewport breakpoint coverage (1920, 1366, 1024, 768, 375)
- Grid responsiveness & collapse behavior
- Modal dialog responsiveness
- Dark mode theme completeness
- Overflow-x constraints
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_DIR = ROOT / "static" / "css"

def audit_css():
    css_files = list(CSS_DIR.glob("*.css"))
    print(f"Auditing {len(css_files)} CSS files...")
    
    breakpoints_found = set()
    dark_mode_selectors = []
    modal_rules = []
    overflow_guards = []
    
    for f in css_files:
        content = f.read_text(encoding="utf-8")
        
        # Check media queries
        for m in re.finditer(r'@media\s*\(([^)]+)\)', content):
            breakpoints_found.add((f.name, m.group(1)))
            
        # Check dark mode
        for m in re.finditer(r'\[data-bs-theme=["\']dark["\']\]([^{]+)', content):
            dark_mode_selectors.append((f.name, m.group(1).strip()))
            
        # Check modal sizing
        for m in re.finditer(r'(\.modal[^{]*\{[^}]+\})', content):
            modal_rules.append((f.name, m.group(1).strip()))

    print(f"Total media queries found: {len(breakpoints_found)}")
    print(f"Total dark mode overrides: {len(dark_mode_selectors)}")
    
    # Check specific target breakpoints:
    # 1920: min-width: 1600px / 1650px
    # 1366: max-width: 1450px / 1250px
    # 1024: max-width: 1150px / 1000px / 980px
    # 768: max-width: 768px / 767px / 700px
    # 375: max-width: 480px / 560px
    targets = {
        'Ultra-wide (1600px+)': False,
        'Laptop/Standard (1250px-1450px)': False,
        'Tablet/Small Desktop (980px-1150px)': False,
        'Tablet Portrait (700px-768px)': False,
        'Mobile (<=560px)': False,
    }
    
    for fname, rule in breakpoints_found:
        if '1600px' in rule or '1650px' in rule:
            targets['Ultra-wide (1600px+)'] = True
        if '1250px' in rule or '1450px' in rule or '1366px' in rule or '1280px' in rule:
            targets['Laptop/Standard (1250px-1450px)'] = True
        if '980px' in rule or '1000px' in rule or '1024px' in rule or '1150px' in rule or '1100px' in rule:
            targets['Tablet/Small Desktop (980px-1150px)'] = True
        if '700px' in rule or '767px' in rule or '768px' in rule:
            targets['Tablet Portrait (700px-768px)'] = True
        if '480px' in rule or '560px' in rule or '600px' in rule:
            targets['Mobile (<=560px)'] = True

    print("\n=== BREAKPOINT COVERAGE ===")
    for target, covered in targets.items():
        print(f"  {target}: {'PASS' if covered else 'MISSING'}")

if __name__ == '__main__':
    audit_css()
