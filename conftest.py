"""项目根 conftest：把项目根显式放进 `sys.path`。

## 为什么需要
`tests/` 里用 `from quant import ...` 引用自建包。原先能通过，**只是因为**
用 `python -m pytest` 调用时当前目录（= 项目根）恰好进了 `sys.path`。
换成裸 `pytest`、或在别的目录里调用，`tests/` 会被插到 `sys.path[0]` 而**项目根不在**，
于是报 `No module named 'quant'` —— 这是**环境依赖型偶发失败**，最难排查的一类。

⇒ 这里显式声明依赖，让测试**与被调用方式无关**。

（生命周期豁免：pytest 配置，不是脚本。）
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_cache_dir = _ROOT / ".cache" / "pycache"
_cache_dir.mkdir(parents=True, exist_ok=True)
sys.pycache_prefix = str(_cache_dir)
