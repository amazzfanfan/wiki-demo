"""端到端测试：OKF 改造验证（直接调 IngestFlow，不走 HTTP）"""
import os
import sys
import time

os.environ['ENABLE_SCHEMA'] = 'true'
os.environ['USE_MINIO'] = 'false'

sys.path.insert(0, os.path.dirname(__file__))

print("=== OKF E2E Test (Direct IngestFlow) ===")

import importlib
import core.schema_engine
import core.path_resolver
importlib.reload(core.schema_engine)
importlib.reload(core.path_resolver)

from core.schema_engine import is_enabled
from core.path_resolver import USE_MINIO
print(f"  schema_enabled={is_enabled()}, USE_MINIO={USE_MINIO}")

test_ws = "okf_test"

# 清理旧测试数据
import shutil
wiki_dir = os.path.join(os.path.dirname(__file__), "data", "wiki", "testuser1", test_ws)
if os.path.exists(wiki_dir):
    shutil.rmtree(wiki_dir)
    print(f"  Cleaned old wiki data: {wiki_dir}")

# 写长文本（确保 >= 2 chunks，每 chunk 1500 chars）
test_content = """双相钢（Dual-Phase Steel, DP钢）是先进高强钢（AHSS）的重要类型之一，广泛应用于汽车车身结构件。
DP780是典型的双相钢牌号，名义抗拉强度为780MPa，微观组织由软韧的铁素体（Ferrite）基体与硬强的马氏体（Martensite）岛组成。
这种双相组织赋予DP钢优异的强度-塑性平衡，使其成为替代传统高强钢的理想选择。
DP钢的典型化学成分（质量分数%）为：C 0.09, Mn 1.65, Si 0.25, Cr 0.45, Mo 0.15。

退火温度（Annealing Temperature）是连续退火工艺中控制双相钢组织演变与力学性能的核心参数。
在DP780双相钢冷轧板（厚度1.2mm）的热处理中，退火温度设定范围为760°C–850°C，保温时间固定为120s。
研究表明，退火温度对力学性能的影响呈现先升后降的趋势：
- 760°C时，抗拉强度785MPa，延伸率14.2%，强塑积11147 MPa·%
- 790°C时，性能持续提升
- 820°C时达到最优：抗拉强度842MPa，延伸率16.8%，强塑积14146 MPa·%，满足DP780标准
- 850°C时性能回落：抗拉强度降至810MPa，延伸率15.1%
性能回落的原因在于退火温度过高（850°C）导致马氏体体积分数异常升高至约35%，
引发局部应力集中和带状偏聚组织，显著损害塑性。

过时效温度（Overaging Temperature）指连续退火中快冷阶段结束、进入慢冷前的恒温平台温度，
直接影响碳化物析出行为与固溶碳含量。在DP780双相钢工艺中：
- 420°C时，Fe3C（渗碳体）析出量最大，但延伸率最低（9.8%），
  原因是Fe3C在铁素体/马氏体界面偏聚形成3–5nm连续薄膜，引发局部脆化
- 440–460°C时，纳米级Fe3C弥散析出，平均粒径15–25nm，数密度约10^22/m³，
  析出强化贡献约120MPa，达到强度与塑性的最优平衡
- 超过480°C时，发生Ostwald熟化（Ostwald Ripening），Fe3C粒径增大至50–80nm，
  数密度骤降至约10^20/m³，强化贡献降至约40MPa

冷却制度（Cooling Regime）是指在连续退火过程中对带钢实施的温度-时间路径控制，
直接影响马氏体相变动力学和残余奥氏体（Retained Austenite）稳定性。
以DP780为例，三种典型冷却方案的对比：

方案A（单段快冷）：50°C/s直接冷至室温。
- 跳过碳配分窗口，残余奥氏体含量低（2.1%），稳定性差（Ms=180°C）
- 马氏体体积分数最高（38%），强度高但塑性受限
- 以亚稳态ε-碳化物为主，几乎不形成Fe3C

方案B（两段冷却）：30°C/s至460°C + 10°C/s至280°C。
- 在过时效段（460°C）提供约15s碳配分时间
- 残余奥氏体体积分数显著提升（4.8%），稳定性提高（Ms=-20°C）
- 强塑积达最优：830 MPa × 16.5% = 13695 MPa·%

方案C（三段冷却）：增加500°C恒温段。
- 500°C段促使Cr原子充分扩散，形成粗大M23C6碳化物（50-100nm）
- 碳被深度束缚，30%残余奥氏体Ms>50°C，72h后显著分解
- 固溶碳耗竭，BH值（烘烤硬化值）暴跌至仅8MPa

烘烤硬化性（Bake Hardening, BH）是评价汽车用钢板抗凹陷能力的关键指标。
BH值定义为材料经170°C×20min烘烤后屈服强度的增量（ΔYS），单位MPa。
其本质源于烘烤过程中固溶碳原子被位错钉扎所致。
碳化物析出程度决定固溶碳含量：析出不足则固溶碳高、BH值高；析出充分则固溶碳低、BH值低。

强塑积（Strength-Plasticity Product）是评价先进高强钢综合力学性能的关键指标，
定义为抗拉强度（MPa）与延伸率（%）的乘积，单位MPa·%。
需注意强塑积不能孤立评估，须结合BH值和残余奥氏体稳定性综合判断。
例如方案C强塑积数值最高（14378 MPa·%），但BH值仅8MPa，实际成形性能反而受限。

碳配分（Carbon Partitioning）是指在连续退火冷却过程中，
碳原子从过饱和马氏体前驱体向未转变奥氏体界面扩散并富集的过程，
是提升残余奥氏体稳定性的核心机制。
有效碳配分需要满足温度窗口（440–480°C）和时间窗口（10–20s）的双重约束。
"""

# 写入测试文件
raw_dir = os.path.join(os.path.dirname(__file__), "data", "raw", test_ws)
os.makedirs(raw_dir, exist_ok=True)
test_file = os.path.join(raw_dir, "test_dp_steel.txt")
with open(test_file, "w", encoding="utf-8") as f:
    f.write(test_content)
print(f"\n📄 Test file: {len(test_content)} chars")

# 直接调用 IngestFlow
from workflows.ingest_flow import IngestFlow
from tools.edit_tools import set_context

set_context(user_id="testuser1", kb_name=test_ws)

flow = IngestFlow()
t0 = time.time()
result = flow.run(
    input_source=test_file,
    kb_name=test_ws,
    user_id="testuser1",
    doc_name="test_dp_steel"
)
elapsed = time.time() - t0
print(f"\n⏱️  Completed in {elapsed:.1f}s, result={result}")

# ===== 检查结果 =====
print(f"\n{'='*60}")
print("📂 Result Files:")
print(f"{'='*60}")

for fname in ["schema.md", "log.md", "index.md", "schema_suggestions.md"]:
    fpath = os.path.join(wiki_dir, fname)
    if os.path.exists(fpath):
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        print(f"\n📋 {fname} ({len(content)} chars):")
        print(content[:600])
    else:
        print(f"\n⚠️ {fname}: NOT FOUND")

concepts_dir = os.path.join(wiki_dir, "concepts")
if os.path.exists(concepts_dir):
    concept_files = sorted([f for f in os.listdir(concepts_dir) if f.endswith(".md")])
    print(f"\n📚 concepts/ ({len(concept_files)} files):")
    for cf in concept_files:
        print(f"  - {cf}")
    
    fm_count = sum(1 for cf in concept_files 
                   if open(os.path.join(concepts_dir, cf), encoding="utf-8").read().startswith("---"))
    print(f"\n  OKF frontmatter: {fm_count}/{len(concept_files)} files")
    
    for cf in concept_files[:2]:
        fp = os.path.join(concepts_dir, cf)
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read()
        print(f"\n📄 {cf}:")
        print(content[:600])
else:
    print("\n⚠️ concepts/: NOT FOUND")

print(f"\n{'='*60}")
print("✅ E2E Test Complete")
