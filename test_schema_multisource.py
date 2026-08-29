"""快速提取 B 系统知识库的完整页面内容"""
import json
from pathlib import Path

# 从上次运行的报告文件读取
report = Path("test_schema_multisource_report.md").read_text(encoding="utf-8")

# 提取 B 知识库部分
b_section = report.split("## B 知识库")[1].split("## B 检测的矛盾")[0] if "## B 知识库" in report else ""

# 输出到独立文件，方便阅读
output = "# 🅱️ Schema 系统生成的 Wiki 页面（完整内容）\n\n"
output += "> 3 篇冷轧钢论文依次 ingest 后的知识库\n\n"
output += "---\n\n"

# 直接从报告里提取（报告已经截断了300字，需要重新跑）
# 改为直接从测试脚本提取
print("需要重新跑测试来提取完整内容...")
print("或者直接从上次运行的日志中提取")
