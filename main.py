import asyncio
import aiohttp
import aiofiles
import os
import json
import re
import logging
import gzip
from parsel import Selector
from urllib.parse import urljoin
from rule_manager import RuleManager  # 确保 rule_manager.py 在同级目录

# ==========================================
# 🔧 配置区域 (Configuration Area)
# ==========================================

# === 日志配置 (比 print 更专业) ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === 全局配置 ===
CONCURRENCY = 5  # 并发数: 同时下载5章 (建议不要超过10，以免被封)
DELAY = 0.5      # 每次请求后的礼貌延迟 (秒)
RETRIES = 3      # 失败重试次数

# === 请求头 ==
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# ==========================================
# 🛠️ 核心逻辑 (Core Logic)
# ==========================================



def clean_filename(filename):
    """清洗文件名，移除 Windows/Linux 不允许的字符"""
    return re.sub(r'[\\/*?:"<>|]', "", filename).strip()

async def fetch(session, url, encoding='auto'):
    """通用请求函数 (带基础重试)"""
    for i in range(RETRIES):
        try:
            async with session.get(url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    # 读取原始字节
                    raw = await response.read()
                    
                    # 检查是否是 gzip 压缩 (魔数: 0x1f 0x8b)
                    if raw[:2] == b'\x1f\x8b':
                        try:
                            raw = gzip.decompress(raw)
                        except Exception as e:
                            print(f"⚠️ gzip 解压失败: {e}")
                    
                    # 解码为字符串
                    if encoding != 'auto':
                        # 使用指定编码
                        try:
                            return raw.decode(encoding)
                        except (UnicodeDecodeError, LookupError):
                            print(f"⚠️ 使用指定编码 {encoding} 失败，尝试自动检测...")
                    
                    # 自动尝试多种编码
                    for enc in ('utf-8', 'gb18030', 'gbk', 'gb2312', 'big5'):
                        try:
                            text = raw.decode(enc)
                            return text
                        except (UnicodeDecodeError, LookupError):
                            continue
                    
                    # 都失败了，用 utf-8 忽略错误
                    return raw.decode('utf-8', errors='ignore')
                else:
                    print(f"⚠️ 请求失败 [{response.status}]: {url}")
                    return None
        except Exception as e:
            print(f"❌ 连接异常 (第{i+1}次): {url} - {e}")
        await asyncio.sleep(1) # 失败后稍微等一下再重试
    return None

async def save_chapter(novel_dir, chapter_idx, title, content):
    """保存章节到文件"""
    # 文件名格式: 0001_第一章.txt (加入序号方便排序)
    filename = f"{chapter_idx:04d}_{clean_filename(title)}.txt"
    filepath = os.path.join(novel_dir, filename)

    try:
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            await f.write(title + "\n\n")
            await f.write(content)
    except Exception as e:
        logger.error(f"文件写入失败: {filename} - {e}")

async def download_chapter(session, url, idx, rules, encoding, semaphore, novel_dir):
    """下载单个章节的工作单元"""
    async with semaphore:  # 限制并发
        print(f"⏳ [{idx}] 正在下载: {url} ...")
        html = await fetch(session, url, encoding)
        if not html:
            print(f"⚠️ [{idx}] 正文获取失败: {url} ...")
            return
        
        sel = Selector(text=html)
        
        # 解析标题和内容
        title = sel.css(rules["chapter_title"]).get()
        # 获取所有段落并拼接
        content_lines = sel.css(rules["chapter_content"]).getall()
        # 清洗数据: 去除首尾空格，用换行符连接
        content = "\n".join([line.strip() for line in content_lines if line.strip()])
        
        if title and content:
            await save_chapter(novel_dir, idx, title, content)
            print(f"✅ [{idx}] 保存成功: {title}")
        else:
            print(f"⚠️ [{idx}] 解析失败 (可能是规则错误或反爬): {url}")
        
        await asyncio.sleep(DELAY) # 礼貌性延迟

async def main():
    # 1. 输入目标
    # 这里以后可以通过命令行参数传入，现在先写在这
    TARGET_URL = "https://www.mnwx.cc/book/419057/" # 替换你的目标
    NOVEL_NAME = "我的一位仙子道友"

    # 2. 加载规则 (关键变化点!)
    manager = RuleManager()
    site_config = manager.get_rule_by_url(TARGET_URL)

    if not site_config:
        print("程序终止：没有找到对应的网站规则，请先在 sites.yaml 中配置。")
        return
    else:
        # 从配置中提取具体规则
        rules = site_config['rules']
        encoding = site_config.get('encoding', 'utf-8')

    """主调度器"""
    print(f"🚀 启动爬虫，目标: {NOVEL_NAME}")
    
    # 1. 创建存储目录
    base_dir = "downloads"
    novel_dir = os.path.join(base_dir, NOVEL_NAME)
    os.makedirs(novel_dir, exist_ok=True)
    
    # 2. 初始化并发限制器
    semaphore = asyncio.Semaphore(CONCURRENCY)
    
    async with aiohttp.ClientSession() as session:
        # 3. 获取目录页
        print("正在获取目录列表...")
        toc_html = await fetch(session, TARGET_URL)
        if not toc_html:
            print("❌ 无法访问目录页，程序终止。")
            return

        # 4. 解析目录
        sel = Selector(text=toc_html)
        links = sel.css(rules["chapter_list"])
        
        tasks = []
        print(f"📖 发现 {len(links)} 个章节，准备开始下载...")

        # 生成元数据 (Simple Meta Data)
        meta_info = {
            "name": NOVEL_NAME,
            "url": TARGET_URL,
            "total_chapters": len(links),
            "status": "downloading"
        }
        with open(os.path.join(novel_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta_info, f, ensure_ascii=False, indent=2)

        # 5. 创建任务队列
        for idx, link in enumerate(links):
            # 提取链接
            href = link.attrib.get(rules["chapter_link_attr"])
            if not href: continue
            
            # 补全 URL
            full_url = urljoin(TARGET_URL, href)
            
            # 创建任务 (注意：idx+1 是为了让章节序号从1开始)
            task = asyncio.create_task(
                download_chapter(session, full_url, idx+1, rules, encoding, semaphore, novel_dir)
            )
            tasks.append(task)
        
        # 6. 执行所有任务
        if tasks:
            await asyncio.gather(*tasks)
        else:
            print("⚠️ 未找到任何章节链接，请检查 'chapter_list' 规则！")

    print(f"🎉 全部任务完成！文件保存在: {novel_dir}")

if __name__ == "__main__":
    # Windows 下 Python 3.8+ 需要设置事件循环策略 (防止报错)
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())