# 存储模块：负责文件系统操作，保存章节内容和索引
#主程序只需要把数据扔给它，不需要关心文件怎么存、存哪里。
# 1. 目录结构：downloads/[作者] 小说名/chapters/
# 2. 每章保存为单独的文本文件，命名格式：0001_章节标题.txt
# 3. 索引文件：index.json，记录已下载章节的 URL 和对应的文件名，方便断点续传


import os
import json
import re
import aiofiles
import logging

logger = logging.getLogger(__name__)

class StorageHandler:
    def __init__(self, novel_name, author="Unknown"):
        self.novel_name = self._clean_str(novel_name)
        self.author = self._clean_str(author)
        
        # 1. 构建标准目录: downloads/[作者] 小说名/
        # 如果作者名包含 "作 者：" 这种前缀，可以在这里清洗，或者在爬虫里清洗
        self.base_dir = os.path.join("downloads", f"[{self.author}] {self.novel_name}")
        self.chapter_dir = os.path.join(self.base_dir, "chapters")
        
        # 2. 初始化目录
        os.makedirs(self.chapter_dir, exist_ok=True)
        
        # 3. 加载或初始化索引 (用于断点续传)
        self.index_path = os.path.join(self.base_dir, "index.json")
        self.downloaded_chapters = self._load_index()

    def _clean_str(self, s):
        """清洗字符串，去除非法字符"""
        if not s: return "Unknown"
        # 去掉文件名里的非法字符
        return re.sub(r'[\\/*?:"<>|]', "", s).strip()

    def _load_index(self):
        """读取已下载的章节列表"""
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_meta(self, meta_info):
        """保存小说元数据 (meta.json)"""
        path = os.path.join(self.base_dir, "meta.json")
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(meta_info, f, ensure_ascii=False, indent=2)
            logger.info(f"📚 元数据已保存: {path}")
        except Exception as e:
            logger.error(f"元数据保存失败: {e}")

    def is_downloaded(self, chapter_url):
        """检查该章节是否已经下载过"""
        return chapter_url in self.downloaded_chapters

    async def save_chapter(self, idx, title, content, url):
        """
        保存章节内容，并更新索引
        """
        safe_title = self._clean_str(title)
        filename = f"{idx:04d}_{safe_title}.txt"
        filepath = os.path.join(self.chapter_dir, filename)

        try:
            # 1. 写入文本文件
            async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
                await f.write(f"{title}\n\n")
                await f.write(content)
            
            # 2. 更新内存中的索引
            self.downloaded_chapters[url] = {
                "idx": idx,
                "title": safe_title,
                "file": filename
            }
            
            # 3. (可选) 实时写入索引文件，防止程序崩溃丢失进度
            # 为了性能，也可以每下载10章存一次，这里为了安全每次都存
            with open(self.index_path, 'w', encoding='utf-8') as f:
                json.dump(self.downloaded_chapters, f, ensure_ascii=False)
                
            logger.info(f"✅ [{idx}] 保存成功: {title}")
            
        except Exception as e:
            logger.error(f"❌ 写入文件失败: {title} - {e}")