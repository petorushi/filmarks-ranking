# 【最終確定版：複数ジャンルOR検索対応、指定ジャンル限定、サイト文言保持】
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time 
import json 
from jinja2 import Template
from urllib.parse import urljoin 
import sys 

# 標準出力をUTF-8に設定
sys.stdout.reconfigure(encoding='utf-8') 

# --- 設定 ---
TOTAL_PAGES = 10 
BASE_DOMAIN = "https://filmarks.com" 

# スクレピング対象のVODランキングURLリスト
VOD_URLS = {
    "Amazon": "/list/vod/prime_video?page={}",
    "Netflix": "/list/vod/netflix?page={}"
}

# ★★★ フィルタリングに使用するジャンルの定義と名称マッピング ★★★
# KEY: Filmarksから取得される可能性のある生データ
# VALUE: フィルタリングボタンに使用する名称 (指定された7つに限定)
TARGET_GENRES_MAP = {
    "SF": "SF",
    "アクション": "アクション",
    "アドベンチャー": "冒険",
    "冒険": "冒険",
    "アドベンチャー・冒険": "冒険", # Filmarksの表記を「冒険」にマッピング
    "クライム": "クライム",
    "ファミリー": "ファミリー",
    "ファンタジー": "ファンタジー",
    "アニメ": "アニメ",
    "アニメーション": "アニメ",
    # ★★★ 指定されていないジャンルはここで除外されます ★★★
}

# 最終的にウェブページに出力するジャンルボタンの名称リスト（重複なし、ソート済み）
# 意図しない重複を除外するためset()を使用し、指定された7ジャンルに合致するもののみ表示する
FINAL_GENRE_BUTTONS = sorted(list(set(TARGET_GENRES_MAP.values())))
# --- /設定 ---

# HTTPリクエストのヘッダー情報
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

movie_data_map = {}
all_processed_genres = set() # フィルタリング用の加工済みジャンル名（例: 冒険）を収集

print("スクレイピングを開始します...")

# VODサービスごとにループ
for vod_name_short, url_suffix in VOD_URLS.items(): 
    print(f"\n--- {vod_name_short} のデータを収集中 ---")
    
    for page in range(1, TOTAL_PAGES + 1):
        url = urljoin(BASE_DOMAIN, url_suffix.format(page))
        print(f"  {vod_name_short} {page}ページ目を収集中...: {url}")
        
        time.sleep(1) 
        
        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                print(f"  警告: {page}ページ目の取得に失敗しました。ステータスコード: {response.status_code}")
                continue
        except requests.exceptions.RequestException as e:
            print(f"  エラー: {page}ページ目のアクセスで問題が発生しました: {e}")
            continue

        soup = BeautifulSoup(response.content, 'html.parser')

        movies = soup.select('div.js-cassette') 
        
        if not movies and page == 1:
             print(f"  【エラー】{vod_name_short}の1ページ目に映画が見つかりませんでした。")
             break 
        elif not movies:
            print(f"  {vod_name_short}のデータは最後まで到達したようです。処理を終了します。")
            break 

        for movie in movies:
            try:
                content_cassette = movie.select_one('div.p-content-cassette')
                if not content_cassette:
                    continue

                # === 必須情報の抽出 (タイトル、評価、映画ID) ===
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

                detail_url = "#"
                movie_id = None
                
                data_clip_str = movie.get('data-clip')
                if data_clip_str:
                    try:
                        cleaned_data_clip_str = data_clip_str.replace("'", '"')
                        data_clip = json.loads(cleaned_data_clip_str)
                        movie_id = data_clip.get('movie_id')
                        
                        if movie_id:
                            detail_url = f"{BASE_DOMAIN}/movies/{movie_id}" 
                    except (json.JSONDecodeError, Exception):
                        pass

                if not movie_id:
                    continue

                # === オプション情報の抽出 (画像URL, 上映日) ===
                poster_url = None
                try:
                    poster_element = content_cassette.select_one('div.p-content-cassette__jacket img') 
                    if poster_element:
                        # 'data-src'または'src'から画像URLを取得
                        poster_url = poster_element.get('data-src') or poster_element.get('src')
                except Exception:
                    pass

                release_date = "上映日：N/A"
                try:
                    # Filmarksの構造に合わせたセレクタで上映日を取得
                    release_date_element = content_cassette.select_one('.p-content-cassette__other-info-title:-soup-contains("上映日：") + span')
                    if release_date_element:
                        release_date = f"上映日：{release_date_element.text.strip()}"
                except Exception:
                    pass 

                # === ジャンル情報の抽出と加工（ここが重要） ===
                raw_genres = [] # Filmarksのオリジナル文言
                processed_genres = set() # フィルタリング用の加工済みジャンル名（例: 冒険）
                genres_info = "ジャンル：N/A"
                try:
                    genre_elements = content_cassette.select('.p-content-cassette__other-info.genres_and_distributor .genres a')
                    raw_genres = [g.text.strip() for g in genre_elements]
                    
                    if raw_genres:
                        # フィルタリング対象ジャンルの加工と抽出
                        for g in raw_genres:
                            processed_g = TARGET_GENRES_MAP.get(g) # マッピングに基づいて加工
                            if processed_g:
                                processed_genres.add(processed_g) # 加工後のジャンル名をセットに追加
                        
                        # HTML表示用の文字列はFilmarksのオリジナル文言を使用
                        unique_raw_genres = list(set(raw_genres))
                        genres_info = f"ジャンル：{', '.join(unique_raw_genres)}"
                        
                        # 最終的なフィルタリング用ジャンルリストをセットに追加
                        all_processed_genres.update(processed_genres)
                except Exception:
                    pass 

                # データに追加（movie_idをキーとして使用し、重複を処理）
                if movie_id in movie_data_map:
                    if vod_name_short not in movie_data_map[movie_id]['vod_sources']:
                        movie_data_map[movie_id]['vod_sources'].append(vod_name_short)
                else:
                    movie_data_map[movie_id] = {
                        'タイトル': title, 
                        '評価': score, 
                        '画像URL': poster_url,
                        '上映日': release_date,
                        'ジャンル': genres_info, # Filmarksのオリジナル文言を使用
                        'ジャンルリスト': list(processed_genres), # フィルタリング用の加工済みジャンルリスト
                        '詳細URL': detail_url,
                        'vod_sources': [vod_name_short] 
                    }
                        
            except Exception:
                 pass


# 収集したデータをDataFrameに変換 (辞書の値を取り出す)
df = pd.DataFrame(list(movie_data_map.values()))

# 実際に収集されたジャンルのみに絞り、ソート
display_genres = sorted([g for g in FINAL_GENRE_BUTTONS if g in all_processed_genres])

# --- HTML生成と出力 ---
if df.empty:
    print("収集できたデータがありませんでした。")
else:
    # 評価の高い順にソートし、順位を振り直す
    ranking_df = df.sort_values(by='評価', ascending=False).reset_index(drop=True)
    ranking_df.index = ranking_df.index + 1
    ranking_df.index.name = '順位'
    
    print("\nHTMLファイルを生成しています...")
    
    # Jinja2テンプレート
    html_template = Template("""
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>Filmarks VODランキング (Prime Video & Netflix)</title>
    
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <style>
        /* デスクトップ/共通スタイル */
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; padding: 20px; }
        .container { max-width: 900px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }
        h1 { color: #0088cc; border-bottom: 3px solid #0088cc; padding-bottom: 10px; margin-bottom: 20px; text-align: center; }
        
        /* ★★★ ジャンルフィルターコンテナのスタイル ★★★ */
        .genre-filters {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            padding: 10px 0 30px 0;
            border-bottom: 1px solid #ddd;
            margin-bottom: 30px;
        }

        .genre-button {
            background-color: #f0f0f0;
            color: #555;
            border: 1px solid #ccc;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.9em;
            cursor: pointer;
            transition: background-color 0.2s, color 0.2s, border-color 0.2s;
            outline: none;
            user-select: none;
        }

        .genre-button.active {
            background-color: #0088cc;
            color: white;
            border-color: #0088cc;
        }
        /* ★★★ /ジャンルフィルターコンテナのスタイル ★★★ */


        .movie-item-link { 
            display: flex; 
            align-items: stretch; 
            padding: 15px; 
            border-bottom: 1px dashed #eee; 
            transition: background-color 0.3s; 
            text-decoration: none; 
            color: inherit; 
        }
        .movie-item-link:hover { 
            background-color: #fcfcfc; 
        }

        .movie-item {
             border-left: 5px solid transparent; 
             transition: all 0.3s ease-in-out;
        }
        .movie-item.hidden {
            display: none;
        }
        
        .rank { 
            font-size: 2.5em; 
            font-weight: bold; 
            width: 80px; 
            text-align: center; 
            color: #aaa; 
            flex-shrink: 0; 
            margin-right: 10px; 
            display: flex; 
            align-items: center; 
            justify-content: center;
        }
        .rank.top3 { color: #ffbf00; } 
        .rank.top10 { color: #0088cc; } 
        
        .content-wrap {
            display: flex;
            flex-grow: 1; 
            height: 100%; 
        }

        .poster { 
            width: 100px; 
            height: auto; 
            margin-right: 20px; 
            flex-shrink: 0; 
            flex-grow: 0; 
            display: flex;
        }
        .poster img { 
            width: 100%; 
            height: 100%; 
            object-fit: contain; 
            border-radius: 4px; 
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.15); 
        }
        
        .info { 
            flex-grow: 1; 
            display: flex; 
            flex-direction: column;
            justify-content: space-between; 
        }
        
        .title-and-badges { 
             display: flex;
             align-items: center;
        }
        .title { 
            font-size: 1.2em; 
            font-weight: 600; 
            color: #333; 
            margin-right: 10px; 
        }

        .movie-item-link:hover .title {
             color: #0088cc;
             text-decoration: underline;
        }
        
        .vod-badges {
            display: flex;
            gap: 5px; 
            margin-top: 5px; 
            margin-bottom: 5px; 
        }
        .vod-badge {
            font-size: 0.75em;
            font-weight: bold;
            padding: 2px 6px;
            border-radius: 4px;
            background: none; 
            border: 1px solid; 
            white-space: nowrap;
        }
        .vod-badge.Amazon {
            color: #0088cc; 
            border-color: #0088cc;
        }
        .vod-badge.Netflix {
            color: #e50914; 
            border-color: #e50914;
        }

        .release-date, .genre-info { font-size: 0.85em; color: #777; margin-bottom: 5px; line-height: 1.4; }
        
        .score-block {
             display: flex;
             flex-direction: column;
        }
        .score { 
            font-size: 1.3em; 
            font-weight: bold; 
            color: #666; 
        }

        .score-bar { height: 10px; background-color: #e0e0e0; border-radius: 5px; margin-top: 5px; width: 100%; max-width: 200px; }
        .score-fill { height: 100%; border-radius: 5px; background-color: #ffaa00; transition: width 0.5s; }
        
        .rating-highlight { 
            background-color: #fff9e6; 
            border-left: 5px solid #ffcc33; 
        }
        .rating-highlight .score { color: #ffaa00; font-weight: bold; }

        /* レスポンシブ対応 (画面幅600px以下で適用) */
        @media (max-width: 600px) {
            body { padding: 5px; }
            .container { padding: 10px; }
            h1 { font-size: 1.4em; margin-bottom: 15px; }
            
            .genre-filters {
                padding: 10px 0 20px 0;
                margin-bottom: 20px;
            }

            .movie-item-link { 
                flex-direction: column; 
                padding: 10px 5px;
            }
            
            .rank { 
                height: auto;
                align-items: flex-start; 
                justify-content: flex-start;
                font-size: 1.8em; 
                width: auto; 
                margin: 0 0 10px 0; 
                align-self: flex-start; 
            }
            
            .content-wrap {
                width: 100%; 
                height: auto;
                align-items: stretch;
            }

            .poster { 
                width: 80px; 
                height: auto; 
                margin-right: 10px; 
            }
            .poster img {
                object-fit: contain; 
            }
            
            .info { 
                height: 100%;
                justify-content: space-between; 
                min-width: 0; 
            }
            
            .title { font-size: 1.0em; }
            
            .title-and-badges { 
                 flex-direction: column; 
                 align-items: flex-start;
                 margin-bottom: 5px; 
            }
            .vod-badges {
                 margin-top: 5px;
                 margin-bottom: 5px;
            }

            .release-date, .genre-info { 
                font-size: 0.75em; 
                margin-bottom: 2px; 
                line-height: 1.2;
            }
            
            .score {
                 font-size: 1.1em; 
            }
            
            .score-bar { 
                max-width: 100%; 
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Prime Video & Netflix 統合ランキング</h1>
        
        <div class="genre-filters">
            {% for genre in display_genres %}
            <button class="genre-button" data-genre="{{ genre }}">{{ genre }}</button>
            {% endfor %}
        </div>
        {% for index, row in data.iterrows() %}
        {% set rank = loop.index %}
        {% set score = row['評価'] %}
        {% set is_highlight = score >= 4.0 %}
        {% set rank_class = 'top3' if rank <= 3 else ('top10' if rank <= 10 else '') %}
        
        <div class="movie-item {% if is_highlight %}rating-highlight{% endif %}" data-genres="{{ row['ジャンルリスト'] | join(',') }}">
            
            {% if row['詳細URL'] != '#' %}
            <a href="{{ row['詳細URL'] }}" target="_blank" class="movie-item-link">
            {% endif %}

                <div class="rank {{ rank_class }}">#{{ rank }}</div>
                
                <div class="content-wrap">
                    <div class="poster">
                        {% if row['画像URL'] %}
                        <img src="{{ row['画像URL'] }}" alt="{{ row['タイトル'] }} ポスター">
                        {% else %}
                        <div style="width: 100%; height: 100%; background: #ccc; display: flex; align-items: center; justify-content: center; font-size: 0.8em; text-align: center;">No Image</div>
                        {% endif %}
                    </div>
                    <div class="info">
                        
                        <div>
                            <div class="title-and-badges">
                                <div class="title">
                                    {{ row['タイトル'] }}
                                </div>
                            </div>
                            <div class="genre-info">{{ row['ジャンル'] }}</div>
                            <div class="release-date">{{ row['上映日'] }}</div>
                        </div>
                        
                        <div class="score-block">
                            <div class="vod-badges">
                                {% for vod in row['vod_sources'] %}
                                <span class="vod-badge {{ vod }}">{{ vod }}</span>
                                {% endfor %}
                            </div>

                            <div class="score">★{{ score | round(1) }}</div>
                            <div class="score-bar">
                                <div class="score-fill" style="width: {{ (score / 5.0 * 100) | round(0) }}%;"></div>
                            </div>
                        </div>
                    </div>
                </div>

            {% if row['詳細URL'] != '#' %}
            </a>
            {% endif %}

        </div>
        {% endfor %}
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const filterButtons = document.querySelectorAll('.genre-button');
            const movieItems = document.querySelectorAll('.movie-item');

            filterButtons.forEach(button => {
                button.addEventListener('click', function() {
                    // クリックされたボタンのアクティブ状態をトグル
                    this.classList.toggle('active');

                    // 現在アクティブな全てのボタンのジャンルを取得
                    const activeButtons = document.querySelectorAll('.genre-button.active');
                    const selectedGenres = Array.from(activeButtons).map(btn => btn.getAttribute('data-genre'));

                    if (selectedGenres.length === 0) {
                        // アクティブなボタンが一つもない場合 (全表示)
                        movieItems.forEach(item => {
                            item.classList.remove('hidden');
                        });
                    } else {
                        // 1つ以上のボタンがアクティブな場合 (OR検索)
                        movieItems.forEach(item => {
                            const movieGenresString = item.getAttribute('data-genres');
                            // カンマ区切りの文字列を配列に変換
                            const movieGenres = movieGenresString ? movieGenresString.split(',') : [];
                            
                            // 映画のジャンルリストに、選択されたジャンルのどれか一つでも含まれているかチェック
                            const shouldShow = selectedGenres.some(selectedGenre => 
                                movieGenres.includes(selectedGenre)
                            );

                            if (shouldShow) {
                                item.classList.remove('hidden');
                            } else {
                                item.classList.add('hidden');
                            }
                        });
                    }
                });
            });
        });
    </script>
    </body>
</html>
""")

    # データをHTMLテンプレートに渡してレンダリング
    html_output = html_template.render(data=ranking_df, display_genres=display_genres)

    # HTMLファイルを保存
    html_file_path = 'index.html' 
    try:
        with open(html_file_path, 'w', encoding='utf-8') as f:
            f.write(html_output)
        print(f"\n✨ スタイルとフィルタ付きのウェブページが '{html_file_path}' に保存されました。")
    except Exception as e:
        print(f"\nHTMLファイルの保存に失敗しました: {e}")