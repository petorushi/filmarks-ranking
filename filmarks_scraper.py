# 【最終確定版：requests + Jinja2】js-cassetteをターゲットにしてIDを確実に取得 (vodパラメーターなし)
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time 
import json 
from jinja2 import Template
from urllib.parse import urljoin 

# --- 設定 ---
TOTAL_PAGES = 1 # 確定まで1ページに設定
BASE_DOMAIN = "https://filmarks.com" 
# --- /設定 ---

# HTTPリクエストのヘッダー情報
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# 収集したいページのURL
base_url = f"{BASE_DOMAIN}/list/vod/prime_video?page={{}}"
movie_data = []

print("スクレイピングを開始します...")

for page in range(1, TOTAL_PAGES + 1):
    url = base_url.format(page)
    print(f"{page}ページ目を収集中...: {url}")
    
    time.sleep(1) 
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"警告: {page}ページ目の取得に失敗しました。ステータスコード: {response.status_code}")
            continue
    except requests.exceptions.RequestException as e:
        print(f"エラー: {page}ページ目のアクセスで問題が発生しました: {e}")
        continue

    soup = BeautifulSoup(response.content, 'html.parser')

    # js-cassetteクラスを持つ要素を映画ブロックとして取得する
    movies = soup.select('div.js-cassette') 
    
    if not movies:
        if page == 1:
             print("【エラー】1ページ目に映画が見つかりませんでした。サイトのHTML構造が変更されている可能性があります。")
        else:
            print(f"{page}ページ目に映画が見つかりませんでした。データは最後まで到達したようです。処理を終了します。")
        break 

    for movie in movies:
        try:
            # 実際の情報コンテナはjs-cassetteの子要素である 'div.p-content-cassette' にある
            content_cassette = movie.select_one('div.p-content-cassette')
            if not content_cassette:
                continue

            # === 必須情報の抽出 (タイトル、評価) ===
            title_element = content_cassette.select_one('.p-content-cassette__title')
            score_element = content_cassette.select_one('.c-rating__score')
            
            if not (title_element and score_element):
                continue

            title = title_element.text.strip()
            score_text = score_element.text.strip()

            try:
                score = float(score_text)
            except ValueError:
                continue

            # === 詳細URLの抽出 (js-cassette自身からdata-clip属性を取得) ===
            detail_url = "#"
            movie_id = None
            
            data_clip_str = movie.get('data-clip') # js-cassetteはdata-clip属性を持っている
            
            if data_clip_str:
                try:
                    cleaned_data_clip_str = data_clip_str.replace("'", '"')
                    data_clip = json.loads(cleaned_data_clip_str)
                    movie_id = data_clip.get('movie_id')
                    
                    if movie_id:
                        # ★★★ 変更点: vodパラメーターを削除 ★★★
                        detail_url = f"{BASE_DOMAIN}/movies/{movie_id}" 
                except json.JSONDecodeError:
                    pass
                except Exception:
                    pass

            # === オプション情報の抽出 ===
            
            # ポスターURL抽出
            poster_url = None
            try:
                poster_element = content_cassette.select_one('div.p-content-cassette__jacket img') 
                if poster_element:
                    poster_url = poster_element.get('data-src') or poster_element.get('src')
            except Exception:
                pass

            # 上映日情報の抽出
            release_date = "上映日：N/A"
            try:
                # content_cassetteの子要素に対してセレクタを適用
                release_date_element = content_cassette.select_one('.p-content-cassette__other-info-title:contains("上映日：") + span')
                if release_date_element:
                    release_date = f"上映日：{release_date_element.text.strip()}"
            except Exception:
                 pass

            # ジャンル情報の抽出
            genres_info = "ジャンル：N/A"
            try:
                # content_cassetteの子要素に対してセレクタを適用
                genre_elements = content_cassette.select('.p-content-cassette__other-info.genres_and_distributor .genres a')
                genres = ', '.join([g.text.strip() for g in genre_elements])
                if genres:
                    genres_info = f"ジャンル：{genres}"
            except Exception:
                pass 

            # データに追加
            movie_data.append({
                'タイトル': title, 
                '評価': score, 
                '画像URL': poster_url,
                '上映日': release_date,
                'ジャンル': genres_info, 
                '詳細URL': detail_url 
            })
                    
        except Exception:
             # 個別の映画の抽出で予期せぬエラーが出ても、ループは継続
             pass

# 収集したデータをDataFrameに変換
df = pd.DataFrame(movie_data)

# --- HTML生成と出力 ---
if df.empty:
    print("収集できたデータがありませんでした。")
else:
    ranking_df = df.sort_values(by='評価', ascending=False).reset_index(drop=True)
    ranking_df.index = ranking_df.index + 1
    ranking_df.index.name = '順位'
    
    print("\nHTMLファイルを生成しています...")
    
    html_template = Template("""
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>Filmarks VODランキング (最終版)</title>
    <style>
        /* スタイルは変更なし */
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; padding: 20px; }
        .container { max-width: 900px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }
        h1 { color: #0088cc; border-bottom: 3px solid #0088cc; padding-bottom: 10px; margin-bottom: 30px; text-align: center; }
        .movie-item { display: flex; align-items: center; padding: 15px; border-bottom: 1px dashed #eee; transition: background-color 0.3s; }
        .movie-item:hover { background-color: #fcfcfc; }
        .rank { font-size: 2.5em; font-weight: bold; width: 80px; text-align: center; color: #aaa; flex-shrink: 0; margin-right: 10px; }
        .rank.top3 { color: #ffbf00; } 
        .rank.top10 { color: #0088cc; } 
        .poster { width: 70px; height: 100px; margin-right: 20px; flex-shrink: 0; }
        .poster img { width: 100%; height: 100%; object-fit: cover; border-radius: 4px; box-shadow: 0 2px 5px rgba(0, 0, 0, 0.15); }
        .info { flex-grow: 1; }
        .title a { font-size: 1.2em; font-weight: 600; color: #333; text-decoration: none; }
        .title a:hover { color: #0088cc; text-decoration: underline; }
        .release-date, .genre-info { font-size: 0.85em; color: #777; margin-bottom: 5px; line-height: 1.4; }
        .score { font-size: 1.1em; font-weight: bold; color: #666; }
        .score-bar { height: 10px; background-color: #e0e0e0; border-radius: 5px; margin-top: 5px; width: 100%; max-width: 200px; }
        .score-fill { height: 100%; border-radius: 5px; background-color: #ffaa00; transition: width 0.5s; }
        .rating-highlight { background-color: #fff9e6; border-left: 5px solid #ffcc33; padding-left: 10px; }
        .rating-highlight .score { color: #ffaa00; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Amazon Prime Video 映画ランキング</h1>
        {% for index, row in data.iterrows() %}
        {% set rank = loop.index %}
        {% set score = row['評価'] %}
        {% set is_highlight = score >= 4.0 %}
        {% set rank_class = 'top3' if rank <= 3 else ('top10' if rank <= 10 else '') %}
        
        <div class="movie-item {% if is_highlight %}rating-highlight{% endif %}">
            <div class="rank {{ rank_class }}">#{{ rank }}</div>
            <div class="poster">
                {% if row['画像URL'] %}
                <img src="{{ row['画像URL'] }}" alt="{{ row['タイトル'] }} ポスター">
                {% else %}
                <div style="width: 100%; height: 100%; background: #ccc; display: flex; align-items: center; justify-content: center; font-size: 0.8em; text-align: center;">No Image</div>
                {% endif %}
            </div>
            <div class="info">
                <div class="title">
                    {% if row['詳細URL'] != '#' %}
                    <a href="{{ row['詳細URL'] }}" target="_blank">{{ row['タイトル'] }}</a>
                    {% else %}
                    {{ row['タイトル'] }}
                    {% endif %}
                </div>
                <div class="genre-info">{{ row['ジャンル'] }}</div>
                <div class="release-date">{{ row['上映日'] }}</div>
                <div class="score">★{{ score | round(1) }} / 5.0</div>
                <div class="score-bar">
                    <div class="score-fill" style="width: {{ (score / 5.0 * 100) | round(0) }}%;"></div>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</body>
</html>
""")

    # データをHTMLテンプレートに渡してレンダリング
    html_output = html_template.render(data=ranking_df)

    # HTMLファイルを保存
    html_file_path = 'filmarks_ranking_styled.html'
    try:
        with open(html_file_path, 'w', encoding='utf-8') as f:
            f.write(html_output)
        print(f"\n✨ スタイル付きのウェブページが '{html_file_path}' に保存されました。")
    except Exception as e:
        print(f"\nHTMLファイルの保存に失敗しました: {e}")