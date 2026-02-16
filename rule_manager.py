import yaml
from urllib.parse import urlparse

class RuleManager:
    def __init__(self, config_path="sites.yaml"):
        self.config_path = config_path
        self.sites = self._load_config()

    def _load_config(self):
        """读取并解析 YAML 配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"❌ 配置文件读取失败: {e}")
            return []

    def get_rule_by_url(self, url):
        """
        根据 URL 自动匹配规则
        原理：提取 URL 中的域名，去配置文件里找有没有对应的 domain
        """
        parsed_url = urlparse(url)
        domain = parsed_url.netloc  # 例如: www.example.com
        print(domain)
        for site in self.sites:
            if domain in site.get('domains', []):
                print(f"✅ 匹配到规则模板: {site['name']}")
                return site
        
        print(f"⚠️ 未找到适配该域名的规则: {domain}")
        return None

# === 测试代码 (直接运行此文件可测试) ===
if __name__ == "__main__":
    manager = RuleManager()
    
    # 模拟测试
    test_url = "https://www.mnwx.cc/book/419057/"
    rule = manager.get_rule_by_url(test_url)
    
    if rule:
        print("尝试读取标题规则:", rule['rules']['chapter_title'])