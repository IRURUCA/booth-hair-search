"""
ステップ7（フェーズ2）: タグ修正つき髪型検索UI（Gradio）。

フロー:
  画像アップロード → ①タグ抽出（WD Tagger）→ 自動抽出タグを表示
  → ユーザーが手で修正・追加（フェーズ1で判明した"入力側の取りこぼし"をここで救う）
  → ②検索（single + IDF）→ top-10 をサムネ・スコア・BOOTHリンクつきで表示

設計思想（roadmap 2-4）: 完全自動判定を目指さない。「候補を出して人が選ぶ」。
"""
from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from pathlib import Path

import gradio as gr
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from matcher import HairMatcher  # noqa: E402
from booth_client import USER_AGENT  # noqa: E402
from paths import IMAGES_DIR  # noqa: E402

# サムネのローカルキャッシュ。配布物には画像を同梱せず、表示時に BOOTH から取得して
# ここへ貯める（＝画像を再配布しない。各利用者の端末が閲覧分だけ取得）。
THUMB_CACHE = IMAGES_DIR

_thumb_session = requests.Session()
_thumb_session.headers["User-Agent"] = USER_AGENT


def _thumb_path(pid: str, url: str | None, allow_fetch: bool = True):
    """サムネのローカルパスを返す。無ければ BOOTH(pximg) から取得してキャッシュ。

    取得は「閲覧のための都度取得」（クロールではない）。1商品につき1回だけ取得し、
    以後はキャッシュを使う。失敗したら None（呼び出し側はリンクにフォールバック）。
    allow_fetch=False ならキャッシュのみ参照（回線不調時にUIを固めないため）。
    """
    dest = THUMB_CACHE / f"{pid}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    if not allow_fetch or not url or not url.startswith("https://"):
        return None
    try:
        r = _thumb_session.get(url, timeout=8)
        if r.status_code == 200 and r.content:
            THUMB_CACHE.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
            return str(dest)
    except requests.RequestException:
        pass
    return None


def _safe_url(r: dict) -> str:
    """商品リンクを検証。http(s) 以外のスキームが紛れていたら BOOTH の正規URLへ。"""
    url = r.get("url") or ""
    if url.startswith("https://") or url.startswith("http://"):
        return url
    return f"https://booth.pm/ja/items/{r['product_id']}"

print("最新DBを確認中...", file=sys.stderr)
try:
    from db_update import sync_db
    _n = sync_db()
    if _n:
        print(f"  最新DBを取得: {_n} ファイル更新", file=sys.stderr)
except Exception:  # noqa: BLE001
    pass  # ネット不可等は同梱DBで続行

print("モデルとDBをロード中...", file=sys.stderr)
MATCHER = HairMatcher()
print(f"  準備完了: {len(MATCHER.pids)} 商品 / 語彙 {len(MATCHER.vocab)} タグ", file=sys.stderr)


def _editor_path(image):
    """ImageEditor の値（dict）から実際の画像パスを取り出す。切り抜き後は composite。"""
    if isinstance(image, dict):
        return image.get("composite") or image.get("background")
    return image  # 後方互換（文字列パス）


def on_extract(image):
    """画像から髪タグを抽出。強いタグをドロップダウンに、弱いタグも含む全確信度をStateに。

    全generalタグの確信度も別Stateに保存し、検索時のハイブリッド（髪タグ＋全タグ）に使う。
    画像は ImageEditor 経由（ユーザーが✂で頭部を切り抜いてから抽出できる。
    実写や引きのスクショはクロップすると精度が大きく上がる）。
    """
    image_path = _editor_path(image)
    if not image_path:
        return gr.update(value=[]), {}, {}, "画像をアップロードしてください。"
    # 照合には弱いシグナル(>=0.05)も使う（母数が多いDBで効く）。表示・編集は強いタグ(>=0.2)。
    full, all_tags = MATCHER.extract_for_search(image_path, thresh=0.05)
    strong = {t: c for t, c in full.items() if c >= 0.2}
    if not full:
        return gr.update(value=[]), {}, all_tags, "髪タグを検出できませんでした。手で追加してください。"
    md = "**自動抽出タグ**（確信度）: " + (", ".join(f"`{t}` {c:.2f}" for t, c in strong.items()) or "（強いタグなし）")
    md += "\n\n→ 弱い候補タグも内部で照合に使っています。下のタグは**手で修正・追加**できます（例: 三つ編みなら `braid`）。"
    return gr.update(value=list(strong.keys())), full, all_tags, md


PER_PAGE = 10


def _num_pages(total: int) -> int:
    return max(1, (total + PER_PAGE - 1) // PER_PAGE)


import math


def _sorted(results, sort):
    """並び順を適用。複合スコア= 類似度 と 人気/新着 の正規化ブレンド（AND検索）。"""
    if sort == "類似度順" or not results:
        return results

    sims = [r["score"] for r in results]
    smin, smax = min(sims), max(sims)

    def nrm(x, lo, hi):
        return (x - lo) / (hi - lo) if hi > lo else 0.5

    W_SIM = 0.6  # 類似度の比重（複合でも類似を主にする）
    if sort == "類似＋スキ":
        ws = [math.log1p(r.get("wish") or 0) for r in results]
        wmin, wmax = min(ws), max(ws)
        return sorted(results, key=lambda r: -(
            W_SIM * nrm(r["score"], smin, smax)
            + (1 - W_SIM) * nrm(math.log1p(r.get("wish") or 0), wmin, wmax)))
    if sort == "類似＋新着":
        # 公開日時（ISO8601, stats由来）で古→新に並べたランクを新しさスコアにする。
        # 日時が無い商品は product_id 代理（IDはほぼ発行順）で日時あり商品より古い扱い。
        # 生の値でなくランクを使うのは、日時(epoch秒)とIDのスケール差で正規化が壊れないため。
        def order_key(r):
            ts = r.get("published_at") or ""
            if ts:
                try:
                    return (1, datetime.fromisoformat(ts).timestamp())
                except ValueError:
                    pass
            return (0, float(int(r["product_id"])))
        oldest_first = sorted(results, key=order_key)
        rank = {r["product_id"]: i for i, r in enumerate(oldest_first)}
        denom = max(1, len(results) - 1)
        return sorted(results, key=lambda r: -(
            W_SIM * nrm(r["score"], smin, smax)
            + (1 - W_SIM) * rank[r["product_id"]] / denom))
    return results


def _render_page(results, page, sort="類似度順"):
    """ranked results を並び替え、指定ページ(1始まり)をギャラリー＋表HTMLにする。"""
    results = _sorted(results, sort)
    total = len(results)
    npages = _num_pages(total)
    page = max(1, min(int(page), npages))
    start = (page - 1) * PER_PAGE
    chunk = results[start:start + PER_PAGE]

    gallery, rows, page_pids = [], [], []
    fetch_fails = 0  # 2回続けて取得に失敗したら、このページ描画では以降キャッシュのみ
    for offset, r in enumerate(chunk):
        rank = start + offset + 1
        pid = r["product_id"]
        had_cache = (THUMB_CACHE / f"{pid}.jpg").exists()
        img = _thumb_path(pid, r.get("thumbnail_url"), allow_fetch=fetch_fails < 2)
        if img:
            # キャプションは商品名フル（小タイルは見切れる／拡大表示で全部見える）
            gallery.append((img, f"#{rank} {r['name']}"))
            page_pids.append(pid)  # ギャラリー表示順のIDを記録（クリック→商品特定に使う）
        elif (not had_cache and fetch_fails < 2
              and (r.get("thumbnail_url") or "").startswith("https://")):
            fetch_fails += 1  # 実際に取得を試みて失敗したときだけ数える
        wish = r.get("wish") or 0
        wish_cell = f"♡{wish:,}" if wish else "―"
        rows.append(
            f"<tr><td style='white-space:nowrap'>#{rank}</td>"
            f"<td style='white-space:nowrap'>{r['score']:.3f}</td>"
            f"<td style='white-space:nowrap'>{wish_cell}</td>"
            f"<td><a href='{html.escape(_safe_url(r))}' target='_blank'>{html.escape(r['name'])}</a></td></tr>"
        )
    if total == 0:
        return [], "該当なし。タグやキーワードの条件を緩めてください。", []
    header = (f"<b>{total}件中 {start + 1}〜{min(start + PER_PAGE, total)}位</b>"
              f"　（ページ {page} / {npages}）")
    table_html = (
        header +
        "<table style='width:100%;border-collapse:collapse' border='1' cellpadding='4'>"
        "<tr><th>順位</th><th>類似</th><th>スキ</th><th style='width:80%'>商品名（クリックでBOOTH）</th></tr>"
        + "".join(rows) + "</table>"
        "<p style='color:#888;font-size:0.85em'>※ サムネ（左）をクリックすると、その商品のBOOTHリンクが上に出ます。"
        "類似スコアは「見つけた確度」ではありません（人が目で選んでください）。</p>"
    )
    return gallery, table_html, page_pids


def on_tags_change(selected_tags):
    """入力タグをWDタグに解決（カナ等を自動変換）。ドロップダウン値と注記を返す。"""
    if not selected_tags:
        return gr.update(), ""
    final, notes, unres = [], [], []
    for tok in selected_tags:
        resolved, _ = MATCHER.resolve_tags([tok])
        if resolved:
            rt = resolved[0]
            if rt not in final:
                final.append(rt)
            if rt != tok:
                notes.append(f"`{tok}`→`{rt}`")
        else:
            unres.append(tok)
    if final == list(selected_tags):
        return gr.update(), ""  # 既に正規形（ループ防止）
    msg = ""
    if notes:
        msg = "自動変換: " + "、".join(notes)
    if unres:
        msg += ("　/　" if msg else "") + "未対応（無視）: " + "、".join(f"`{u}`" for u in unres)
    return gr.update(value=final), msg


def _filtered(results, tag_only, selected_tags, keyword=""):
    """表示時の絞り込み（Stateには常に全ランキングを保持）。
    - tag_only: 選択タグを1つも持たない商品を除外
    - keyword: 商品名に含まれる語で絞り込み（大小文字・全半角は区別せずゆるめに）
    """
    out = results or []
    if tag_only and selected_tags:
        out = [r for r in out if MATCHER.contains_any(r["product_id"], selected_tags)]
    kw = (keyword or "").strip()
    if kw:
        # 商品名だけでなくBOOTHタグも見る（アバター名は名前に無くタグにある事が多い）
        out = [r for r in out if MATCHER.keyword_hit(r["product_id"], r.get("name") or "", kw)]
    return out


def on_search(selected_tags, detected, all_tags_state, tag_only, sort, keyword):
    """検索してランキング全体を State に入れ、1ページ目を描画。ページ選択肢も更新。"""
    if not selected_tags:
        return [], gr.update(choices=[1], value=1), [], "タグを1つ以上選んでください。", []
    detected = detected or {}
    # クエリ組み立て: 弱いタグ(検出済み<0.2)はそのまま照合に使う。
    #   ユーザーが外した強タグは除外、足したタグは確信度1.0。
    query = {}
    for t, c in detected.items():
        if c >= 0.2 and t not in selected_tags:
            continue  # 表示されていた強タグをユーザーが外した
        query[t] = float(c)
    for t in selected_tags:
        if t not in detected:
            query[t] = 1.0  # ユーザーが手で足した
    # DBにある限り全件をランキング（ページで手繰れるように）。絞り込みは表示時に適用。
    # 画像がある場合は全タグ側もクエリに渡してハイブリッド（タグのみ検索は従来どおり）
    pool = MATCHER.search(query, top_k=len(MATCHER.pids),
                          full_query=all_tags_state or None)
    view = _filtered(pool, tag_only, selected_tags, keyword)
    npages = _num_pages(len(view))
    gallery, table_html, pids = _render_page(view, 1, sort)
    return pool, gr.update(choices=list(range(1, npages + 1)), value=1), gallery, table_html, pids


def goto(results, page, sort, tag_only, selected_tags, keyword):
    """State のランキングから指定ページを描画（◀▶・ページ選択の共通処理）。"""
    view = _filtered(results, tag_only, selected_tags, keyword)
    npages = _num_pages(len(view))
    page = max(1, min(int(page), npages))
    gallery, table_html, pids = _render_page(view, page, sort)
    return gr.update(value=page), gallery, table_html, pids


def on_redisplay(results, tag_only, selected_tags, sort, keyword):
    """並び順・絞り込み・キーワードの変更を即反映（再検索なし）。1ページ目へ。"""
    view = _filtered(results, tag_only, selected_tags, keyword)
    npages = _num_pages(len(view))
    gallery, table_html, pids = _render_page(view, 1, sort)
    return gr.update(choices=list(range(1, npages + 1)), value=1), gallery, table_html, pids


def on_pick(page_pids, evt: gr.SelectData):
    """サムネクリック→その商品のBOOTHリンクを上部に表示（どのサムネがどれか明確に）。"""
    if not page_pids or evt.index is None or evt.index >= len(page_pids):
        return ""
    p = MATCHER.product_by_id.get(page_pids[evt.index], {})
    url = _safe_url({"url": p.get("url"), "product_id": page_pids[evt.index]})
    name = html.escape(p.get("name", ""))
    return (
        "<div style='padding:8px 10px;border:1px solid #4a90d9;border-radius:6px;margin:2px 0'>"
        f"🖼 選択中: <b>{name}</b>　"
        f"<a href='{html.escape(url)}' target='_blank'>🛒 BOOTHで開く ↗</a></div>"
    )


# サムネ拡大(lightbox)が開いている間だけ #pickbox を表示するJS。
# Gradioに拡大の開閉イベントが無いため、ギャラリー内に拡大ビュー(.preview)が
# 出現/消滅するのをMutationObserverで監視して display を切り替える。
_PREVIEW_JS = """
() => {
  const box = document.getElementById('pickbox');
  const gal = document.getElementById('cand_gallery');
  if (!box || !gal) return;
  const sync = () => {
    const preview = gal.querySelector('.preview');
    box.style.display = preview ? '' : 'none';
    if (!preview) return;
    // 拡大表示の下に出る「#N 商品名」キャプションもハイパーリンク化する
    const a = box.querySelector('a');
    const url = a ? a.getAttribute('href') : null;
    if (!url) return;
    const cap = [...preview.querySelectorAll('*')].find(
      el => el.children.length === 0 && /^\\s*#\\d/.test(el.textContent || ''));
    if (!cap) return;
    if (cap.tagName === 'A') {
      // リンク化済み: 拡大中に別サムネへ切り替えた場合に備え href を追従させる
      if (cap.getAttribute('href') !== url) cap.setAttribute('href', url);
      return;
    }
    const link = document.createElement('a');
    link.href = url; link.target = '_blank';
    link.style.color = 'inherit'; link.style.textDecoration = 'underline';
    // テキストノードを作り直さず<a>内へ移動する（Svelteのテキスト更新を生かし、
    // 拡大中に別サムネへ切り替えたときキャプション文言が古いまま残るのを防ぐ）
    while (cap.firstChild) link.appendChild(cap.firstChild);
    cap.appendChild(link);
  };
  new MutationObserver(sync).observe(gal, {childList: true, subtree: true, attributes: true});
  // 選択商品のリンクは on_pick の応答で遅れて #pickbox に入るため、こちらの変化でも再実行する
  new MutationObserver(sync).observe(box, {childList: true, subtree: true});
  sync();
}
"""


with gr.Blocks(title="画像から探す髪型検索ツール") as demo:
    gr.Markdown(
        "# 画像から探す髪型検索ツール\n"
        "アバターのスクショや髪型画像から、BOOTHの似た髪型商品を探します。\n"
        "**タグは手で直せます**——自動抽出が取りこぼした特徴（三つ編み等）を足すと精度が上がります。"
    )
    detected_state = gr.State({})
    all_tags_state = gr.State({})  # 画像の全generalタグ確信度（ハイブリッド検索の全タグ側クエリ）
    results_state = gr.State([])
    page_pids_state = gr.State([])  # 現在ギャラリーに出ている商品IDの並び（クリック特定用）
    with gr.Row():
        with gr.Column(scale=1):
            # ImageEditor: 貼り付け後に✂（クロップ）で頭部を切り抜ける。
            # 実写や引きのスクショは、髪が大きく写るよう切り抜くと精度が上がる
            image = gr.ImageEditor(
                type="filepath", label="画像をアップロード（✂で切り抜き→自動で再抽出）",
                height=380, sources=["upload", "clipboard"],  # ウェブカメラは無効
                transforms=("crop",), brush=False, eraser=False, layers=False,
                # 既定の image_mode="RGBA" だと JPG入力→RGBA変換→JPEG保存で
                # "cannot write mode RGBA as JPEG" になる（Gradio 6.22）。
                # タガーは透過を白合成するので RGB で十分
                image_mode="RGB", format="png",
            )
            extract_btn = gr.Button("① タグ抽出", variant="secondary")
            info = gr.Markdown()
            tags = gr.Dropdown(
                choices=MATCHER.vocab, multiselect=True, allow_custom_value=True,
                label="髪形状タグ（修正・追加可 / カナOK）",
                info="「ツインテール」「ボブ」「みつあみ」等の日本語で入れても自動変換します。",
            )
            tag_note = gr.Markdown()
            tag_only = gr.Checkbox(
                label="選択タグを含む商品だけ", value=False,
                info="ONで選んだタグを1つも持たない商品を除外（即反映）。",
            )
            search_btn = gr.Button("② 検索", variant="primary")
        with gr.Column(scale=2):
            sort = gr.Radio(
                choices=["類似度順", "類似＋スキ", "類似＋新着"], value="類似度順", label="並び順",
                info="複合順=似た候補の中で、人気(スキ数)や新しさを加味して並べ替え。",
            )
            keyword = gr.Textbox(
                label="キーワードでさらに絞り込み（任意）",
                placeholder="例: ウルフ / アバター名（しなの等）/ bob（商品名・BOOTHタグを検索・即反映）",
            )
            with gr.Row():
                prev_btn = gr.Button("◀ 前の10件", scale=1)
                page_dd = gr.Dropdown(choices=[1], value=1, label="ページ (10件ずつ)", scale=2)
                next_btn = gr.Button("次の10件 ▶", scale=1)
            # サムネ拡大中だけ表示（下部のload JSがlightbox開閉を監視して出し入れ）
            pick_html = gr.HTML(elem_id="pickbox")
            # height固定だとギャラリー内スクロールが発生して1段目が切れる → 自動高さで
            # 2行(10件)を丸ごと表示する。キャプションに商品名を出す
            gallery = gr.Gallery(label="候補（サムネクリックでリンク表示）", columns=5, rows=2,
                                 height="auto", object_fit="cover",
                                 buttons=["download", "fullscreen"],  # share は消す
                                 elem_id="cand_gallery")
            result_html = gr.HTML()

    redisplay_in = [results_state, tag_only, tags, sort, keyword]
    redisplay_out = [page_dd, gallery, result_html, page_pids_state]
    goto_in = [results_state, page_dd, sort, tag_only, tags, keyword]

    extract_btn.click(on_extract, [image], [tags, detected_state, all_tags_state, info])
    image.upload(on_extract, [image], [tags, detected_state, all_tags_state, info])
    # ✂で切り抜きを確定(apply)したら自動で再抽出（クロップ→即タグ更新）
    image.apply(on_extract, [image], [tags, detected_state, all_tags_state, info])
    tags.change(on_tags_change, [tags], [tags, tag_note])
    search_btn.click(on_search, [tags, detected_state, all_tags_state, tag_only, sort, keyword],
                     [results_state, page_dd, gallery, result_html, page_pids_state])
    sort.change(on_redisplay, redisplay_in, redisplay_out)
    tag_only.change(on_redisplay, redisplay_in, redisplay_out)
    keyword.change(on_redisplay, redisplay_in, redisplay_out)
    page_dd.change(goto, goto_in, [page_dd, gallery, result_html, page_pids_state])
    prev_btn.click(lambda res, p, s, f, t, k: goto(res, int(p) - 1, s, f, t, k),
                   goto_in, [page_dd, gallery, result_html, page_pids_state])
    next_btn.click(lambda res, p, s, f, t, k: goto(res, int(p) + 1, s, f, t, k),
                   goto_in, [page_dd, gallery, result_html, page_pids_state])
    gallery.select(on_pick, [page_pids_state], [pick_html])
    demo.load(None, None, None, js=_PREVIEW_JS)  # lightbox開閉に応じて選択中表示を出し入れ


if __name__ == "__main__":
    # server_port=None → 空きポートを自動探索（7860が使用中でも落ちない）。
    # inbrowser=True → 選ばれたポートを既定ブラウザで自動オープン。
    demo.launch(server_name="127.0.0.1", server_port=None,
                allowed_paths=[str(IMAGES_DIR)], inbrowser=True)
