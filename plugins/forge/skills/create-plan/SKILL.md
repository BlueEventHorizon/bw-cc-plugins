---
name: create-plan
description: |
  計画書作成ワークフロー。設計書からタスクを抽出し計画書を作成、または既存計画書を更新。
  トリガー: "計画書作成", "計画開始", "start planning", "/forge:create-plan"
user-invocable: true
argument-hint: "<feature>"
allowed-tools: Bash, Read, AskUserQuestion
---

# /forge:create-plan

計画書を作成するワークフローを起動する。

## Step 1: Feature 選択 [MANDATORY]

対象 Feature: **$ARGUMENTS**

引数が指定されていない場合:
1. `specs/` ディレクトリ内の Feature 一覧を確認: `ls -d specs/*/`
2. ユーザーに対象 Feature を質問

## Step 2: モード判定 [MANDATORY]

`specs/{feature}/plan/{feature}_plan.md` を確認し、モードを決定:

| 状況 | モード |
|------|--------|
| 計画書が存在しない | **新規作成モード**: ワークフローに従って計画書を作成 |
| 計画書が存在する | **更新モード**: 既存計画書にタスクを追加・修正 |

## Step 3: ワークフロー文書の特定 [MANDATORY]

以下の優先順位でワークフロー文書を特定する:

1. `/query-rules` で「計画書作成ワークフロー」「planning workflow」に関連するルール文書を取得
   - 取得できた場合: そのワークフロー文書に従って実行
2. フォールバック: `${CLAUDE_PLUGIN_ROOT}/defaults/planning_workflow.md` を使用

**Skill 失敗時**: エラー内容をユーザーに報告し、フォールバックの使用を提案する。

## Step 4: ワークフロー実行

Step 3 で特定したワークフロー文書を読み込み、その指示に従って実行する。
