from __future__ import annotations

from typing import Any


RULES: list[tuple[str, str, str, list[str]]] = [
    (
        "test_failure",
        "high",
        "单元测试或集成测试失败",
        ["test failures", "there are test failures", "surefire", "assertionerror", "failed tests"],
    ),
    (
        "compile_error",
        "high",
        "编译失败",
        ["compilation failure", "failed to execute goal", "maven-compiler-plugin", "cannot find symbol"],
    ),
    (
        "dependency_error",
        "high",
        "依赖解析失败",
        ["could not resolve dependencies", "dependencyresolutionexception", "non-resolvable parent pom"],
    ),
    (
        "adapter_execute_failed",
        "high",
        "Adapter 执行失败",
        ["adapter release execute", "ssh connectivity check failed", "permission denied", "connection timed out"],
    ),
    (
        "quality_gate_failed",
        "medium",
        "质量门禁失败",
        ["checkstyle", "pmd", "spotbugs", "sonarqube", "quality gate"],
    ),
]


def analyze_pipeline_failure(log_tail: str, stage_name: str) -> dict[str, Any]:
    normalized = (log_tail or "").lower()
    for category, confidence, summary, keywords in RULES:
        matched = [keyword for keyword in keywords if keyword in normalized]
        if matched:
            return {
                "category": category,
                "confidence": confidence,
                "summary": f"{stage_name}：{summary}",
                "evidence": matched[:5],
                "suggestion": _suggestions(category),
                "shouldBlockRelease": True,
            }
    return {
        "category": "unknown",
        "confidence": "low",
        "summary": f"{stage_name}：流水线失败，暂未命中内置规则",
        "evidence": _last_non_empty_lines(log_tail, 5),
        "suggestion": [
            "打开云效完整日志，定位首个失败堆栈或非零退出命令",
            "补充该错误特征到 CI/CD Agent 规则库",
            "必要时由人工复核后再重新触发流水线",
        ],
        "shouldBlockRelease": True,
    }


def _suggestions(category: str) -> list[str]:
    mapping = {
        "compile_error": [
            "本地执行相同编译命令复现",
            "检查最近提交是否缺少类、方法、import 或模块依赖",
            "优先修复首个编译错误，再重新触发 CI",
        ],
        "test_failure": [
            "查看失败测试用例名称和断言信息",
            "确认是业务逻辑变更、测试数据问题还是环境依赖问题",
            "修复后本地执行对应测试类再提交",
        ],
        "dependency_error": [
            "检查 Maven 仓库、父 POM、版本号和私服权限",
            "确认依赖是否已发布到可访问仓库",
            "避免在 Release 阶段临时跳过依赖问题",
        ],
        "adapter_execute_failed": [
            "检查目标主机网络、账号、白名单和 Adapter 审计记录",
            "确认人工审批号和 TASK_ID 是否一致",
            "失败未排除前不要推进云效任务完成状态",
        ],
        "quality_gate_failed": [
            "根据质量工具输出修复高优先级问题",
            "确认规则是否为本仓库基线规则",
            "通过质量门禁后再进入 Release",
        ],
    }
    return mapping.get(category, ["查看完整日志并人工复核"])


def _last_non_empty_lines(text: str, limit: int) -> list[str]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-limit:]
