"""
weather — 全球天气查询（基于 wttr.in，免费无需 API Key）。

Category: utility
Source: wttr.in
"""


def run(city: str = "Beijing", format_str: str = "3") -> str:
    """查询指定城市的天气。

    Args:
        city: 城市名（支持中文如"北京"、英文如"London"、机场代码如"JFK"）
        format_str: 格式 1-4，1=ANSI 终端版，2=纯文本，3=简洁版，4=JSON

    Returns:
        天气信息字符串
    """
    import urllib.parse
    import urllib.request

    encoded = urllib.parse.quote(city)
    url = f"https://wttr.in/{encoded}?format={format_str}&lang=zh"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        return f"[weather] 查询失败: {e}"


__all__ = ["run"]
