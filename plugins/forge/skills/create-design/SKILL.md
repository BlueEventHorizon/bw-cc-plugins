---
name: create-design
description: |
  設計書作成ワークフロー。要件定義書から設計書を作成、または既存設計書をレビュー。
  トリガー: "設計書作成", "設計開始", "start design", "/forge:create-design"
user-invocable: true
argument-hint: "<feature>"
allowed-tools: Bash, Read, AskUserQuestion
---

# /forge:create-design

設計書を作成するワークフローを起動する。

## Step 1: Feature 選択 [MANDATORY]

対象 Feature: **$ARGUMENTS**

引数が指定されていない場合:
1. `specs/` ディレクトリ内の Feature 一覧を確認: `ls -d specs/*/`
2. ユーザーに対象 Feature を質問

## Step 2: モード判定 [MANDATORY]

`specs/{feature}/design/` ディレクトリを確認し、モードを決定:

| 状況 | モード |
|------|--------|
| 設計書が存在しない | **新規作成モード**: ワークフローに従って設計書を作成 |
| 設計書が存在する | **レビューモード**: `/forge:review design` で既存設計書をレビューし改善提案を出す |

## Step 3: ワークフロー文書の特定 [MANDATORY]

以下の優先順位でワークフロー文書を特定する:

1. `/query-rules` で「設計書作成ワークフロー」「design workflow」に関連するルール文書を取得
   - 取得できた場合: そのワークフロー文書に従って実行
2. フォールバック: `${CLAUDE_PLUGIN_ROOT}/defaults/design_workflow.md` を使用

**Skill 失敗時**: エラー内容をユーザーに報告し、フォールバックの使用を提案する。

## Step 4: ワークフロー実行

Step 3 で特定したワークフロー文書を読み込み、その指示に従って実行する。
