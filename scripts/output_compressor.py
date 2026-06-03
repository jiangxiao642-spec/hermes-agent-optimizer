#!/usr/bin/env python3
"""
output_compressor — 压缩工具输出再喂 LLM。
灵感：chopratejas/headroom（60-95% token 节省）。
不依赖 Rust/PyO3，纯 Python 正则 + 规则。

用法：
  cat big_output.txt | python3 output_compressor.py
  python3 output_compressor.py file.txt
"""

import sys, re

RULES = [
    # 1. 去时间戳日志行
    (r'^\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*\]?\s*(INFO|DEBUG|WARN|WARNING|NOTICE|TRACE)\s*:?\s*', ''),
    # 2. 去空行（保留最多1个连续空行）
    (r'\n{3,}', '\n\n'),
    # 3. 去 pip/npm 进度条行
    (r'^\s*(Downloading|Collecting|Installing|Uninstalling|Found|Using cached|Requirement already|Attempting|Building|Created wheel).*$', ''),
    # 4. 去 curl/wget 下载进度
    (r'^\s*\d{1,3}%\s.*$', ''),
    (r'^\s*[│├└━╸╰].*\n', ''),
    # 5. 缩进去重：连续相同前缀的行只保留第一行
    # 6. HTTP header 行
    (r'^<\s*(HTTP\/|Server:|Date:|Content-Type:|Content-Length:|Connection:|Cache-Control:|X-|Set-Cookie:).*$', ''),
    # 7. 去 "  " 多余空格
    (r'  +', ' '),
]

def compress(text: str) -> dict:
    original_len = len(text)
    compressed = text
    
    for pattern, replacement in RULES:
        compressed = re.sub(pattern, replacement, compressed, flags=re.MULTILINE)
    
    # 去首尾空行
    compressed = compressed.strip()
    
    compressed_len = len(compressed)
    savings = (1 - compressed_len / max(original_len, 1)) * 100
    
    return {
        "original_chars": original_len,
        "compressed_chars": compressed_len,
        "savings_pct": round(savings, 1),
        "text": compressed
    }

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
        print("output_compressor — 压缩工具输出。用法: cat log.txt | output_compressor.py")
        sys.exit(0)
    
    if len(sys.argv) > 1:
        text = open(sys.argv[1]).read()
    else:
        text = sys.stdin.read()
    
    result = compress(text)
    print(result["text"])
    print(f"\n[压缩: {result['original_chars']}→{result['compressed_chars']} 字符, -{result['savings_pct']}%]", file=sys.stderr)
