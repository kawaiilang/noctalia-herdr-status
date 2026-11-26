# noctalia-herdr-status

[English](README.md) | 日本語

[Herdr](https://herdr.dev) TUI セッションのエージェント／シェルペイン状態を読み取り専用で監視し、クリックで対象ペインと端末ウィンドウへフォーカス移動できる [Noctalia](https://github.com/noctalia-dev/noctalia) 向けプラグインと Python ヘルパーです。

## 特徴

- **プライバシーに配慮した状態表示**: Herdr の UNIX ソケット（`session.snapshot`）からペイン ID・表示名・エージェント状態（`blocked` / `working` / `done` / `idle` / `unknown` / `shell`）・ワークスペース／タブラベル・ディレクトリの末尾名のみを取り出します。フルパスや端末タイトル、プロンプト内容は出力しません。
- **ワンクリックで対象ペインへ移動**: パネル上の項目をクリックすると、Herdr 側のペイン切替（`pane.focus`）と端末ウィンドウの前面フォーカスをまとめて実行します。
- **コンポジタ対応**: ウィンドウ検索・フォーカスは現在 [Umbriel](https://github.com/noctalia-dev/umbriel) Wayland コンポジタに対応しています。コンポジタ操作は `src/noctalia_herdr_status/compositor.py` にバックエンド分離してあるため、将来的に他コンポジタ対応も追加しやすい構造です。
- **多言語対応**: 日本語・英語の UI 翻訳（`plugin/translations/`）を同梱しています。

## 導入方法（Nix / Home Manager）

flake 入力に追加します:

```nix
{
  inputs = {
    noctalia-herdr-status = {
      url = "github:kawaiilang/noctalia-herdr-status";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };
}
```

Home Manager モジュールを読み込んで有効化します:

```nix
{ inputs, osConfig, ... }:
{
  imports = [ inputs.noctalia-herdr-status.homeModules.default ];

  programs.noctaliaHerdrStatus = {
    enable = true;
    umbrielPackage = osConfig.programs.umbriel.package;
  };
}
```

バー上の並び順はモジュール側では変更しないため、各自の Noctalia バー設定のウィジェット一覧に `"herdr-status"` を追加してください。

プラグイン ID は `kawaiilang/herdr-status`、ウィジェット種別は `kawaiilang/herdr-status:bar` です。

## 環境変数

- `HERDR_SOCKET_PATH`: Herdr API ソケットの明示パス。
- `HERDR_SESSION`: 名前付き Herdr セッション（`$XDG_CONFIG_HOME/herdr/sessions/<name>/herdr.sock`）。
- `HERDR_WINDOW_APP_ID`: 複数の端末ウィンドウを絞り込む際の任意の `app_id` フィルタ。

## 開発・テスト

リポジトリのルートで開発シェルに入ると、Python・Luau と lint ツールを使えます。たとえば、編集したプラグインファイルをコンパイルできます。

```bash
nix develop
luau-compile --null plugin/service.luau
```

Nix ファイルを整形し、Python・Luau のテスト、Ruff、Pyright、Nix の静的解析をまとめて実行します。

```bash
nix fmt
nix flake check
```

Luau だけを検証するには、プラグインをビルドします。`service`・`widget`・`panel` をコンパイルし、それぞれのテストを Noctalia API のモックで実行します。

```bash
nix build --no-link --print-build-logs .#plugin
```

Python テスト単体の実行:

```bash
PYTHONPATH=src:tests python3 -m unittest discover -s tests -v
```

## ライセンス

MIT（[LICENSE](LICENSE)）
