# 【最終版: 映画/ドラマ絵文字調整 + ジャンルフィルター修正 + モバイルCSS対応 + HTML構造再修正】
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
import traceback 

sys.stdout.reconfigure(encoding='utf-8') 

# --- 設定 ---
MAX_MOVIES_TO_SCRAPE = 5000  # 取得上限件数
TOTAL_PAGES = 10          # 取得ページ数
SYNOPSIS_PER_PAGE = 500   # ページあたりのあらすじ取得制限を解除
BASE_DOMAIN = "https://filmarks.com" 

# 全てのVODとリストタイプを対象
VOD_LIST_URLS = { 
    "Amazon": { "映画": "/list/vod/prime_video?page={}", "ドラマ": "/list-drama/vod/prime_video?page={}" },
    "Netflix": { "映画": "/list/vod/netflix?page={}", "ドラマ": "/list-drama/vod/netflix?page={}" },
    #"Disney+": { "映画": "/list/vod/disneyplus?page={}", "ドラマ": "/list-drama/vod/disneyplus?page={}" }
}

# 「スリラー」を除外
TARGET_GENRES_MAP = {
    "SF": "SF", "アクション": "アクション", "アドベンチャー": "冒険", "冒険": "冒険",
    "アドベンチャー・冒険": "冒険", "クライム": "クライム", "ファミリー": "ファミリー",
    "ファンタジー": "ファンタジー", "アニメ": "アニメ", "アニメーション": "アニメ",
    "サスペンス": "サスペンス", "ヒューマンドラマ": "ヒューマンドラマ", "ミステリー": "ミステリー",
}
FINAL_GENRE_BUTTONS = sorted(list(set(TARGET_GENRES_MAP.values())))

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

movie_data_map = {}
all_processed_genres = set() 
movie_processed_count = 0 
synopsis_fetched_count = 0 
available_content_types = set()

print("スクレイピングを開始します...")


def fetch_synopsis(detail_url, headers):
    """あらすじを取得する関数"""
    global synopsis_fetched_count
    
    if detail_url == "#" or not detail_url.startswith(BASE_DOMAIN):
        return "あらすじ情報なし"
    
    time.sleep(0.8) 
    
    try:
        response = requests.get(detail_url, headers=headers)
        if response.status_code != 200:
            return "あらすじ情報なし"
            
        detail_soup = BeautifulSoup(response.content, 'html.parser')
        
        # 方法1: p.p-content-detail__synopsis-desc から取得
        synopsis_elements = detail_soup.select('p.p-content-detail__synopsis-desc')
        if synopsis_elements:
            synopsis_text = synopsis_elements[-1].text.strip() 
            if synopsis_text and len(synopsis_text) > 10:
                synopsis_fetched_count += 1
                return synopsis_text

        # 方法4: JSON-LD から取得 
        json_ld_script = detail_soup.find('script', {'type': 'application/ld+json'})
        if json_ld_script and json_ld_script.string:
            try:
                data = json.loads(json_ld_script.string)
                if isinstance(data, list):
                    movie_data = next((item for item in data if isinstance(item, dict) and item.get('@type') in ['Movie', 'TVEpisode', 'TVSeries']), None)
                else:
                    movie_data = data
                
                if isinstance(movie_data, dict) and movie_data.get('@type') in ['Movie', 'TVEpisode', 'TVSeries']:
                    extracted_synopsis = movie_data.get('description') or movie_data.get('outline')
                    if extracted_synopsis and isinstance(extracted_synopsis, str) and len(extracted_synopsis.strip()) > 10:
                        synopsis_fetched_count += 1
                        return extracted_synopsis.strip()
            except (json.JSONDecodeError, AttributeError, TypeError, StopIteration):
                pass

        # 方法2: ドラマ専用 - div.p-drama__synopsis 内のテキスト
        drama_synopsis_div = detail_soup.select_one('div.p-drama__synopsis')
        if drama_synopsis_div:
            for unwanted in drama_synopsis_div.select('button, h3, .p-drama__synopsis-title'):
                unwanted.decompose()
            synopsis_text = re.sub(r'\s+', ' ', drama_synopsis_div.get_text(strip=True))
            if synopsis_text and len(synopsis_text) > 10:
                synopsis_fetched_count += 1
                return synopsis_text

        # 方法5 (強化版): div#js-content-detail-synopsis 内の p タグを結合 (最終フォールバック)
        synopsis_container = detail_soup.select_one('div#js-content-detail-synopsis')
        if synopsis_container:
            synopsis_text = ""
            for p_tag in synopsis_container.find_all('p', recursive=True):
                text = p_tag.get_text(strip=True)
                if text:
                    synopsis_text += " " + text
            
            if not synopsis_text:
                for tag in synopsis_container.find_all(['h3', 'button']):
                    tag.decompose()
                synopsis_text = synopsis_container.get_text(strip=True)
            
            synopsis_text = re.sub(r'\s+', ' ', synopsis_text.strip()).strip()

            if synopsis_text and len(synopsis_text) > 10 and "あらすじ情報なし" not in synopsis_text:
                synopsis_fetched_count += 1  
                return synopsis_text
            
    except requests.exceptions.RequestException:
        pass
        
    return "あらすじ情報なし"


# VODサービスごとにループ
for vod_name, list_types in VOD_LIST_URLS.items():  
    for list_type, url_suffix in list_types.items():
        
        vod_name_short = vod_name
        synopsis_counter_for_page = 0  
            
        print(f"\n{'='*60}")
        print(f"--- {vod_name} の {list_type} データを収集中 ---")
        print(f"{'='*60}")
        
        # 設定されたページ数分ループ
        for page in range(1, TOTAL_PAGES + 1):
            url = urljoin(BASE_DOMAIN, url_suffix.format(page))
            print(f"\n📄 {vod_name} {list_type} {page}ページ目: {url}")
            
            time.sleep(1) 
            
            try:
                response = requests.get(url, headers=headers)
                if response.status_code != 200:
                    print(f"  ⚠️ ページ取得失敗。ステータス: {response.status_code}")
                    continue
            except requests.exceptions.RequestException as e:
                print(f"  ❌ アクセスエラー: {e}")
                continue

            soup = BeautifulSoup(response.content, 'html.parser')
            
            for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
                comment.extract()
            
            movies = soup.select('div.js-cassette')
            print(f"  📊 取得した要素数: {len(movies)}件\n")
            
            if not movies:
                print(f"  ⚠️ コンテンツが見つかりません")
                break 

            for idx, movie in enumerate(movies):
                if movie_processed_count >= MAX_MOVIES_TO_SCRAPE:
                    print("  🛑 処理件数上限に到達")
                    break 

                try:
                    
                    # 評価スコア
                    score_element = movie.select_one('.c-rating__score')
                    score = float(score_element.text.strip()) if score_element else 0.0

                    # タイトル
                    title_element = movie.select_one('h3.p-content-cassette__title')
                    if not title_element:
                        continue 
                    
                    title = title_element.text.strip()
                    
                    detail_url = "#"
                    movie_id = None
                    
                    # data-clip からIDとURLを取得
                    data_clip_str = movie.get('data-clip')
                    if data_clip_str:
                        try:
                            cleaned_data_clip_str = data_clip_str.replace("'", '"').replace('&quot;', '"')
                            data_clip = json.loads(cleaned_data_clip_str)
                            
                            drama_series_id = data_clip.get('drama_series_id')
                            drama_season_id = data_clip.get('drama_season_id')
                            movie_content_id = data_clip.get('movie_id') or data_clip.get('tv_id')
                            
                            if drama_series_id and drama_season_id:
                                movie_id = f"dramas_{drama_series_id}_{drama_season_id}"
                                detail_url = f"{BASE_DOMAIN}/dramas/{drama_series_id}/{drama_season_id}"
                            elif movie_content_id:
                                content_classes = movie.get('class', [])
                                content_type_path = 'tv' if ('p-content-cassette--tv' in content_classes or list_type == 'ドラマ') else 'movies'
                                movie_id = f"{content_type_path}_{movie_content_id}" 
                                detail_url = f"{BASE_DOMAIN}/{content_type_path}/{movie_content_id}"
                                
                        except Exception:
                            pass

                    if not movie_id: 
                        continue

                    # ポスターURL
                    poster_element = movie.select_one('div.p-content-cassette__jacket img, div.c2-poster-m img') 
                    poster_url = poster_element.get('data-src') if poster_element else None
                    if not poster_url:
                        poster_url = poster_element.get('src') if poster_element else None

                    # 公開日
                    release_date = "公開・初回放送:N/A"
                    release_info_div = movie.select_one('div.p-content-cassette__other-info')
                    if release_info_div:
                        first_span = release_info_div.select_one('span:nth-of-type(1)')
                        if first_span:
                            label = release_info_div.select_one('.p-content-cassette__other-info-title')
                            prefix = label.text.strip() if label else "日付:"
                            release_date = f"{prefix}{first_span.text.strip()}"

                    # ジャンル取得ロジック
                    raw_genres = []  
                    processed_genres = set()  
                    genres_info = "ジャンル:N/A"
                    
                    genre_elements = movie.select('div.p-content-cassette__other-info.genres_and_distributor ul.genres li a')
                    
                    if not genre_elements:
                         genre_elements = movie.select('div.p-content-cassette__genre ul li a')
                         
                    if genre_elements:
                        raw_genres = [g.text.strip() for g in genre_elements]
                        if raw_genres:
                            for g in raw_genres:
                                processed_g = TARGET_GENRES_MAP.get(g)
                                if processed_g: 
                                    processed_genres.add(processed_g)
                            genres_info = f"ジャンル:{', '.join(list(set(raw_genres)))}"
                            all_processed_genres.update(processed_genres)
                        
                    # あらすじ取得 
                    synopsis = "あらすじ情報なし"  
                    if synopsis_counter_for_page < SYNOPSIS_PER_PAGE and detail_url != "#":
                        synopsis = fetch_synopsis(detail_url, headers)  
                        if synopsis != "あらすじ情報なし":
                            synopsis_counter_for_page += 1  
                        
                    # データ保存
                    available_content_types.add(list_type) 
                    
                    if movie_id in movie_data_map:
                        if vod_name_short not in movie_data_map[movie_id]['vod_sources']:
                            movie_data_map[movie_id]['vod_sources'].append(vod_name_short)
                    else:
                        movie_data_map[movie_id] = {
                            'タイトル': title,  
                            '評価': score,  
                            '画像URL': poster_url,
                            '公開・初回放送': release_date,  
                            'ジャンル': genres_info,  
                            'あらすじ': synopsis,  
                            'ジャンルリスト': list(processed_genres),  
                            '詳細URL': detail_url,
                            'vod_sources': [vod_name_short],
                            'コンテンツタイプ': list_type 
                        }
                    
                    movie_processed_count += 1  

                except Exception as e:
                    pass
                
            if movie_processed_count >= MAX_MOVIES_TO_SCRAPE: 
                break
        
        if movie_processed_count >= MAX_MOVIES_TO_SCRAPE:
             break
    
    if movie_processed_count >= MAX_MOVIES_TO_SCRAPE:
        break


# ============================================
# データ処理 & HTML生成
# ============================================

df = pd.DataFrame(list(movie_data_map.values()))

print(f"\n{'='*60}")
print(f"✅ 収集完了: {movie_processed_count}件")
print(f"✅ あらすじ取得成功: {synopsis_fetched_count}件")
print(f"{'='*60}\n")

if df.empty:
    print("❌ データなし")
else:
    ranking_df = df.sort_values(by='評価', ascending=False).reset_index(drop=True)
    ranking_df.index = ranking_df.index + 1
    ranking_df.index.name = '順位'
    
    print("📊 取得データサンプル:")
    print(ranking_df[['タイトル', '評価', 'コンテンツタイプ', 'ジャンル']].head())
    
    print("\n🔨 HTMLファイル生成中...")
    
    current_date = datetime.now().strftime("%Y.%m.%d")
    display_genres = sorted([g for g in FINAL_GENRE_BUTTONS if g in all_processed_genres])
    available_vods = sorted(list(set(sum([d['vod_sources'] for d in movie_data_map.values()], []))))
    display_content_types = sorted(list(available_content_types))
    
    html_template = Template("""
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>Filmarks VODランキング(映画・ドラマ)</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎞️</text></svg>">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; padding: 20px; }
    .container { max-width: 900px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }
    h1 { color: #0088cc; border-bottom: 3px solid #0088cc; padding-bottom: 10px; margin-bottom: 20px; text-align: center; }
    .update-time { text-align: right; font-size: 0.85em; color: #777; margin-top: -10px; margin-bottom: 15px; padding-right: 10px; }
    .update-time span { font-weight: bold; color: #555; margin-left: 5px; }
    .filter-section { border-bottom: 1px solid #ddd; padding-bottom: 10px; margin-bottom: 15px; }
    .filter-title { font-size: 0.9em; font-weight: bold; color: #555; margin-bottom: 5px; }
    .filter-buttons { display: flex; flex-wrap: wrap; gap: 8px; }
    .genre-button, .vod-button, .type-button { background-color: #f0f0f0; color: #555; border: 1px solid #ccc; padding: 5px 12px; border-radius: 20px; font-size: 0.9em; cursor: pointer; transition: all 0.2s; outline: none; user-select: none; }
   
    /* VODボタンの色 */
    .vod-button[data-vod="Amazon"] { background-color: #f0f8ff; border-color: #0088cc; color: #0088cc; }
    .vod-button[data-vod="Netflix"] { background-color: #fff0f1; border-color: #e50914; color: #e50914; }
    .vod-button[data-vod="Disney+"] { background-color: #f1f3ff; border-color: #113ccf; color: #113ccf; }

    /* コンテンツタイプの色 */
    .type-button[data-type="映画"] { background-color: #f7f7e0; border-color: #a0a000; color: #a0a000; }
    .type-button[data-type="ドラマ"] { background-color: #e0f7f7; border-color: #008080; color: #008080; }

    /* アクティブなボタン */
    .genre-button.active { background-color: #0088cc; color: white; border-color: #0088cc; }
    .vod-button.active[data-vod="Amazon"] { background-color: #0088cc; color: white; }
    .vod-button.active[data-vod="Netflix"] { background-color: #e50914; color: white; }
    .vod-button.active[data-vod="Disney+"] { background-color: #113ccf; color: white; }
    .type-button.active[data-type="映画"] { background-color: #a0a000; color: white; }
    .type-button.active[data-type="ドラマ"] { background-color: #008080; color: white; }
   
    .movie-item { border-left: 5px solid transparent; transition: all 0.3s; display: flex; align-items: stretch; padding: 15px 0; border-bottom: 1px dashed #eee; position: relative; }
    .movie-item.hidden { display: none; }
    .rating-highlight { background-color: #fff9e6; border-left: 5px solid #ffcc33; }
    .movie-item:hover { background-color: #fcf9f0; }
    .rank-area { width: 90px; flex-shrink: 0; padding-right: 15px; padding-left: 10px; display: flex; justify-content: center; align-items: center; }
    .rank { font-size: 3.5em; font-weight: bold; text-align: center; color: #aaa; line-height: 1; }
    .rank.top3 { color: #ffbf00; }
    .rank.top10 { color: #0088cc; }
    .content-link-wrap { display: flex; flex-grow: 1; align-items: flex-start; text-decoration: none; color: inherit; transition: color 0.3s; padding: 15px 0; margin: -15px 0; }
    .content-link-wrap:hover .title { color: #0088cc; text-decoration: underline; }
    .poster { width: 100px; height: auto; margin-right: 20px; flex-shrink: 0; display: flex; padding-top: 9px;}
    .poster img { width: 100%; height: 100%; object-fit: contain; border-radius: 4px; box-shadow: 0 2px 5px rgba(0, 0, 0, 0.15); }
    .info { flex-grow: 1; display: flex; flex-direction: column; justify-content: flex-start; padding-right: 15px; min-width: 250px; }
    .title { font-size: 1.2em; font-weight: 600; color: #333; margin-bottom: 5px; }
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
    .vod-badge.Disney\\+ { color: #113ccf; border-color: #113ccf; }
    .synopsis-area { flex-basis: 100%; font-size: 0.85em; color: #555; line-height: 1.5; display: flex; flex-direction: column; padding-top: 5px; }
    .synopsis-toggle-button { background: none; border: none; color: orange; cursor: pointer; padding: 5px 0; font-size: 0.9em; font-weight: bold; text-align: left; }
    .synopsis-text { overflow: hidden; transition: max-height 0.5s ease-in-out; max-height: 0; padding: 0; margin-top: 0; }
    .synopsis-text.expanded { padding: 10px 0; max-height: 1000px !important; }
    .synopsis-text p { margin: 0; }
    .movie-emoji { margin-right: 5px; } /* 映画絵文字用のスペース調整 */

        /* --- 追加CSS開始 --- */
        .content-area-mobile-wrap {
            display: flex; /* これを追加 */
        }
        /* --- 追加CSS終了 --- */
   
    /* ============== 評価レート上限フィルター ============== */
    .rating-filter-controls {
        display: flex;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
    }
    .rating-btn {
        background-color: #f0f0f0;
        color: #555;
        border: 1px solid #ccc;
        padding: 5px 10px;
        border-radius: 20px;
        font-size: 0.95em;
        cursor: pointer;
        transition: all 0.15s;
        outline: none;
        user-select: none;
        font-weight: bold;
        line-height: 1;
    }
    .rating-btn:hover { background-color: #0088cc; color: white; border-color: #0088cc; }
    .rating-btn:active { transform: scale(0.94); }
    .rating-btn:disabled { opacity: 0.35; cursor: not-allowed; }
    .rating-btn:disabled:hover { background-color: #f0f0f0; color: #555; border-color: #ccc; }
    #rate-display {
        font-size: 1.4em;
        font-weight: bold;
        color: orange;
        min-width: 42px;
        text-align: center;
        display: inline-block;
        letter-spacing: 0.02em;
    }
    .rating-label {
        font-size: 0.85em;
        color: #888;
        margin-left: 4px;
    }
    @media (max-width: 500px) {
        .rating-btn { padding: 4px 9px; font-size: 0.9em; }
        #rate-display { font-size: 1.2em; }
    }
    /* ============================================================= */

    /* ============== iPhone SE2 (375px) 対応 CSSの復活 ============== */
    @media (max-width: 500px) {
      body { padding: 10px; }
      .container { padding: 15px; }
     
      .filter-buttons { gap: 6px; }
      .genre-button, .vod-button, .type-button { padding: 4px 10px; font-size: 0.85em; }
     
      .movie-item {
        flex-direction: column; /* 縦に積み重ねる */
        align-items: flex-start;
        padding: 10px 0;
        border-bottom: 1px solid #eee;
      }
      .content-link-wrap {
        /* flex-direction: column; */
        padding: 0 14px;
        margin: 0;
      }
     
      .rank-area {
        width: 100%;
        height: 40px;
        padding: 0;
        justify-content: flex-start; /* 順位を左に寄せる */
        margin-bottom: 10px;
      }
      .rank {
        font-size: 2.5em; /* 順位を少し小さく */
        width: 50px;
      }
     
      .poster {
        width: 80px; /* ポスターを小さく */
        height: auto;
        margin-right: 15px;
        padding-top: 0;
      }
     
      .info {
        min-width: unset;
        padding-right: 0;
        margin-top: -8px; /* 順位エリアに重なるように調整 */
        /* margin-left: 65px; */ /* ポスターの横に寄せる */
      }
     
      .title {
        font-size: 1.1em; /* タイトルを少し小さく */
        line-height: 1.3;
      }
      .score-block { margin-bottom: 3px; }
      .score-text { font-size: 1.3em; } /* スコアも調整 */
      .star-rating { font-size: 1.1em; }
     
      .vod-badges { margin-top: 2px; margin-bottom: 2px; }
      .synopsis-area {
        flex-basis: 100%;
        /* margin-top: 10px; */
        margin-left: 0; /* 全幅を使う */
      }
      .synopsis-text { font-size: 0.8em; }
     
      .content-area-mobile-wrap {
        display: flex;
        flex-direction: row;
        width: 100%;
        padding: 0 14px; /* これを追加 */
      }
    }
    /* ========================================================= */
    </style>
</head>
<body>
    <div class="container">
        <h1>VOD 統合ランキング(映画・ドラマ)</h1>
        <div class="update-time">&#128337; 最終更新日: <span>{{ current_date }}</span></div>
        
        <div class="filter-section content-type-filters">
            <div class="filter-title">コンテンツタイプ:</div>
            <div class="filter-buttons">
                {% for type in display_content_types %}
                <button class="type-button" data-type="{{ type }}">{{ type }}</button>
                {% endfor %}
            </div>
        </div>
        
        <div class="filter-section rating-filter">
            <div class="filter-title">評価レート上限:</div>
            <div class="rating-filter-controls">
                <button class="rating-btn" id="rate-minus-1" title="-1.0">&#171;</button>
                <button class="rating-btn" id="rate-minus-01" title="-0.1">&#8249;</button>
                <span id="rate-display">5.0</span>
                <button class="rating-btn" id="rate-plus-01" title="+0.1">&#8250;</button>
                <button class="rating-btn" id="rate-plus-1" title="+1.0">&#187;</button>
                <span class="rating-label">以下を表示</span>
            </div>
        </div>
        
        <div class="filter-section genre-filters">
            <div class="filter-title">ジャンル:</div>
            <div class="filter-buttons">
                {% for genre in display_genres %}
                <button class="genre-button" data-genre="{{ genre }}">{{ genre }}</button>
                {% endfor %}
            </div>
        </div>
        
        <div class="filter-section vod-filters" style="border-bottom: none; margin-bottom: 30px;">
            <div class="filter-title">VODサービス:</div>
            <div class="filter-buttons">
                {% for vod in available_vods %}
                <button class="vod-button" data-vod="{{ vod }}">{{ vod }}</button>
                {% endfor %}
            </div>
        </div>
        
        {% for index, row in data.iterrows() %}
        {% set rank = loop.index %}
        {% set score = row['評価'] %}
        {% set score_percent = (score / 5.0 * 100) %}
        {% set is_highlight = score >= 4.0 %}
        {% set rank_class = 'top3' if rank <= 3 else ('top10' if rank <= 10 else '') %}
        {% set synopsis_content = row['あらすじ'] | default('') | trim %}
        {% set has_synopsis = synopsis_content and synopsis_content != "あらすじ情報なし" and synopsis_content | length > 0 %}
        
        <div class="movie-item {% if is_highlight %}rating-highlight{% endif %}" 
             data-genres="{{ row['ジャンルリスト'] | join(',') }}"
             data-vods="{{ row['vod_sources'] | join(',') }}"
             data-type="{{ row['コンテンツタイプ'] }}">
            
            <div class="rank-area">
                <div class="rank {{ rank_class }}">{{ rank }}</div>
            </div>
            
            <div class="content-area-mobile-wrap"> <div class="poster">
                    {% if row['画像URL'] %}
                    <img src="{{ row['画像URL'] }}" alt="{{ row['タイトル'] }}">
                    {% else %}
                    <div style="width:100%;height:100%;background:#ccc;display:flex;align-items:center;justify-content:center;font-size:0.8em;">No Image</div>
                    {% endif %}
                </div>
                
                <div class="info">
                    {% if row['詳細URL'] != '#' %}
                    <a href="{{ row['詳細URL'] }}" target="_blank" class="content-link-wrap" style="padding:0; margin:0; flex-direction: column; align-items: flex-start;">
                    {% endif %}
                        <div class="score-block">
                            <div class="star-rating">
                                <div class="stars-outer">★★★★★</div>
                                <div class="stars-inner" style="width: {{ score_percent }}%;">★★★★★</div>
                            </div>
                            <div class="score-text">{{ score | round(1) }}</div>
                        </div>
                        <div class="title">
                            {% if row['コンテンツタイプ'] == '映画' %}
                            <span class="movie-emoji">🎬</span> 
                            {% endif %}
                            {{ row['タイトル'] }}
                        </div>
                        <div class="genre-info">{{ row['ジャンル'] }}</div>
                        <div class="release-date">{{ row['公開・初回放送'] }}</div>
                    {% if row['詳細URL'] != '#' %}
                    </a>
                    {% endif %}

                    <div class="vod-badges">
                        {% for vod in row['vod_sources'] %}
                        {% set badge_class = 'Disney\\+' if vod == 'Disney+' else vod %}
                        <span class="vod-badge {{ badge_class }}">{{ vod }}</span>
                        {% endfor %}
                    </div>
                    
                    {% if has_synopsis %}
                    <div class="synopsis-area">
                        <button class="synopsis-toggle-button js-toggle-synopsis" data-expanded="false">あらすじを見る▼</button>
                        <div class="synopsis-text js-synopsis-full">
                            <p>{{ synopsis_content | e }}</p> 
                        </div>
                    </div>
                    {% endif %}
                </div>
                
            </div> </div>
        {% endfor %}
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const movieItems = document.querySelectorAll('.movie-item');

            // --- 評価レート上限フィルター ---
            let maxRating = 5.0;
            const rateDisplay  = document.getElementById('rate-display');
            const btnMinus1    = document.getElementById('rate-minus-1');
            const btnMinus01   = document.getElementById('rate-minus-01');
            const btnPlus01    = document.getElementById('rate-plus-01');
            const btnPlus1     = document.getElementById('rate-plus-1');

            function updateRateUI() {
                rateDisplay.textContent = maxRating.toFixed(1);
                btnMinus1.disabled  = maxRating <= 0.0;
                btnMinus01.disabled = maxRating <= 0.0;
                btnPlus1.disabled   = maxRating >= 5.0;
                btnPlus01.disabled  = maxRating >= 5.0;
            }

            function changeRating(delta) {
                maxRating = Math.round((maxRating + delta) * 10) / 10;
                maxRating = Math.min(5.0, Math.max(0.0, maxRating));
                updateRateUI();
                applyFilters();
            }

            btnMinus1.addEventListener('click',  () => changeRating(-1.0));
            btnMinus01.addEventListener('click', () => changeRating(-0.1));
            btnPlus01.addEventListener('click',  () => changeRating(0.1));
            btnPlus1.addEventListener('click',   () => changeRating(1.0));
            // ---------------------------------

            function applyFilters() {
                const activeGenres = Array.from(document.querySelectorAll('.genre-button.active')).map(btn => btn.getAttribute('data-genre'));
                const activeVods = Array.from(document.querySelectorAll('.vod-button.active')).map(btn => btn.getAttribute('data-vod'));
                const activeTypes = Array.from(document.querySelectorAll('.type-button.active')).map(btn => btn.getAttribute('data-type'));

                movieItems.forEach(item => {
                    const movieGenres = (item.getAttribute('data-genres') || '').split(',');
                    const movieVods = (item.getAttribute('data-vods') || '').split(',');
                    const movieType = item.getAttribute('data-type');
                    const scoreEl = item.querySelector('.score-text');
                    const score = scoreEl ? parseFloat(scoreEl.textContent) : 0;

                    const showByGenre  = activeGenres.length === 0 || activeGenres.some(g => movieGenres.includes(g));
                    const showByVod    = activeVods.length === 0   || activeVods.some(v => movieVods.includes(v));
                    const showByType   = activeTypes.length === 0  || activeTypes.includes(movieType);
                    const showByRating = isNaN(score) || score <= maxRating;

                    item.classList.toggle('hidden', !(showByGenre && showByVod && showByType && showByRating));
                });
            }

            document.querySelectorAll('.genre-button').forEach(button => {
                button.addEventListener('click', function() {
                    this.classList.toggle('active');
                    applyFilters();
                });
            });

            document.querySelectorAll('.vod-button').forEach(button => {
                button.addEventListener('click', function() {
                    this.classList.toggle('active');
                    applyFilters();
                });
            });

            document.querySelectorAll('.type-button').forEach(button => {
                button.addEventListener('click', function() {
                    this.classList.toggle('active');
                    applyFilters();
                });
            });

            document.querySelectorAll('.js-toggle-synopsis').forEach(button => {
                const synopsisArea = button.closest('.synopsis-area');
                if (!synopsisArea) return;
                const full = synopsisArea.querySelector('.js-synopsis-full');
                full.style.maxHeight = '0px';

                button.addEventListener('click', function(event) {
                    event.preventDefault(); 
                    event.stopPropagation(); 
                    const isExpanded = this.getAttribute('data-expanded') === 'true';
                    
                    if (!isExpanded) {
                        full.classList.add('expanded');
                        // 展開時にscrollHeightを使って高さを取得
                        full.style.maxHeight = full.scrollHeight + 'px'; 
                        this.textContent = '一部を隠す▲';
                        this.setAttribute('data-expanded', 'true');
                    } else {
                        // 収縮時に現在のscrollHeightを取得してから高さを0にする
                        full.style.maxHeight = full.scrollHeight + 'px'; 
                        setTimeout(() => {
                            full.style.maxHeight = '0px';
                            full.classList.remove('expanded'); 
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

    html_output = html_template.render(
        data=ranking_df,  
        display_genres=display_genres,  
        current_date=current_date,  
        available_vods=available_vods,
        display_content_types=display_content_types 
    )

    html_file_path = 'index.html'  
    try:
        with open(html_file_path, 'w', encoding='utf-8') as f:
            f.write(html_output)
        print(f"\n✅ '{html_file_path}' に保存完了!")
    except Exception as e:
        print(f"\n❌ HTML保存失敗: {e}")