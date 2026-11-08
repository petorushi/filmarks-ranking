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
non_svod_skipped_count = 0  # 見放題ではない（レンタル・購入のみ）ため除外した件数
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

                    # 見放題のみ対象: 一覧ページの各作品には、そのサービスでの提供形態が
                    # 「見放題(label-svod)・レンタル(label-tvod)・購入(label-est)」のラベルで付いている。
                    # 見放題ラベルが無い作品は会員でも追加料金が必要なので除外する
                    if not movie.select_one('.c-vod-service-types__label.label-svod'):
                        non_svod_skipped_count += 1
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
print(f"✅ 見放題ではないため除外: {non_svod_skipped_count}件")
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
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>VOD 統合ランキング</title>
    <meta name="description" content="Filmarks の評価で並べた Amazon Prime Video と Netflix の映画・ドラマのランキング">
    <meta name="theme-color" content="#FBF9F8">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='18' fill='%238E1B2E'/><text x='50' y='74' font-size='68' font-family='Arial Narrow,Arial' font-weight='700' text-anchor='middle' fill='%23FBF9F8'>1</text></svg>">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@500;800&family=Zen+Kaku+Gothic+New:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
    /* 配色: 明るい映画館のロビー。客席のボルドーをアクセントにし、順位と高評価の数字だけに使う */
    :root {
        --bg: #FBF9F8;
        --raised: #F0EBEA;
        --line: #E6DCDC;
        --accent: #8E1B2E;
        --ink: #2A1A1E;
        --ink-dim: #5E4C50;
        --muted: #8E7C80;
        --amazon: #1C6AA3;
        --netflix: #C4122F;
        --disney: #2B44C2;
        --font-num: 'Big Shoulders Display', 'Arial Narrow', sans-serif;
        --font-body: 'Zen Kaku Gothic New', 'Hiragino Sans', 'Yu Gothic UI', sans-serif;
        --gutter: clamp(16px, 4vw, 40px);
    }
    * { box-sizing: border-box; }
    html { -webkit-text-size-adjust: 100%; }
    body {
        margin: 0;
        background: var(--bg);
        color: var(--ink);
        font-family: var(--font-body);
        font-size: 15px;
        line-height: 1.7;
    }
    a { color: inherit; }
    button { font: inherit; color: inherit; }
    :focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 4px; }

    /* ---------- ヘッダー ---------- */
    .masthead {
        max-width: 1040px;
        margin: 0 auto;
        padding: clamp(40px, 8vw, 88px) var(--gutter) 28px;
        display: grid;
        grid-template-columns: 1fr auto;
        align-items: end;
        gap: 24px;
    }
    .masthead h1 {
        margin: 0;
        font-size: clamp(30px, 5.4vw, 52px);
        font-weight: 700;
        line-height: 1.2;
        letter-spacing: 0.02em;
    }
    .masthead .lede { margin: 12px 0 0; color: var(--ink-dim); font-size: 14px; max-width: 34em; }
    .masthead .updated { margin: 0; color: var(--muted); font-size: 13px; text-align: right; white-space: nowrap; }
    .masthead .updated time { font-family: var(--font-num); font-size: 20px; font-weight: 500; color: var(--ink-dim); letter-spacing: 0.04em; margin-left: 6px; }

    /* ---------- 絞り込み（上部に固定） ---------- */
    .filters {
        position: sticky;
        top: 0;
        z-index: 10;
        background: rgba(251, 249, 248, 0.94);
        -webkit-backdrop-filter: blur(10px);
        backdrop-filter: blur(10px);
        border-top: 1px solid var(--line);
        border-bottom: 1px solid var(--line);
    }
    .filters-inner {
        max-width: 1040px;
        margin: 0 auto;
        padding: 14px var(--gutter);
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px 28px;
    }
    .filter-group { display: flex; align-items: center; gap: 10px; min-width: 0; }
    .filter-group > .group-name { color: var(--muted); font-size: 12px; white-space: nowrap; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip {
        border: 1px solid var(--line);
        background: transparent;
        color: var(--ink-dim);
        padding: 4px 13px;
        border-radius: 999px;
        font-size: 13px;
        line-height: 1.6;
        cursor: pointer;
        transition: background-color .15s, color .15s, border-color .15s;
    }
    .chip:hover { border-color: var(--ink-dim); color: var(--ink); }
    .chip[aria-pressed="true"] { background: var(--ink); border-color: var(--ink); color: var(--bg); font-weight: 700; }
    .chip.vod[data-vod="Amazon"][aria-pressed="true"] { background: var(--amazon); border-color: var(--amazon); }
    .chip.vod[data-vod="Netflix"][aria-pressed="true"] { background: var(--netflix); border-color: var(--netflix); }
    .chip.vod[data-vod="Disney+"][aria-pressed="true"] { background: var(--disney); border-color: var(--disney); }

    .rate-control { display: flex; align-items: center; gap: 2px; }
    .rate-step {
        width: 30px; height: 30px;
        border: 1px solid var(--line);
        background: transparent;
        color: var(--ink-dim);
        border-radius: 999px;
        cursor: pointer;
        font-size: 15px;
        line-height: 1;
    }
    .rate-step:hover:not(:disabled) { border-color: var(--ink-dim); color: var(--ink); }
    .rate-step:disabled { opacity: .3; cursor: not-allowed; }
    .rate-value { font-family: var(--font-num); font-weight: 800; font-size: 24px; color: var(--accent); min-width: 2.2em; text-align: center; line-height: 1; }
    .rate-note { color: var(--muted); font-size: 12px; margin-left: 6px; white-space: nowrap; }

    .filter-genres { flex-basis: 100%; }
    .filter-genres .chips { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding: 2px; margin: -2px; }
    .filter-genres .chips::-webkit-scrollbar { display: none; }
    .chip { flex-shrink: 0; }

    .result-bar {
        max-width: 1040px;
        margin: 0 auto;
        padding: 18px var(--gutter) 6px;
        display: flex;
        align-items: baseline;
        gap: 16px;
        color: var(--muted);
        font-size: 13px;
    }
    .result-bar strong { font-family: var(--font-num); font-weight: 800; font-size: 22px; color: var(--ink); margin-right: 3px; letter-spacing: 0.02em; }
    .reset {
        border: 0; background: none; padding: 0;
        color: var(--ink-dim);
        text-decoration: underline; text-underline-offset: 3px;
        cursor: pointer; font-size: 13px;
    }
    .reset[hidden] { display: none; }

    /* ---------- ランキング ---------- */
    .ranking { list-style: none; margin: 0 auto; padding: 0 var(--gutter) 96px; max-width: 1040px; }
    .entry {
        display: grid;
        grid-template-columns: 4.2rem 76px 1fr auto;
        grid-template-areas: "rank poster body score";
        gap: 0 20px;
        align-items: start;
        padding: 18px 0;
        border-bottom: 1px solid var(--line);
        content-visibility: auto;
        contain-intrinsic-size: auto 150px;
    }
    .entry[hidden] { display: none; }
    .rank {
        grid-area: rank;
        font-family: var(--font-num);
        font-weight: 800;
        font-size: 44px;
        line-height: .9;
        color: var(--muted);
        text-align: right;
        font-variant-numeric: tabular-nums;
        padding-top: 2px;
    }
    .poster {
        grid-area: poster;
        aspect-ratio: 5 / 7;
        border-radius: 4px;
        overflow: hidden;
        background: var(--raised);
        display: block;
    }
    .poster img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .poster .no-image { display: flex; height: 100%; align-items: center; justify-content: center; color: var(--muted); font-size: 11px; }
    .body { grid-area: body; min-width: 0; }
    .title { margin: 0; font-size: 17px; font-weight: 700; line-height: 1.45; }
    .title a { text-decoration: none; }
    .title a:hover { text-decoration: underline; text-underline-offset: 4px; text-decoration-thickness: 1px; }
    .facts { margin: 6px 0 0; display: flex; flex-wrap: wrap; gap: 4px 14px; color: var(--ink-dim); font-size: 12.5px; }
    .facts .kind { color: var(--ink); }
    .where { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }
    .svc { font-size: 11.5px; font-weight: 700; padding: 1px 8px; border-radius: 3px; border: 1px solid currentColor; line-height: 1.6; }
    .svc[data-vod="Amazon"] { color: var(--amazon); }
    .svc[data-vod="Netflix"] { color: var(--netflix); }
    .svc[data-vod="Disney+"] { color: var(--disney); }

    .score { grid-area: score; text-align: right; min-width: 64px; }
    .score .num { font-family: var(--font-num); font-weight: 800; font-size: 32px; line-height: .95; color: var(--ink); font-variant-numeric: tabular-nums; }
    .score .meter { display: block; margin: 8px 0 0 auto; width: 64px; height: 3px; background: var(--line); border-radius: 2px; overflow: hidden; }
    .score .meter i { display: block; height: 100%; background: var(--ink-dim); }
    .entry.high .score .num { color: var(--accent); }
    .entry.high .score .meter i { background: var(--accent); }

    /* あらすじ（開閉） */
    .synopsis { margin-top: 10px; }
    .synopsis-toggle {
        border: 0; background: none; padding: 2px 0; cursor: pointer;
        color: var(--ink-dim); font-size: 13px;
        display: inline-flex; align-items: center; gap: 6px;
    }
    .synopsis-toggle:hover { color: var(--ink); }
    .synopsis-toggle .caret { display: inline-block; width: 7px; height: 7px; border-right: 1.5px solid currentColor; border-bottom: 1.5px solid currentColor; transform: rotate(45deg) translateY(-2px); transition: transform .25s; }
    .synopsis-toggle[aria-expanded="true"] .caret { transform: rotate(-135deg) translateY(-1px); }
    .synopsis-panel { display: grid; grid-template-rows: 0fr; transition: grid-template-rows .3s ease; }
    .synopsis-panel.open { grid-template-rows: 1fr; }
    .synopsis-panel > div { overflow: hidden; }
    .synopsis-panel p { margin: 8px 0 0; color: var(--ink-dim); font-size: 13.5px; line-height: 1.85; max-width: 42em; }

    /* 1〜3位: 大きな順位と大きなポスターで目立たせる */
    .entry.podium { grid-template-columns: 6.4rem 120px 1fr auto; padding: 28px 0; contain-intrinsic-size: auto 230px; }
    .entry.podium .rank { font-size: 96px; color: var(--accent); letter-spacing: -0.02em; }
    .entry.podium .title { font-size: 21px; }
    .entry.podium .score .num { font-size: 44px; }

    /* 4〜10位: 順位だけ明るくする */
    .entry.top10 .rank { color: var(--ink-dim); }

    .empty { max-width: 1040px; margin: 0 auto; padding: 48px var(--gutter); color: var(--ink-dim); }
    .empty[hidden] { display: none; }

    /* 読み込み時の演出は 1〜3 位の順位が順に灯る 1 回だけ */
    @keyframes light-up { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
    .entry.podium .rank { animation: light-up .7s cubic-bezier(.2,.7,.2,1) both; }
    .entry.podium:nth-child(2) .rank { animation-delay: .12s; }
    .entry.podium:nth-child(3) .rank { animation-delay: .24s; }

    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after { animation: none !important; transition: none !important; }
    }

    /* ---------- スマホ幅 ---------- */
    @media (max-width: 640px) {
        body { font-size: 14px; }
        /* スマホでは絞り込みが画面の大半を占めるので固定しない */
        .filters { position: static; }
        .masthead { grid-template-columns: 1fr; gap: 10px; padding-top: 36px; padding-bottom: 20px; }
        .masthead .updated { text-align: left; }
        .filters-inner { gap: 10px 18px; padding-top: 10px; padding-bottom: 10px; }
        .filter-group { flex-basis: 100%; }
        .filter-group .chips { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding: 2px; margin: -2px; }
        .filter-group .chips::-webkit-scrollbar { display: none; }
        .filter-group > .group-name { min-width: 4.5em; }
        .entry {
            grid-template-columns: 2.6rem 64px 1fr;
            grid-template-areas: "rank poster body" ". poster score";
            gap: 0 12px;
            padding: 14px 0;
        }
        .rank { font-size: 30px; }
        .title { font-size: 15.5px; }
        .score { grid-area: score; text-align: left; display: flex; align-items: center; gap: 10px; margin-top: 8px; }
        .score .num { font-size: 24px; }
        .score .meter { margin: 0; width: 56px; }
        .entry.podium { grid-template-columns: 3.4rem 92px 1fr; padding: 20px 0; }
        .entry.podium .rank { font-size: 56px; }
        .entry.podium .title { font-size: 17px; }
        .entry.podium .score .num { font-size: 30px; }
    }
    </style>
</head>
<body>
    <header class="masthead">
        <div>
            <h1>VOD 統合ランキング</h1>
            <p class="lede">Amazon Prime Video と Netflix の見放題で観られる映画・ドラマを、Filmarks の評価が高い順に並べています。</p>
        </div>
        <p class="updated">最終更新<time datetime="{{ current_date | replace('.', '-') }}">{{ current_date }}</time></p>
    </header>

    <div class="filters">
        <div class="filters-inner">
            <div class="filter-group" role="group" aria-label="種類">
                <span class="group-name">種類</span>
                <div class="chips">
                    {% for type in display_content_types %}
                    <button type="button" class="chip type" data-type="{{ type }}" aria-pressed="false">{{ type }}</button>
                    {% endfor %}
                </div>
            </div>
            <div class="filter-group" role="group" aria-label="配信サービス">
                <span class="group-name">配信</span>
                <div class="chips">
                    {% for vod in available_vods %}
                    <button type="button" class="chip vod" data-vod="{{ vod }}" aria-pressed="false">{{ vod }}</button>
                    {% endfor %}
                </div>
            </div>
            <div class="filter-group" role="group" aria-label="評価の上限">
                <span class="group-name">評価の上限</span>
                <div class="rate-control">
                    <button type="button" class="rate-step" data-delta="-1" aria-label="上限を 1.0 下げる">&laquo;</button>
                    <button type="button" class="rate-step" data-delta="-0.1" aria-label="上限を 0.1 下げる">&lsaquo;</button>
                    <output class="rate-value" id="rate-value" aria-live="polite">5.0</output>
                    <button type="button" class="rate-step" data-delta="0.1" aria-label="上限を 0.1 上げる">&rsaquo;</button>
                    <button type="button" class="rate-step" data-delta="1" aria-label="上限を 1.0 上げる">&raquo;</button>
                    <span class="rate-note">以下を表示</span>
                </div>
            </div>
            <div class="filter-group filter-genres" role="group" aria-label="ジャンル">
                <span class="group-name">ジャンル</span>
                <div class="chips">
                    {% for genre in display_genres %}
                    <button type="button" class="chip genre" data-genre="{{ genre }}" aria-pressed="false">{{ genre }}</button>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>

    <div class="result-bar">
        <span><strong id="result-count">{{ data | length }}</strong>件を表示中</span>
        <button type="button" class="reset" id="reset" hidden>絞り込みを解除</button>
    </div>

    <ol class="ranking">
        {% for index, row in data.iterrows() %}
        {% set rank = loop.index %}
        {% set score = row['評価'] %}
        {% set tier = 'podium' if rank <= 3 else ('top10' if rank <= 10 else '') %}
        {% set synopsis_content = row['あらすじ'] | default('') | trim %}
        {% set has_synopsis = synopsis_content and synopsis_content != "あらすじ情報なし" %}
        {% set has_link = row['詳細URL'] != '#' %}
        {% set genres_text = row['ジャンル'] | replace('ジャンル:', '') %}
        <li class="entry {{ tier }} {% if score >= 4.0 %}high{% endif %}"
            data-genres="{{ row['ジャンルリスト'] | join(',') }}"
            data-vods="{{ row['vod_sources'] | join(',') }}"
            data-type="{{ row['コンテンツタイプ'] }}"
            data-score="{{ score }}">
            <div class="rank" aria-label="{{ rank }}位">{{ rank }}</div>

            {% if has_link %}<a class="poster" href="{{ row['詳細URL'] }}" target="_blank" rel="noopener" tabindex="-1" aria-hidden="true">{% else %}<div class="poster">{% endif %}
                {# 画像が取れなかった行は pandas で NaN（float）になるため、文字列かどうかで判定する #}
                {% if row['画像URL'] is string and row['画像URL'] %}
                <img src="{{ row['画像URL'] }}" alt="" loading="{{ 'eager' if rank <= 6 else 'lazy' }}" decoding="async" width="300" height="420">
                {% else %}
                <span class="no-image">画像なし</span>
                {% endif %}
            {% if has_link %}</a>{% else %}</div>{% endif %}

            <div class="body">
                <h2 class="title">
                    {% if has_link %}<a href="{{ row['詳細URL'] }}" target="_blank" rel="noopener">{{ row['タイトル'] }}</a>{% else %}{{ row['タイトル'] }}{% endif %}
                </h2>
                <p class="facts">
                    <span class="kind">{{ row['コンテンツタイプ'] }}</span>
                    <span>{{ row['公開・初回放送'] }}</span>
                    {% if genres_text != 'N/A' %}<span>{{ genres_text }}</span>{% endif %}
                </p>
                <div class="where">
                    {% for vod in row['vod_sources'] %}
                    <span class="svc" data-vod="{{ vod }}">{{ vod }}</span>
                    {% endfor %}
                </div>
                {% if has_synopsis %}
                <div class="synopsis">
                    <button type="button" class="synopsis-toggle" aria-expanded="false" aria-controls="syn-{{ rank }}"><span class="label">あらすじを読む</span><span class="caret" aria-hidden="true"></span></button>
                    <div class="synopsis-panel" id="syn-{{ rank }}"><div><p>{{ synopsis_content | e }}</p></div></div>
                </div>
                {% endif %}
            </div>

            <div class="score" aria-label="評価 {{ '%.1f' | format(score) }}">
                <div class="num">{{ '%.1f' | format(score) }}</div>
                <span class="meter" aria-hidden="true"><i style="width: {{ (score / 5.0 * 100) | round(1) }}%"></i></span>
            </div>
        </li>
        {% endfor %}
    </ol>
    <p class="empty" id="empty" hidden>条件に合う作品はありません。評価の上限を上げるか、絞り込みを解除してください。</p>

    <script>
    document.addEventListener('DOMContentLoaded', function () {
        const entries = Array.from(document.querySelectorAll('.entry'));
        const chips = Array.from(document.querySelectorAll('.chip'));
        const rateValue = document.getElementById('rate-value');
        const rateSteps = Array.from(document.querySelectorAll('.rate-step'));
        const resultCount = document.getElementById('result-count');
        const resetButton = document.getElementById('reset');
        const emptyNote = document.getElementById('empty');
        const MAX_RATE = 5.0;
        let maxRate = MAX_RATE;

        // 押されているチップの data 属性の値を集める
        function activeValues(kind, attr) {
            return chips
                .filter(c => c.classList.contains(kind) && c.getAttribute('aria-pressed') === 'true')
                .map(c => c.dataset[attr]);
        }

        function updateRateUI() {
            rateValue.textContent = maxRate.toFixed(1);
            rateSteps.forEach(btn => {
                const delta = parseFloat(btn.dataset.delta);
                btn.disabled = delta < 0 ? maxRate <= 0 : maxRate >= MAX_RATE;
            });
        }

        function applyFilters() {
            const genres = activeValues('genre', 'genre');
            const vods = activeValues('vod', 'vod');
            const types = activeValues('type', 'type');
            let shown = 0;

            entries.forEach(entry => {
                const entryGenres = (entry.dataset.genres || '').split(',');
                const entryVods = (entry.dataset.vods || '').split(',');
                const score = parseFloat(entry.dataset.score);
                const visible =
                    (genres.length === 0 || genres.some(g => entryGenres.includes(g))) &&
                    (vods.length === 0 || vods.some(v => entryVods.includes(v))) &&
                    (types.length === 0 || types.includes(entry.dataset.type)) &&
                    (isNaN(score) || score <= maxRate + 1e-9);
                entry.hidden = !visible;
                if (visible) shown++;
            });

            resultCount.textContent = shown.toLocaleString('ja-JP');
            emptyNote.hidden = shown !== 0;
            resetButton.hidden = genres.length + vods.length + types.length === 0 && maxRate === MAX_RATE;
        }

        chips.forEach(chip => chip.addEventListener('click', () => {
            chip.setAttribute('aria-pressed', chip.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
            applyFilters();
        }));

        rateSteps.forEach(btn => btn.addEventListener('click', () => {
            const next = Math.round((maxRate + parseFloat(btn.dataset.delta)) * 10) / 10;
            maxRate = Math.min(MAX_RATE, Math.max(0, next));
            updateRateUI();
            applyFilters();
        }));

        resetButton.addEventListener('click', () => {
            chips.forEach(c => c.setAttribute('aria-pressed', 'false'));
            maxRate = MAX_RATE;
            updateRateUI();
            applyFilters();
        });

        document.querySelectorAll('.synopsis-toggle').forEach(btn => {
            const panel = document.getElementById(btn.getAttribute('aria-controls'));
            const label = btn.querySelector('.label');
            btn.addEventListener('click', () => {
                const open = btn.getAttribute('aria-expanded') !== 'true';
                btn.setAttribute('aria-expanded', String(open));
                panel.classList.toggle('open', open);
                label.textContent = open ? 'あらすじを閉じる' : 'あらすじを読む';
            });
        });

        updateRateUI();
        applyFilters();
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