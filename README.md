# 上下水道 管路台帳のデータ整備・分析ツール集

上下水道の管路台帳 GIS を実務で扱う立場から、台帳データの整備・検査・分析を
Python(geopandas)で自動化するツールとデモをまとめたリポジトリです。

| ツール | 内容 |
|---|---|
| [work1-ledger-cleanup](work1-ledger-cleanup/) | 台帳レイヤの品質検査ツール(SonicWeb 系エクスポートの属性辞書抽出+一括 QA レポート) |
| [work2-ledger-checker](work2-ledger-checker/) | 台帳 × 現地調査の突合チェック・Excel 調書自動生成(全合成データ) |
| [work3-deterioration](work3-deterioration/) | 下水道管渠の劣化リスク評価・点検優先度スクリーニング(手法デモ) |
| [work4-urgency](work4-urgency/) | TV カメラ調査結果からの緊急度判定(判定基準は JSON プロファイル・調査データは全合成) |

解説記事(Qiita):

1. [下水道管路のオープンデータで劣化リスク評価・点検優先度マップを作ってみた(Python/geopandas)](https://qiita.com/shirube-lab/items/303367cfc87f2772871a)
2. [下水道管路の劣化リスク評価に「地形の目」を足す — J-SHIS 微地形区分と海岸線距離(Python/geopandas)](https://qiita.com/shirube-lab/items/c0e3a133b996a1971200)

## データについての宣言

- 主データは **半田市オープンデータ「水道管路等データ」(CC-BY 4.0)** です。
  https://www.city.handa.lg.jp/opendata/1005557/1005561/1010384.html
- 環境特徴量として **防災科研 J-SHIS「地形・地盤分類 250m メッシュマップ
  (2020 年更新版)」**(出典明示で利用可)と **国土数値情報「行政区域データ
  N03」**(CC BY 4.0)を使用しています(詳細: [data/env/README.md](data/env/README.md))。
- **勤務先・顧客に由来するデータは一切使用していません。**
- work2 のデータは全て合成(座標も架空の配置で、実在の管路とは無関係)です。
- work3 の機械学習パートの点検ラベルは**合成**です(実点検データは公開されて
  いないため)。手法デモであり、半田市の実際の管路状態の評価・更新計画を
  示すものではありません。
- work4 の調査データ(不良の記録)も**全て合成**です。管路の位置のみ半田市の
  オープンデータを用いており、実際の管渠の状態評価ではありません。

## 変更履歴

[CHANGELOG.md](CHANGELOG.md) を参照してください。

## ライセンス

- コード: MIT License([LICENSE](LICENSE))
- データ(data/ 以下および加工成果物): 半田市「水道管路等データ」CC-BY 4.0 に
  基づく(コードのライセンスとは別です)

## 実行環境・クイックスタート

Python 3.11 / geopandas / scikit-learn / folium / openpyxl / matplotlib

```bash
pip install geopandas scikit-learn folium openpyxl matplotlib

# 1. データ展開(初回のみ)
python data/handa/setup_data.py

# 2. 各作品の実行(詳細は各 README)
python work1-ledger-cleanup/parse_s2a_fields.py
python work1-ledger-cleanup/ledger_qa.py
python work2-ledger-checker/generate_sample_data.py
python work2-ledger-checker/ledger_checker.py
python work3-deterioration/prepare_data.py
python work3-deterioration/score_priority.py
python work3-deterioration/future_wave.py
python work4-urgency/generate_survey_data.py   # work3 の出力が必要
python work4-urgency/judge_urgency.py
```
