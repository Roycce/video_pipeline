import re

with open('gui.py', 'r', encoding='utf-8') as f:
    content = f.read()

replacement = """
    def _log_message(self, msg: str):
        self.log_text.append(msg)
        with open("debug_log.txt", "a", encoding="utf-8") as f:
            f.write(msg + "\\n")
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
"""

content = re.sub(
    r'    def _log_message\(self, msg: str\):.*?scrollbar\.setValue\(scrollbar\.maximum\(\)\)',
    replacement.strip('\n'),
    content,
    flags=re.DOTALL
)

with open('gui.py', 'w', encoding='utf-8') as f:
    f.write(content)
