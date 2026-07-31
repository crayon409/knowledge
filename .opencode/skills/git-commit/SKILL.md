---
name: git-commit
description: 当需要将当前修改提交到 Git 仓库并推送到远程时使用此技能
allowed-tools: Bash
---

# Git 提交流程技能

## 使用场景

当工作区有未提交的修改，需要将其保存、同步远程更新、提交并推送到远程仓库时使用此技能。

## 执行步骤

### 1. 暂存当前修改

```bash
git stash push -m "auto-stash-before-commit"
```

将当前工作区的所有修改暂存，以便拉取远程更新时不会冲突。

如果 `git stash` 失败（如工作区无修改），**跳过此步骤**，直接进入步骤 2。

### 2. 拉取远程更新

```bash
git pull --rebase
```

### 3. 恢复暂存修改

如果步骤 1 执行了 stash，恢复：

```bash
git stash pop
```

### 4. 处理冲突

如果步骤 3 出现冲突，按以下流程解决：

1. 查看冲突文件：`git diff --name-only --diff-filter=U`
2. 逐个打开冲突文件，手动合并冲突标记（`<<<<<<<` / `=======` / `>>>>>>>`）
3. 合并原则：保留两个版本的**有意义内容**，删除冲突标记
4. 标记冲突已解决：`git add <冲突文件>`

如果步骤 2（pull）出现冲突，同样按上述流程处理。

### 5. 暂存所有修改

```bash
git add -A
```

提交前确认 `git status` 无遗漏。

### 6. 提交

```bash
git commit -m "<描述性提交信息>"
```

提交信息要求：
- 使用中文简述改了什么
- 如果是功能新增，使用 `feat: ` 前缀
- 如果是问题修复，使用 `fix: ` 前缀

### 7. 推送到远程

```bash
git push
```

## 完整流程示例

```bash
# Step 1: stash current changes
git stash push -m "auto-stash-before-commit" 2>/dev/null || echo "nothing to stash"

# Step 2: pull latest
git pull --rebase

# Step 3: restore stashed changes
git stash pop 2>/dev/null || echo "no stash to pop"

# Step 4: if conflict, resolve manually, then git add

# Step 5: stage all
git add -A

# Step 6: commit
git commit -m "feat: add daily collect workflow and articles"

# Step 7: push
git push
```

## 注意事项

- 执行前先检查 `git status`，确认要提交的内容
- 如果 stash pop 后出现冲突，优先与用户沟通解决策略
- 不提交包含密钥、Token 等敏感信息的文件
- 不执行 `git push --force`（违反 AGENTS.md 红线）
- 不修改 `git config` 或 remote URL（违反 AGENTS.md 红线）
- 如果没有未暂存或未跟踪的修改，直接告知用户无需提交
