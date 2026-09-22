import ast
from pathlib import Path
p=Path(__file__).with_name('multivendor_app.py')
ast.parse(p.read_text(encoding='utf-8'))
print('Syntax OK:', p.name)
