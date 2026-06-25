# Adapter MVP 文档与注释维护计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全 `app/` 内部所有缺失的方法/类注释，并把对外文档收口成可直接使用的使用手册、架构设计、部署与配置说明。

**Architecture:** 先用脚本化方式批量补齐代码注释，避免手工漏项；再基于现有 README 和 `delivery/docs/` 中的说明，重写成面向落地的三份主文档，最后用 README 作为入口索引。整个过程保持现有行为不变，只整理表达和文档结构。

**Tech Stack:** Python 3, FastAPI, unittest, Markdown

---

### Task 1: 盘点并补齐 `app/` 注释

**Files:**
- Modify: `app/*.py`
- Test: `tests/*.py`

- [ ] **Step 1: 统计所有缺失 docstring 的类和函数**

```bash
python3 - <<'PY'
import ast, pathlib
root = pathlib.Path('app')
for path in sorted(root.rglob('*.py')):
    tree = ast.parse(path.read_text())
    missing = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and ast.get_docstring(node) is None:
            missing.append(node.name)
    if missing:
        print(path, len(missing))
PY
```

- [ ] **Step 2: 批量补入中文 docstring**

```python
"""示例：在缺失 docstring 的函数或类首行插入简短中文说明。"""
```

- [ ] **Step 3: 运行语法与单测验证**

```bash
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

### Task 2: 重写使用手册

**Files:**
- Create: `delivery/docs/使用手册.md`
- Modify: `README.md`

- [ ] **Step 1: 从现有说明里整理主流程**

```markdown
钉钉需求 -> 创建 workflow -> 读取需求 -> 解析 -> 创建云效任务 -> 编码 -> 流水线 -> Apifox -> 关单
```

- [ ] **Step 2: 写出可直接操作的使用说明**

```markdown
1. 准备链接
2. 创建 workflow
3. 调试读取
4. 跑通任务创建与关单
```

- [ ] **Step 3: 将 README 收口成入口页**

```markdown
- 使用手册
- 架构设计
- 部署与配置
```

### Task 3: 重写架构设计与部署配置

**Files:**
- Create: `delivery/docs/架构设计.md`
- Create: `delivery/docs/部署与配置.md`
- Create: `delivery/docs/文档索引.md`

- [ ] **Step 1: 写出系统架构和模块边界**

```markdown
Adapter、workflow、云效、Apifox、钉钉、审计与配置表
```

- [ ] **Step 2: 写出部署和配置说明**

```markdown
本地启动、远端部署、数据库、环境变量、脚本、常见校验
```

- [ ] **Step 3: 写出文档索引**

```markdown
入口、主流程、调研、配置、任务文档之间的关系
```

- [ ] **Step 4: 运行文档自查**

```bash
python3 - <<'PY'
from pathlib import Path
for p in [Path('README.md'), Path('delivery/docs/使用手册.md'), Path('delivery/docs/架构设计.md'), Path('delivery/docs/部署与配置.md')]:
    print(p, p.exists(), p.stat().st_size if p.exists() else 0)
PY
```
