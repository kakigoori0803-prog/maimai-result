# maimai-result

iOSショートカットで maimai DX NET のプレイ履歴を取得し、  
FastAPI サーバーに送信して保存・閲覧するプロジェクトです。

## 構成
- FastAPI (Python)
- Renderでデプロイ
- iOSショートカットでデータ送信

## エンドポイント
- `/health` : 動作確認用 ({"ok": true})
- `/ingest` : JSONデータ受け取り (ショートカットからPOST)
- `/data`   : 保存されたデータ一覧を返す
