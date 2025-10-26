# 【ホバー時のデザイン調整とあらすじ位置修正版 - CSS微調整 + 更新日追加】
import requests
from bs4 import BeautifulSoup, Comment 
import pandas as pd
import time 
import json 
from jinja2 import Template
from urllib.parse import urljoin 
import sys 
from datetime import datetime 
import re 

# 標準出力をUTF-8に設定
sys.stdout.reconfigure(encoding='utf-8') 

# --- 設定 (変更なし) ---
MAX_MOVIES_TO_SCRAPE = 10 
TOTAL_PAGES = 1 
BASE_DOMAIN = "https://filmarks.com" 

VOD_URLS = { "Amazon": "/list/vod/prime_video?page={}", }
TARGET_GENRES_MAP = {
    "SF": "SF", "アクション": "アクション", "アドベンチャー": "冒険", "冒険": "冒険",
    "アドベンチャー・冒険": "冒険", "クライム": "クライム", "ファミリー": "ファミリー",
    "ファンタジー": "ファンタジー", "アニメ": "アニメ", "アニメーション": "アニメ",
}
FINAL_GENRE_BUTTONS = sorted(list(set(TARGET_GENRES_MAP.values())))
# --- /設定 ---

# HTTPリクエストのヘッダー情報
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

movie_data_map = {}
all_processed_genres = set() 
movie_processed_count = 0 
synopsis_fetched_count = 0 

print("スクレイピングを開始します...")


# ★★★ あらすじ本文取得ロジック (変更なし) ★★★
def fetch_synopsis(detail_url, headers):
    global synopsis_fetched_count
    
    if detail_url == "#" or not detail_url.startswith(BASE_DOMAIN):
        return "あらすじ情報なし"
    
    print(f"    -> あらすじ取得中: {detail_url}") 
    time.sleep(0.8) 
    
    try:
        response = requests.get(detail_url, headers=headers)
        if response.status_code != 200:
            print(f"    警告: 詳細ページの取得に失敗しました。ステータスコード: {response.status_code}")
            return "あらすじ情報なし"
            
        detail_soup = BeautifulSoup(response.content, 'html.parser')
        
        # 1. ★最優先★ JSON-LDからの抽出を試みる
        json_ld_script = detail_soup.find('script', {'type': 'application/ld+json'})
        if json_ld_script and json_ld_script.string:
            try:
                data = json.loads(json_ld_script.string)
                
                if isinstance(data, list):
                    movie_data = next((item for item in data if isinstance(item, dict) and item.get('@type') == 'Movie'), None)
                else:
                    movie_data = data
                
                if isinstance(movie_data, dict) and movie_data.get('@type') == 'Movie' and 'outline' in movie_data:
                    extracted_synopsis = movie_data['outline'].strip()
                    if extracted_synopsis and len(extracted_synopsis) > 10:
                        synopsis_fetched_count += 1
                        print("    ✅ あらすじをJSON-LD (outline) から取得しました。")
                        return extracted_synopsis

            except (json.JSONDecodeError, AttributeError, TypeError, StopIteration):
                pass


        # 2. 標準セレクタでの取得を試みる (フォールバック)
        synopsis_container = detail_soup.select_one('div#js-content-detail-synopsis')
        if synopsis_container:
            synopsis_elements = synopsis_container.select('p.p-content-detail__synopsis-desc')
            
            synopsis_text = "あらすじ情報なし"
            if len(synopsis_elements) >= 2:
                synopsis_text = synopsis_elements[1].text.strip()
            elif len(synopsis_elements) == 1:
                synopsis_text = synopsis_elements[0].text.strip()
            else:
                if synopsis_container.find('h3', class_='p-content-detail__synopsis-term'):
                    synopsis_container.find('h3', class_='p-content-detail__synopsis-term').decompose()
                if synopsis_container.find('button', class_='p-content-detail-readmore'):
                    synopsis_container.find('button', class_='p-content-detail-readmore').decompose()
                
                temp_text = synopsis_container.text.strip()
                temp_text = re.sub(r'\s+', ' ', temp_text).strip()
                if temp_text and len(temp_text) > 10:
                    synopsis_text = temp_text

            if synopsis_text and synopsis_text != "あらすじ情報なし" and synopsis_text.strip() and len(synopsis_text) > 10:
                 synopsis_fetched_count += 1 
                 print("    ✅ あらすじの本文を取得しました (標準セレクタ/フォールバック)。")
                 return synopsis_text

            
    except requests.exceptions.RequestException as e:
        print(f"    エラー: 詳細ページのアクセスで問題が発生しました: {e}")
        
    print("    ❌ あらすじの本文は取得できませんでした。")
    return "あらすじ情報なし"
# ★★★ /あらすじ本文取得ロジック ★★★


# VODサービスごとにループ (変更なし)
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
            if movie_processed_count >= MAX_MOVIES_TO_SCRAPE:
                print("  💡 処理件数が上限に達したため、スクレイピングを強制終了します。")
                break 

            try:
                # ... (映画情報抽出ロジックは省略) ...
                content_cassette = movie.select_one('div.p-content-cassette')
                if not content_cassette: continue
                
                title_element = content_cassette.select_one('.p-content-cassette__title')
                score_element = content_cassette.select_one('.c-rating__score')
                if not (title_element and score_element): continue

                title = title_element.text.strip()
                score_text = score_element.text.strip()
                try: score = float(score_text)
                except ValueError: continue

                detail_url = "#"
                movie_id = None
                
                data_clip_str = movie.get('data-clip')
                if data_clip_str:
                    try:
                        cleaned_data_clip_str = data_clip_str.replace("'", '"')
                        data_clip = json.loads(cleaned_data_clip_str)
                        movie_id = data_clip.get('movie_id')
                        if movie_id: detail_url = f"{BASE_DOMAIN}/movies/{movie_id}" 
                    except (json.JSONDecodeError, Exception): pass

                if not movie_id: continue

                poster_url = None
                try:
                    poster_element = content_cassette.select_one('div.p-content-cassette__jacket img') 
                    if poster_element: poster_url = poster_element.get('data-src') or poster_element.get('src')
                except Exception: pass

                release_date = "上映日：N/A"
                try:
                    release_info_div = content_cassette.select_one('.p-content-cassette__other-info-title')
                    if release_info_div and "上映日：" in release_info_div.text:
                        next_span = release_info_div.find_next_sibling('span')
                        if next_span: release_date = f"上映日：{next_span.text.strip()}"
                except Exception: pass 

                raw_genres = [] 
                processed_genres = set() 
                genres_info = "ジャンル：N/A"
                try:
                    genre_elements = content_cassette.select('.p-content-cassette__other-info.genres_and_distributor .genres a')
                    raw_genres = [g.text.strip() for g in genre_elements]
                    if raw_genres:
                        for g in raw_genres:
                            processed_g = TARGET_GENRES_MAP.get(g)
                            if processed_g: processed_genres.add(processed_g)
                            
                            unique_raw_genres = list(set(raw_genres))
                            genres_info = f"ジャンル：{', '.join(unique_raw_genres)}"
                            all_processed_genres.update(processed_genres)
                except Exception: pass 
                    
                # --- あらすじのスクレイピングを実行 ---
                synopsis = "あらすじ情報なし" 
                if movie_processed_count < MAX_MOVIES_TO_SCRAPE and detail_url != "#":
                    synopsis = fetch_synopsis(detail_url, headers) 
                    
                # --- /あらすじのスクレイピングを実行 ---
                
                # データに追加 
                if movie_id in movie_data_map:
                    if vod_name_short not in movie_data_map[movie_id]['vod_sources']:
                        movie_data_map[movie_id]['vod_sources'].append(vod_name_short)
                else:
                    movie_data_map[movie_id] = {
                        'タイトル': title, 
                        '評価': score, 
                        '画像URL': poster_url,
                        '上映日': release_date,
                        'ジャンル': genres_info, 
                        'あらすじ': synopsis, 
                        'ジャンルリスト': list(processed_genres), 
                        '詳細URL': detail_url,
                        'vod_sources': [vod_name_short] 
                    }
                
                movie_processed_count += 1 

            except Exception as e:
                print(f"    個別の映画処理中にエラー: {e}")
                pass
        
        if movie_processed_count >= MAX_MOVIES_TO_SCRAPE: break
    if movie_processed_count >= MAX_MOVIES_TO_SCRAPE: break


# 収集したデータをDataFrameに変換 (変更なし)
df = pd.DataFrame(list(movie_data_map.values()))

# 最終的な取得ステータスをコンソールに出力
if synopsis_fetched_count > 0:
    print(f"\n✅ テストモード（{MAX_MOVIES_TO_SCRAPE}件制限）で、あらすじの本文取得に成功しました。 (取得件数: {synopsis_fetched_count}/{MAX_MOVIES_TO_SCRAPE})")
else:
    print(f"\n❌ テストモード（{MAX_MOVIES_TO_SCRAPE}件制限）ですが、あらすじの本文は取得できませんでした。")

# ... (HTML生成と出力は省略) ...
display_genres = sorted([g for g in FINAL_GENRE_BUTTONS if g in all_processed_genres])

if df.empty:
    print("収集できたデータがありませんでした。")
else:
    ranking_df = df.sort_values(by='評価', ascending=False).reset_index(drop=True)
    ranking_df.index = ranking_df.index + 1
    ranking_df.index.name = '順位'
    
    print("\nHTMLファイルを生成しています...")
    
    # 🌟 追加: 現在の日付をJinja2テンプレートで利用できるようにする
    current_date = datetime.now().strftime("%Y.%m.%d")
    
    html_template = Template("""
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>Filmarks VODランキング (Prime Video & Netflix)</title>
    
    <meta name="viewport" content="width=1040, initial-scale=1">
    <style>
        /* CSS修正 */
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; padding: 20px; }
        .container { max-width: 900px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }
        h1 { color: #0088cc; border-bottom: 3px solid #0088cc; padding-bottom: 10px; margin-bottom: 20px; text-align: center; }

        /* 🌟 追加: 更新日時のスタイル */
        .update-time { 
            text-align: right; 
            font-size: 0.85em; 
            color: #777; 
            margin-top: -10px; /* H1との間を少し詰める */
            margin-bottom: 15px;
            padding-right: 10px;
        }
        .update-time span {
            font-weight: bold;
            color: #555;
            margin-left: 5px;
        }
        
        .genre-filters { display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 0 30px 0; border-bottom: 1px solid #ddd; margin-bottom: 30px; }
        .genre-button { background-color: #f0f0f0; color: #555; border: 1px solid #ccc; padding: 5px 12px; border-radius: 20px; font-size: 0.9em; cursor: pointer; transition: background-color 0.2s, color 0.2s, border-color 0.2s; outline: none; user-select: none; }
        .genre-button.active { background-color: #0088cc; color: white; border-color: #0088cc; }
        
        /* ★修正点1: movie-item 全体にホバー効果を適用 */
        .movie-item { 
            border-left: 5px solid transparent; 
            transition: all 0.3s ease-in-out; 
            display: flex; 
            align-items: stretch; 
            padding: 15px 0; 
            border-bottom: 1px dashed #eee; 
            position: relative; 
            cursor: pointer; /* マウスカーソルをポインターに変更 */
        }
        .movie-item.hidden { display: none; }
        .rating-highlight { background-color: #fff9e6; border-left: 5px solid #ffcc33; }
        
        /* ★修正点2: ホバー時に背景色を適用 */
        .movie-item:hover {
             background-color: #ffefd1; /* 薄いオレンジ */
        }
        
        .rank-area { width: 90px; flex-shrink: 0; padding-right: 15px; padding-left: 10px; display: flex; flex-direction: row; flex-wrap: nowrap; align-content: stretch; justify-content: center; align-items: center; }
        .rank { font-size: 3.5em; font-weight: bold; text-align: center; color: #aaa; line-height: 1; }
        .rank.top3 { color: #ffbf00; }
        .rank.top10 { color: #0088cc; }
        
        /* ★修正点3: content-link-wrap のホバー効果を削除し、ホバー時タイトル色変更を追加 */
        .content-link-wrap { 
            display: flex; 
            flex-grow: 1; 
            align-items: flex-start; /* 縦方向の整列を修正 */
            text-decoration: none; 
            color: inherit; 
            transition: color 0.3s; /* タイトルの色変更用 */
            padding: 15px 0; 
            margin: -15px 0; /* movie-item のpaddingを相殺し、クリック領域を広げる */
            flex-wrap: wrap; /* あらすじを次の行に配置するために追加 */
        }
        .movie-item:hover .title { color: #0088cc; text-decoration: underline; } /* ホバー時タイトルを青くする */

        /* ★CSS変更点1: padding-top: 9px; を追加 */
        .poster { width: 100px; height: auto; margin-right: 20px; flex-shrink: 0; flex-grow: 0; display: flex; padding-top: 9px;}
        .poster img { width: 100%; height: 100%; object-fit: contain; border-radius: 4px; box-shadow: 0 2px 5px rgba(0, 0, 0, 0.15); }
        .info { flex-grow: 1; display: flex; flex-direction: column; justify-content: flex-start; padding-right: 15px; min-width: 250px; }
        .main-info { display: flex; flex-direction: column; flex-grow: 1; justify-content: flex-start; }
        .title-and-badges { display: flex; align-items: center; margin-bottom: 5px; }
        .title { font-size: 1.2em; font-weight: 600; color: #333; margin-right: 10px; }
        
        .release-date, .genre-info { font-size: 0.85em; color: #777; margin-bottom: 5px; line-height: 1.4; }
        .score-block { display: flex; align-items: center; margin-bottom: 5px; }
        .star-rating { display: inline-flex; align-items: center; font-size: 1.3em; margin-right: 8px; position: relative; }
        .stars-outer { position: relative; display: inline-flex; color: #d9d1b9; white-space: nowrap; }
        .stars-inner { position: absolute; top: 0; left: 0; white-space: nowrap; overflow: hidden; width: 0; color: orange; }
        .score-text { font-size: 1.5em; font-weight: bold; color: orange; }
        .vod-badges { display: flex; gap: 5px; margin-top: 5px; margin-bottom: 5px; }
        .vod-badge { font-size: 0.75em; font-weight: bold; padding: 2px 6px; border-radius: 4px; background: none; border: 1px solid; white-space: nowrap; }
        .vod-badge.Amazon { color: #0088cc; border-color: #0088cc; }
        .vod-badge.Netflix { color: #e50914; border-color: #e50914; }
        
        /* ★CSS変更点2: あらすじの調整 - margin-top: 10px; を削除 */
        .synopsis-wrap { 
            flex-basis: 100%; /* 親要素(content-link-wrap)の幅いっぱいを使用 */
            /* margin-top: 10px; ← 削除済み */
            padding-left: 120px; /* ポスターの幅(100px) + マージン(20px) に合わせて左に余白を持たせる */
            font-size: 0.85em; 
            color: #555; 
            line-height: 1.5; 
            z-index: 5; 
            display: flex; 
            flex-direction: column; 
        }
        .synopsis-content { position: relative; z-index: 2; }
        .synopsis-text { overflow: hidden; transition: max-height 0.5s ease-in-out, padding 0.2s; max-height: 0; padding: 0; display: block; }
        .synopsis-text.expanded { padding: 10px 0; }
        .synopsis-text p { margin: 0; }
        .synopsis-toggle-button { background: none; border: none; color: orange; cursor: pointer; padding: 5px 0; font-size: 0.9em; display: block; font-weight: bold; text-align: left; position: relative; z-index: 10; }
        
        @media (max-width: 600px) {
            body { padding: 5px; }
            .container { padding: 10px; }
            h1 { font-size: 1.4em; margin-bottom: 15px; }
            .update-time { margin-top: -5px; margin-bottom: 10px; text-align: center; }
            .movie-item { flex-direction: column; align-items: flex-start; padding: 10px 0; position: relative; }
            .rank-area { width: 100%; padding: 0 10px; margin-bottom: 5px; justify-content: flex-start; align-items: flex-start; }
            .rank { font-size: 2.5em; align-self: flex-start; padding-left: 0; }
            
            .content-link-wrap { width: 100%; padding: 0 10px; flex-wrap: wrap; align-items: flex-start; margin: 0; }
            .poster { width: 80px; height: auto; margin-right: 10px; padding-top: 0; /* モバイルではリセット */ }
            .info { padding-right: 0; min-width: 0; flex-basis: calc(100% - 90px); }
            .title { font-size: 1.0em; }
            .release-date, .genre-info { font-size: 0.75em; margin-bottom: 2px; line-height: 1.2; }
            .score { font-size: 1.1em; }
            
            /* スマホ表示でのあらすじ調整 */
            .synopsis-wrap { width: 100%; flex-basis: 100%; margin-top: 5px; padding: 0 10px; } /* 余分なpaddingを削除し、モバイルでの左右のpaddingを合わせる */
        }
    </style>
</head>
<body>
    <div class="container">
        
        <h1>Prime Video & Netflix 統合ランキング</h1>
        
        {# 🌟 追加: 更新日時の表示 #}
        <div class="update-time" id="js-update-time">
            &#128337; <span>{{ current_date }}</span>
        </div>
        
        <div class="genre-filters">
            {% for genre in display_genres %}
            <button class="genre-button" data-genre="{{ genre }}">{{ genre }}</button>
            {% endfor %}
        </div>
        
        {% for index, row in data.iterrows() %}
        {% set rank = loop.index %}
        {% set score = row['評価'] %}
        {% set score_percent = (score / 5.0 * 100) %}
        {% set is_highlight = score >= 4.0 %}
        {% set rank_class = 'top3' if rank <= 3 else ('top10' if rank <= 10 else '') %}
        {# あらすじの有無判定 #}
        {% set synopsis_content = row['あらすじ'] | default('') | trim %}
        {% set has_synopsis = synopsis_content is not none and synopsis_content != "あらすじ情報なし" and synopsis_content | length > 0 %}
        
        <div class="movie-item {% if is_highlight %}rating-highlight{% endif %}" data-genres="{{ row['ジャンルリスト'] | join(',') }}">
            
            <div class="rank-area">
                <div class="rank {{ rank_class }}">{{ rank }}</div>
            </div>
            
            {# ★ここから a タグを開始。あらすじを<a>タグの中に含める構造に変更 #}
            {% if row['詳細URL'] != '#' %}
            <a href="{{ row['詳細URL'] }}" target="_blank" class="content-link-wrap">
            {% endif %}

                <div class="poster">
                    {% if row['画像URL'] %}
                        <img src="{{ row['画像URL'] }}" alt="{{ row['タイトル'] }} ポスター">
                    {% else %}
                    <div style="width: 100%; height: 100%; background: #ccc; display: flex; align-items: center; justify-content: center; font-size: 0.8em; text-align: center;">No Image</div>
                    {% endif %}
                </div>
                <div class="info">
                    
                    <div class="score-block">
                        <div class="star-rating">
                            <div class="stars-outer">★★★★★</div>
                            <div class="stars-inner" style="width: {{ score_percent }}%;">★★★★★</div>
                        </div>
                        <div class="score-text">{{ score | round(1) }}</div>
                    </div>

                    <div class="main-info">
                        <div>
                            <div class="title-and-badges">
                                <div class="title">
                                    {{ row['タイトル'] }}
                                </div>
                            </div>
                            <div class="genre-info">{{ row['ジャンル'] }}</div>
                            <div class="release-date">{{ row['上映日'] }}</div>
                        </div>
                        
                        {# VODバッジ #}
                        <div class="vod-badges">
                            {% for vod in row['vod_sources'] %}
                            <span class="vod-badge {{ vod }}">{{ vod }}</span>
                            {% endfor %}
                        </div>
                        
                    </div>
                    
                </div>
            
            {# あらすじブロックをVODバッジの直後、aタグ内に配置 #}
            {% if has_synopsis %}
            <div class="synopsis-wrap">
                <div class="synopsis-content">
                    {# トグルボタンを先に配置（CSSで制御するため） #}
                    <button class="synopsis-toggle-button js-toggle-synopsis" data-expanded="false">
                        あらすじを見る▼
                    </button>
                    <div class="synopsis-text js-synopsis-full" >
                        <p>{{ synopsis_content | e }}</p> 
                    </div>
                </div>
            </div>
            {% endif %}
            
            {# aタグを終了 #}
            {% if row['詳細URL'] != '#' %}
            </a>
            {% endif %}

        </div>
        {% endfor %}
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // ジャンルフィルタのロジック (変更なし)
            const filterButtons = document.querySelectorAll('.genre-button');
            const movieItems = document.querySelectorAll('.movie-item');

            filterButtons.forEach(button => {
                button.addEventListener('click', function() {
                    this.classList.toggle('active');

                    const activeButtons = document.querySelectorAll('.genre-button.active');
                    const selectedGenres = Array.from(activeButtons).map(btn => btn.getAttribute('data-genre'));

                    if (selectedGenres.length === 0) {
                        movieItems.forEach(item => {
                            item.classList.remove('hidden');
                        });
                    } else {
                        movieItems.forEach(item => {
                            const movieGenresString = item.getAttribute('data-genres');
                            const movieGenres = movieGenresString ? movieGenresString.split(',') : [];
                            
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

            // あらすじトグルのロジック (変更なし)
            document.querySelectorAll('.js-toggle-synopsis').forEach(button => {
                const movieItem = button.closest('.movie-item');
                if (!movieItem) return;

                const full = movieItem.querySelector('.js-synopsis-full');

                button.setAttribute('data-expanded', 'false');

                button.addEventListener('click', function(event) {
                    event.preventDefault(); 
                    event.stopPropagation(); 
                    
                    const isExpanded = this.getAttribute('data-expanded') === 'true';
                    
                    if (!isExpanded) {
                        // 展開
                        full.style.maxHeight = 'none';
                        const scrollHeight = full.scrollHeight; 
                        
                        full.style.maxHeight = '0px'; 
                        
                        setTimeout(() => {
                            full.style.maxHeight = (scrollHeight + 20) + 'px'; 
                            full.classList.add('expanded'); 
                        }, 10); 

                        this.textContent = '一部を隠す▲';
                        this.setAttribute('data-expanded', 'true');

                    } else {
                        // 折りたたみ

                        full.style.maxHeight = full.scrollHeight + 'px'; 
                        
                        full.classList.remove('expanded'); 
                        setTimeout(() => {
                            full.style.maxHeight = '0px';
                        }, 10);
                        
                        this.textContent = 'あらすじを見る▼';
                        this.setAttribute('data-expanded', 'false');
                    }
                });
            });
        });
    </script>
</body>
</html>
""")

    # データをHTMLテンプレートに渡してレンダリング
    html_output = html_template.render(data=ranking_df, display_genres=display_genres, current_date=current_date)

    # HTMLファイルを保存
    html_file_path = 'index.html' 
    try:
        with open(html_file_path, 'w', encoding='utf-8') as f:
            f.write(html_output)
        print(f"\n✨ 更新日時の表示を追加し、CSSの微調整を適用しました。")
        print(f"ウェブページが '{html_file_path}' に保存されました。")
    except Exception as e:
        print(f"\nHTMLファイルの保存に失敗しました: {e}")