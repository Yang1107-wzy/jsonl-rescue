# JSONL Rescue · 可恢复的数据整理工具

[English](README.md) · [发布包](https://github.com/Yang1107-wzy/jsonl-rescue/releases)

为训练、评测、日志数据提供流式 JSONL 对象检查和去重。合法记录输出到新文件，拒收记录以原始字节归档；原文件保持不变。输入支持 JSONL 和 `.gz`。

![真实示例输出的排版展示](docs/demo.svg)

## 安装

Python 3.10+，没有运行时第三方依赖。当前通过 GitHub 发布，未发布到 PyPI。

```sh
python -m pip install "git+https://github.com/Yang1107-wzy/jsonl-rescue.git@v1.0.0"
jsonl-rescue --version
```

## 快速体验

```sh
git clone https://github.com/Yang1107-wzy/jsonl-rescue.git
cd jsonl-rescue
python -m pip install .
jsonl-rescue scan examples/messy.jsonl --required id --required text --dedupe
jsonl-rescue clean examples/messy.jsonl --required id --required text --dedupe --output clean.jsonl --rejects rejected.jsonl
```

示例共 6 行：接受 2 行、拒收 4 行，其中重复 1 行。扫描返回 1；成功完成整理返回 0。再次运行时请选择新的输出文件名，已有文件不会被覆盖。

## 检查与去重

- UTF-8、JSON 语法、空行、BOM、重复 JSON 属性名、非有限数字。
- 每行必须是 JSON 对象；数组与标量不符合本工具的数据集约定。
- `--required KEY` 检查顶层字段存在，可重复使用；不校验字段值和类型。
- `--dedupe` 启用基于排序键紧凑 JSON 的 SHA-256 去重，以临时 SQLite 保存指纹。
- 小数使用 Decimal 解析和精确保值序列化，避免 `1e-400` 变成零或高精度数据被错误合并。

去重忽略对象键顺序和空白，保留数组顺序；不是近似或语义去重。`1` 与 `1.0` 序列化不同，小数的指数写法可能规范化。理论上存在哈希碰撞。重复项指向第一条被接受的记录。

## 拒收记录可恢复

拒收文件的每行包含 `line`、`code`、`raw_base64`；重复项还包含 `first_line`。`raw_base64` 保存原始行的完整字节，包括换行符和不合法 UTF-8。

```python
import base64
import json

with open("rejected.jsonl", encoding="utf-8") as archive:
    for line in archive:
        item = json.loads(line)
        original_bytes = base64.b64decode(item["raw_base64"])
```

接受记录会被规范化为紧凑、排序键 JSON。若需要全部原始格式与顺序，使用保留的源文件。拒收档案含原始内容，隐私等级与输入相同。

## 自动化

```sh
jsonl-rescue scan data.jsonl --dedupe --format json --max-issues 20
```

报告包含总行数、接受数、拒收数、重复数、问题分类计数和问题样本。`--max-issues` 只限制报告的细节样本，所有行仍被检查，整理时每条拒收记录仍完整归档。恒有 `total = accepted + rejected`，重复数是拒收数的子集。

| 退出码 | 含义 |
| --- | --- |
| 0 | 扫描无拒收，或整理成功完成 |
| 1 | 扫描发现拒收记录 |
| 2 | 用法、文件或处理失败 |

## 资源与文件保护

输入、干净输出、拒收文件必须是不同路径；拒绝已有输出与符号链接，以独占方式创建新文件。通常异常发生后删除本次新建的输出；进程强制结束或断电仍可能留下部分文件。

内存主要随单条记录、有限报告样本、SQLite 缓存增长；超大单行仍会消耗内存。去重需要与唯一记录数成比例的临时磁盘。不支持 gzip 输出、stdin、自动修复语法、字段类型转换。空文件是有效的零行输入。

遵循 [JSON Lines 格式](https://jsonlines.org/)，另加对象记录限制；结构检查通过不表示符合某家微调 API 或数据质量标准。MIT 许可，提供跨平台 CI 和合成示例。
