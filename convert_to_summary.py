"""
Convert today's digest JSON + article .txt files into docs/data/{date}_summary.json
This is what the schedule agent will produce each day.
Run once to migrate existing 2026-06-02 data.
"""
import sys, json, re
from pathlib import Path
from datetime import datetime, timezone

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE     = Path(__file__).parent
DATA_DIR = BASE / "data"
OUT_DIR  = BASE / "docs" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Podcast summary condensed (already in digest JSON) ─────────────────
PODCAST_SUMMARIES = {
    # 张小珺
    "143. 对何小鹏的第二次访谈":
        "何小鹏谈2025年重注人形机器人Iron诞生与意外，两成胜率仍坚持下注；聊技术变革下CEO心路及新车GX。",
    "142. 雨森的创投观察第2集":
        '真格基金戴雨森：好的Harness比OS更有价值，"AGI在缩水"；2026大机会在于勇敢做通用方向。',
    "141. Freda的投资札记第2集":
        "Altimeter合伙人Freda：接力赛变篮球赛，AI让组织从多层级转向3-5人小队；投资人开始测试能否被Agent替代。",
    # 卫诗婕
    "75.与灵初王启斌聊「灵巧操作」":
        "灵初智能王启斌：10万小时人类操作数据是富矿；登顶摩根士丹利全球人形机器人报告；具身大脑路线直指智能上限。",
    "74.与地瓜、阿里云的访谈":
        "地瓜机器人与阿里云聊具身基建：AI第三朵云将成机器人行业母生态；Token经济下独立开发者可推动新浪潮。",
    "73.【520 特辑】AI +爱，赢了":
        "脊髓损伤者与妻子用6个AI Agent、两台电脑24小时完成脑机信号控轮椅demo，获小红书黑客松硬件冠军。",
    # 罗永浩
    "罗永浩的X字路口！当一群情绪不稳定的杠精讨论起情绪稳定":
        "脱口秀演员高寒、小块等聊情绪稳定，节目前段混乱；块神后段表现力挽狂澜，可直接跳至1:24处。",
    "郑执×罗永浩":
        '东北文艺复兴三杰之一郑执，聊自编自导电影《森中有林》及"永远赶末班车"的人生路。',
    "李想×罗永浩":
        "李想谈理想L9 Livis旗舰SUV（自研芯片算力2560 TOPS）及AI+具身智能公司转型；让普通人过上富豪的生活。",
    # 硅谷101
    "E238｜聊聊Harness时代AI-First的组织架构":
        "CreaoAI实践Harness工程：99%代码由AI完成，每天3-8次部署；初级工程师比资深更适应转型。",
    "E237｜央视和FIFA谈判纷争背后":
        "央视与FIFA版权谈妥，2002至2026年价格涨20倍；中国体育版权只有世界杯和奥运会稳赚不赔。",
    "E236｜99%的作业都是AI写的":
        "清华、纽大、哥大毕业生：99%作业有AI参与；大学核心价值转向同侪交流与批判性思维。",
    # 晚点聊
    "167: 洋葱学园杨临风":
        "洋葱学园CEO杨临风：AI捷径正在杀死真学习；自主学习是意愿、能力和工具的协同。",
    "166: 许华哲再次具身创业":
        "破壳机器人许华哲：具身不是robotics也不是自动驾驶，强化学习可能被低估。",
    "164: 当AI\"杀死\"SaaS":
        '明略吴明辉：AI杀死SaaS，闭源软件价值消失；将开源多Agent协同网络"章鱼"。',
    # 乱翻书
    "267.3000块成本，3.5亿次播放":
        "AI短剧《安徽小木匠》：3000元成本、19天上线，抖音播放超3.5亿次、收入50万；剧本全由AI生成。",
    "全面压制，不留空档：字节跳动如何做增长":
        "字节增长中台10年方法论：TikTok一个双月涨1.2亿DAU；核心是把增长做成标准化能力。",
    "头腾大战八年后":
        "从2018年朋友圈争论到相互起诉，复盘头腾大战8年；双方最终承认这场公关战不该打。",
    # 英文播客
    "#497 – Biggest Mysteries in Physics":
        "Fermilab粒子物理学家Don Lincoln深度讲解反物质、暗能量与万物理论等物理学最大未解之谜。",
    "#496 – FFmpeg":
        "VLC开发者与FFmpeg贡献者讲述互联网视频底层技术的历史与现状。",
    "#495 – Vikings":
        "历史学者Lars Brownworth深度讲述维京战士、Ragnar与中世纪北欧战争文化。",
    "Reiner Pope – Chip design from the bottom up":
        "MatX CEO从逻辑门讲起，拆解GPU、TPU、FPGA架构演化逻辑，探讨人脑与硅基架构差异。",
    "Eric Jang – Building AlphaGo from scratch":
        "从零构建AlphaGo，重温搜索+强化学习基础；探讨RL在LLM中的信用分配难题。",
    "David Reich – Why the Bronze Age was an inflection point":
        "古DNA研究：自然选择在农业革命后加速，青铜时代认知遗传预测值上升约一个标准差。",
    "Why Video Agent models are next":
        'xAI工程师谈：视频模型智能来自LLM；下一代视频AI是"视频Agent"而非更好的生成模型。',
    "The Age of Async Agents":
        "Devin母公司Cognition完成10亿美元D轮；Shopify等大公司自建Agent vs 专业Agent公司的权衡。",
    "ESM: The Bitter Lesson is Coming for Proteins":
        "BioHub发布ESMFold 2，68亿蛋白质图谱；推理时间Scaling在癌症等5靶点有效。",
    "Building an AI Guardian for Enterprise with Onyx Security":
        "Onyx Security构建AI控制平面，监控自主Agent权限与意图；讨论渐进式模型上线。",
    "The Story Behind Cerebras' $63 Billion IPO":
        "Cerebras完成630亿美元IPO，晶圆级芯片推理速度达GPU的20倍；OpenAI 200亿合同4周谈成。",
    "Pax Silica":
        "美国主导的Pax Silica 14国AI供应链安全联盟：菲律宾建4000英亩经济安全区。",
    "ChatGPT – The Super Assistant Era":
        "OpenAI产品负责人谈ChatGPT长期留存策略；从聊天机器人演变为主动超级助手的路线图。",
    "AI Enterprise - Databricks & Glean":
        "Databricks与Glean：95%的AI项目失败；LLM商品化，持久护城河在专有数据和Agentic工作流。",
    "All things AI w @sama & @satyanadella":
        "Sam Altman与Satya Nadella谈3万亿美元AI建设：OpenAI-微软合作解锁云规模。",
}

# ── Article summaries (from our HTML) ─────────────────────────────────
ARTICLE_SUMMARIES = {
    "The Epoch Brief - June 1, 2026": """本期周报三大要点：
① **开放模型滞后闭源前沿约4个月**，差距自2025年10月以来略有扩大，约等同于GPT-5与GPT-5.5之间的性能跨度（ECI指数8分）。
② **超大规模计算商资本开支Q1 2026达1561亿美元**，全年预计7700亿、2027年突破1万亿。
③ **全球推理供给增速约3-4倍/年，但token需求增速约10倍/年**，算力紧缺或已到来，将推高前沿算力价格并迫使普通用户转向更小的模型。""",

    "Is a compute crunch coming?": """Epoch AI对全球GPU推理算力进行定量建模，以Kimi K2.6为基准，运行于GB200/GB300 NVL72。
**供给侧**：约190万块GB200 + 150万块GB300（占全球算力约40%），理论可产出每秒**5亿至200亿**输出token（取决于上下文长度）。全球供给每年增长约**3-4倍**。
**需求侧**：年增速约**10倍**，供需剪刀差意味着算力紧缺即将到来，Agentic长上下文工作负载首当其冲。
**关键技术**：解码阶段是主要带宽瓶颈；KV缓存压力随上下文增长线性放大；MLA注意力、分块Prefill和投机解码是关键效率工具。
**投资含义**：前沿访问价格上涨；高带宽内存、高效互联价值凸显；模型效率快速提升将使更小模型尽快赶上前沿。""",

    "The Epoch Brief - May 22, 2026": """两大研究更新：
① AI芯片**内存（HBM）成本占比从52%升至63%**（2024年Q1至2025年Q4），HBM支出从约120亿升至约320亿美元，是增速最快的成本分项。
② 顶级实验室当前使用**不足全球AI算力的一半**，但按现有增速，数年内可吸收大部分余量。届时继续扩展将受制于芯片产能，而AI资本开支已接近1万亿美元/年——"需要戏剧性的经济变革"。
此外：Epoch AI将在网站提供长文音频播放功能；开放多个研究员岗位。""",

    "AI Dark Output: The Visible Cost of Invisible Output": """SemiAnalysis提出"**AI黑暗产出（Dark Output）**"框架：AI创造的大量经济价值因GDP统计方法局限而不可见。
**三类形态**：①替代性——AI取代人工后，GDP中对应服务交易消失，如法律文书成本从150美元降至0.5美元（降幅>99%）；②新增型——AI使以前"太贵"的任务变为可行（文献综述从2000美元降至2美元），产生真实价值但无GDP痕迹；③捕获型——具市场定价权的企业维持原价，利润爆炸。
**核心数据**：当前具备实质替代潜力的**劳动力成本约1.5万亿美元**（Tier 4+证据）。Anthropic 2026年3月经济指数显示**37%的token消耗在计算机与数学领域**，但软件投资对GDP的贡献未偏离AI前趋势。
**统计指纹**：AI暴露行业出现"就业下降+平均薪资上升"矛盾（低薪岗位率先消失拉高均值）。
**宏观含义**：GDP可见AI成本（数据中心、GPU、电力），但无法见其产出——若不解决这一计量危机，政策和投资决策将基于失真数据。""",

    "Finding Miscompiles for Fun, Not Profit": """前Google/Waymo/OpenAI编译器工程师的AI辅助漏洞挖掘实验：
**Fuzzing阶段**：与AI协作编写fuzzer，对NVIDIA ptxas编译器**3天发现40+个错误编译**（一周后升至80+）；AMD LLVM AMDGPU后端速率相近。
**代码阅读阶段**：让Claude并行运行**50个子Agent阅读LLVM代码**，发现速率**每4分钟1个**；x86后端接近**每2分钟2个**，且无减速。
**关键漏洞**：LLVM将原子store降级为非原子操作——99%时间无症状，1%时静默数据损坏，极难溯源，可导致生产系统灾难性故障。
**成本**：Fuzzer约1000美元；代码阅读Agent单次下午耗费**超过1万美元**。
**结论**："五个月前不可能完成的事，现在只是非常昂贵；**预算差距将成为竞争优势的分水岭**。"文章补记：Opus 4.8发布后同等成本可降至约1/5。""",

    "Anthropic Growth and Bedrock Mix Drive AWS Margins Higher While Peers Lag": """SemiAnalysis Tokenomics 2.0模型分析超大规模云厂商AI业务利润率分化。
**核心结论**：**AWS 1Q26 EBIT利润率环比提升213bp**，是同期唯一上行的CSP；Oracle和Coreweave低于预期，Azure下行，GCP含DeepMind训练成本分摊不确定性。
**Bedrock结构性优势**：AWS通过Bedrock分发Claude等前沿模型，以"Anthropic为卖方、AWS收基础设施费+收入分成"实现高利润率TaaS业务，远优于纯GPU出租。
**关键数据**：AWS AI占总营收比从**1Q24的2%升至1Q26的10%**（GCP/Azure分别为36%/27%，但利润率均低于AWS）；**Trainium芯片承担超50%的Bedrock token负载**；Graviton CPU在Anthropic、OpenAI、Meta均有大规模部署。
**竞争护城河**：三大CSP的TaaS业务规模合计超**100亿美元ARR**，Neocloud几乎为零；只有AWS/Azure/GCP三家可同时接入OpenAI、Claude、Gemini三大前沿模型。""",

    "Semis Memo: Supply Chain Inheritance": """Citrini半导体备忘录，核心命题：**AI数据中心正在继承电动车供应链**。
**继承机制**：Nvidia 2025年技术博客明确说明，**800V直流机架架构技术直接来自EV和太阳能行业**。AI算力基础设施对MLCCs、功率MOSFETs、滤波器等模拟器件的需求激增。
**供需错配**：TI、NXP等被多轮资本开支周期灼伤，宁可涨价也不扩产——正进入**量价齐升**阶段。Murata、Vishay、Samsung Electro-Mechanics等MLCC供应商已开始表现。
**其他主题**（付费墙后）：Agentic时代CPU需求回升、Neocloud推理短缺机遇、AI材料瓶颈、韩国半导体解锁机会。""",

    "Flash Note: Defense Production Act": """美国总统签署《国防生产法》第303号认定（2026-04-20），将变压器、高压输电组件、功率电子器件等**列为国家防御必要物资**，使能联邦贷款担保支持国内产能扩张。
**市场信号**：GE Vernova **1Q26单季度电气化订单净增量接近2022-2025全年增量之和**，增长加速。
**韩国厂商是关键边际供应商**：美国765kV超高压变压器产能来自四家韩企——Hyosung重工（美国唯一765kV产能）、HD现代电气（2027年扩产至150台/年）、LS Electric、日进电气。四家合计订单积压**239亿美元**（约5-6年工作量）。""",

    "Strait of Hormuz: A Citrini Field Trip": """Citrini研究员"Analyst #3"亲赴霍尔木兹海峡实地调研，背景：所有分析人士都依赖相同陈旧卫星图，**AIS数据遗漏约一半实际过境船只**。
**执行**：持四门语言能力、配备1.5万美元现金和高倍摄影设备，签署"不得采集信息"保证书后入境阿曼；随后乘无GPS快艇深入海峡，**在距伊朗海岸18英里处游泳**，头顶Shahed无人机飞过，伊朗革命卫队巡逻艇游弋在侧；被阿曼海岸警卫队拦截、手机被没收，事后完成8小时复盘汇报。
**目标**：厘清伊朗革命卫队对过境船只的最新规则，为投资者提供任何二手分析都无法替代的现场情报。投资结论在付费墙后。""",

    "Investing in Endra": """a16z领投Endra的A轮融资。Endra将机械、电气和管道（MEP）工程设计自动化，目标市场超过**1500亿美元**的全球MEP咨询服务市场。
平台读取标准BIM（Revit格式）文件，在3D环境中重建建筑，工程师设定规则后点击"优化"，原本耗时数周的逐层点击工作可在一次会话内完成。
创始团队：瑞典人Niklas Lindgren和Anton Juric曾共同创业并退出；技术联创David Rydberg和Gustav Hammarlund来自高盛斯德哥尔摩低延迟交易团队。已拥有多家全球顶级MEP公司为早期客户，营收呈垂直增长。""",

    "Keeping the Drone Swarm Alive": """a16z深度分析：美国国防自主无人系统大规模部署的关键瓶颈是**后勤可持续性**，而非技术本身。
**背景**：五角大楼Replicator计划，FY27预算**540亿美元（同比增240倍，超过整个海军陆战队预算）**。
**瓶颈**：①现有基础设施为有人平台设计，无人系统缺乏前沿补给能力；②GAO警告：已采购**43亿美元、21艘无人艇**但遗漏全生命周期成本；③**平台全生命周期成本70%在于可持续运营**，近半超预期；④波音未投标XLUUV后续运营合同——初步市场失灵。
**结论**：在解决后勤自动化之前，大规模部署无人平台只是将瓶颈从战场前移至补给线。自主后勤本身是下一个重要国防科技投资方向。""",

    "Charts of the Week: Retail to the Moon": """本期三大图表主题：
**① 零售投资者史上最活跃**：5月零售现金股票成交量**超越2021年迷因股峰值12%**；零售期权日均合约量约历史月均的**160%**；半导体期权达2020年后月均的**2.8倍**；IB/Robinhood/Schwab合计保证金余额超**2500亿美元**（疫情前5倍）。七周内无单日净卖出，零售从"逢跌买入稳定器"变为"单边上涨助推器"，产生"flow fragility"风险。
**② AI资本开支债务化**：超大规模厂商2026年已发行约**1500亿美元债券**（同比增35%）；AI相关债务占2026年投资级净发行约**50%**、高收益债约**40%**；IT资本开支占S&P 500总资本开支约**40%**。
**③ FedRAMP 20x**：政府软件安全认证大幅提速——首批300项历时逾10年，**2025年单年批准约140项**，为科技公司打开政府端市场新窗口。""",

    "Games and Numbers (May 20 - June 2, 2026)": """2026年5月下旬至6月初PC/主机游戏里程碑：
① **Subnautica 2** EA首5天**销410万份**、收入超1亿美元，2026年PC发行最快启动（含Game Pass达650万用户）；
② **Forza Horizon 6** 首几日约**500万份**、收入超3.25亿美元；
③ **007 First Light** 3天**销150万份**，IO Interactive史上最成功发行，Steam峰值同时在线68,500；
④ **The Witcher 3** 累计突破**6500万份**，巫师IP 1Q26营收同比增**36%**至约1230万美元，2027年发布新DLC；
⑤ **Star Citizen** 众筹突破**10亿美元**，自2010年开发至今仍无正式发布日期。""",

    "AppMagic: Top Mobile Games by Revenue and Downloads in May 2026": """2026年5月手机游戏数据（AppMagic，不含中国安卓市场）：
**收入榜**：①Honor of Kings **1.559亿美元**居首；②Whiteout Survival（1.052亿）；③Royal Match（1.051亿）；④Gossip Harbor **9680万美元**（历史次高月，增长强劲）；⑤Last War: Survival环比骤降**30%至8070万美元**（2024年3月以来最低，或因D2C导流及营销降温）。
**下载榜**：**箭头解谜品类突然爆发**——Miniclip旗下Arrows: Puzzle Escape以**2860万次安装**领跑，同门Arrows GO!以**2380万次**居次，同类型Arrow Puzzle进入前十。此前下载榜长期被超休闲游戏统治，本月出现明显品类轮动。""",
}

def find_summary(title, summaries_dict):
    """Fuzzy match article title to our pre-written summary."""
    for key, val in summaries_dict.items():
        if key in title or title in key:
            return val
    return None

def build_summary_json(date_str, days_back=14):
    json_path = DATA_DIR / f"{date_str}_digest.json"
    if not json_path.exists():
        print(f"[ERROR] {json_path} not found")
        return

    digest = json.loads(json_path.read_text(encoding="utf-8"))

    from datetime import datetime, timedelta
    cutoff = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=days_back)).strftime("%Y-%m-%d")
    print(f"  日期范围: {cutoff} ~ {date_str}")

    # Build podcast list (deduplicated, filtered to last N days)
    seen_titles = set()
    podcasts_out = []
    for p in digest.get("podcasts", []):
        if p.get("date", "")[:10] < cutoff:
            continue
        key = p["title"][:30]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        summary_zh = find_summary(p["title"], PODCAST_SUMMARIES) or ""
        podcasts_out.append({
            "source":     p["source"],
            "title":      p["title"],
            "date":       p["date"][:10],
            "duration":   p.get("duration", ""),
            "link":       p.get("link", ""),
            "summary_zh": summary_zh,
        })

    # Build articles list (filtered to last N days)
    articles_out = []
    seen_art = set()
    for a in digest.get("articles", []):
        if a.get("date", "")[:10] < cutoff:
            continue
        if a["title"] in seen_art:
            continue
        seen_art.add(a["title"])
        summary_zh = find_summary(a["title"], ARTICLE_SUMMARIES) or a.get("summary", "")
        articles_out.append({
            "source":     a["source"],
            "title":      a["title"],
            "date":       a["date"][:10],
            "link":       a.get("link", ""),
            "chars":      a.get("chars", 0),
            "summary_zh": summary_zh,
        })

    output = {
        "date":         date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "podcasts": len(podcasts_out),
            "articles": len(articles_out),
        },
        "podcasts": podcasts_out,
        "articles": articles_out,
    }

    out_path = OUT_DIR / f"{date_str}_summary.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 写入 {out_path}")
    print(f"     播客: {len(podcasts_out)} 条  文章: {len(articles_out)} 条")

if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-06-02"
    build_summary_json(date)
