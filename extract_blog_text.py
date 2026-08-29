from html.parser import HTMLParser
from pathlib import Path

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.in_script = False
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.in_script = True
    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.in_script = False
    def handle_data(self, data):
        if not self.in_script:
            self.text.append(data)

html = Path('D:/WorkPlace/agno-llm-wiki-demo/google_okf_blog.html').read_text(encoding='utf-8')
ext = TextExtractor()
ext.feed(html)
text = '\n'.join(t.strip() for t in ext.text if t.strip())
Path('D:/WorkPlace/agno-llm-wiki-demo/google_okf_blog.txt').write_text(text, encoding='utf-8')
print(f'Extracted {len(text)} chars')
print(text[:2000])
