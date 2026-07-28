#!/usr/bin/env python3
"""
job-posting-writer/server.py
job-posting-writer CLI（job_posting_writer.py）をブラウザから使える最小Web版にするローカルサーバー。

目的:
  job_posting_writer.py はターミナル操作（python3 job_posting_writer.py <ファイル>）でしか動かないため、
  非エンジニアのクライアント（人事担当者・採用代行事業者）に実演を見せられない。
  本サーバーは job_posting_writer.py の求人票組み立て・コンプライアンスチェック・スカウトメール生成
  ロジック（generate_job_posting/generate_scout_message）をそのまま再利用し、ブラウザの入力フォーム
  （職種名・会社名・魅力ポイント等、任意で候補者経歴ハイライト）から求人票・スカウトメールを生成する
  UIを提供する（ai-me/server.py・review-reply-writer/server.py と同型）。
  コンプライアンスチェック（禁止表現検出）は本デモの差別化要素のため、検出結果を常に明示的に表示する。

依存: 標準ライブラリのみ（http.server）。新規pipパッケージは追加しない。
ANTHROPIC_API_KEY 未設定でも job_posting_writer.py と同じルールベーステンプレートのみで動作する。

使い方:
    python3 server.py
    python3 server.py --port 8771
    → ブラウザで http://localhost:8771 を開き、求人情報を入力する

他プロセス・テストからの利用:
    from server import answer_generate
    status, result = answer_generate({"job": {...}, "candidate": {...}})
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from job_posting_writer import (  # noqa: E402
    EMPLOYMENT_TYPES,
    INDUSTRIES,
    generate_job_posting,
    generate_scout_message,
)

DEFAULT_PORT = 8771


def answer_generate(payload: dict) -> tuple[int, dict]:
    """POST /generate のロジック本体。(HTTPステータス, レスポンスdict) を返す。

    job_posting_writer.py の generate_job_posting()/generate_scout_message() をそのまま呼び出し、
    validate_job()/validate_candidate() が投げる ValueError（必須フィールド不足・値不正等）を400に変換する。
    candidate は任意。渡されない（None/未指定/空dict）場合はスカウトメールを生成せずスキップする。
    """
    if not isinstance(payload, dict):
        return 400, {"error": "求人情報の形式が不正です。"}

    job = payload.get("job")
    if not isinstance(job, dict) or not job:
        return 400, {"error": "job情報が必要です。"}

    try:
        job_template, job_refined, job_mode, issues = generate_job_posting(job)
    except ValueError as exc:
        return 400, {"error": str(exc)}

    result = {
        "job_template": job_template,
        "job_refined": job_refined,
        "job_mode": job_mode,
        "compliance_issues": issues,
        "scout_template": None,
        "scout_refined": None,
        "scout_mode": None,
    }

    candidate = payload.get("candidate")
    if candidate:
        try:
            scout_template, scout_refined, scout_mode, _ = generate_scout_message(job, candidate)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        result["scout_template"] = scout_template
        result["scout_refined"] = scout_refined
        result["scout_mode"] = scout_mode

    return 200, result


def render_index_html() -> bytes:
    industry_options = "".join(
        f'<option value="{key}">{label}</option>' for key, label in INDUSTRIES.items()
    )
    employment_type_options = "".join(
        f'<option value="{label}">{label}</option>' for label in EMPLOYMENT_TYPES
    )
    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>job-posting-writer — AI求人票・スカウトメール生成デモ</title>
<style>
  body {{ font-family: -apple-system, "Hiragino Sans", sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; background: #f7f7f8; }}
  h1 {{ font-size: 18px; }}
  p.lead {{ color: #555; font-size: 14px; }}
  label {{ display: block; margin-top: 12px; font-size: 13px; color: #333; }}
  select, input[type=text], textarea {{ width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; font-size: 14px; margin-top: 4px; }}
  textarea {{ height: 70px; }}
  textarea.tall {{ height: 90px; }}
  .row {{ display: flex; gap: 12px; }}
  .row > div {{ flex: 1; }}
  .hint {{ font-size: 12px; color: #888; }}
  button {{ margin-top: 16px; padding: 10px 18px; border: none; border-radius: 6px; background: #2d6cdf; color: #fff; cursor: pointer; }}
  button:disabled {{ background: #999; cursor: default; }}
  #result {{ margin-top: 20px; background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 16px; display: none; }}
  #result.error {{ border-color: #d33; color: #d33; }}
  .meta {{ font-size: 12px; color: #666; margin-bottom: 10px; }}
  h2 {{ font-size: 15px; margin: 16px 0 8px; }}
  .doc-text {{ white-space: pre-wrap; line-height: 1.7; }}
  .empty-note {{ color: #888; font-size: 13px; }}
  .compliance {{ padding: 10px; border-radius: 6px; margin-bottom: 12px; font-size: 13px; }}
  .compliance.ok {{ background: #eaf6ea; color: #1a6b1a; }}
  .compliance.flagged {{ background: #fdecea; color: #a12a1f; }}
  .compliance ul {{ margin: 6px 0 0; padding-left: 18px; }}
</style>
</head>
<body>
<h1>job-posting-writer デモ — 求人情報を入力して求人票・スカウトメールを生成</h1>
<p class="lead">職種名・会社名・魅力ポイント等を入力して「求人票を生成する」を押してください。APIキー不要でルールベースの求人票が常に生成され、年齢・性別・身体的条件の禁止表現も同時にチェックします。候補者の経歴ハイライトも入力すると、スカウトメールもあわせて生成します。ANTHROPIC_API_KEY設定時は業種トーンに推敲した文章も追加生成します。</p>

<label for="job_title">職種名（必須）
  <input type="text" id="job_title" placeholder="バックエンドエンジニア">
</label>

<div class="row">
  <div>
    <label for="company_name">会社名（必須）
      <input type="text" id="company_name" placeholder="株式会社サンプルテック">
    </label>
  </div>
  <div>
    <label for="industry">業種
      <select id="industry">{industry_options}</select>
    </label>
  </div>
</div>

<div class="row">
  <div>
    <label for="employment_type">雇用形態
      <select id="employment_type">{employment_type_options}</select>
    </label>
  </div>
  <div>
    <label for="salary_range">給与（任意）
      <input type="text" id="salary_range" placeholder="年収500万〜800万円">
    </label>
  </div>
</div>

<label for="work_location">勤務地（任意）
  <input type="text" id="work_location" placeholder="東京都渋谷区（フルリモート可）">
</label>

<label for="appeal_points">この仕事の魅力ポイント（必須・1行に1件）
  <textarea id="appeal_points" class="tall" placeholder="フルリモート勤務・フレックスタイム制で裁量をもって働ける&#10;残業月10時間以内・年間休日125日"></textarea>
</label>

<label for="requirements">応募資格（任意・1行に1件・未入力なら未経験歓迎の既定文になります）
  <textarea id="requirements" placeholder="Python or Goでのサーバーサイド開発実務経験2年以上"></textarea>
</label>

<div class="row">
  <div>
    <label for="candidate_name">候補者名（任意・スカウトメール生成時のみ使用）
      <input type="text" id="candidate_name" placeholder="田中">
    </label>
  </div>
  <div>
    <label for="candidate_highlight">候補者の経歴ハイライト（任意・入力するとスカウトメールも生成）
      <input type="text" id="candidate_highlight" placeholder="前職での決済基幹システムをPythonで刷新したご経験">
    </label>
  </div>
</div>
<p class="hint">候補者の経歴ハイライトを入力すると、上の求人情報を土台にしたスカウトメールもあわせて生成します。</p>

<button type="button" id="send">求人票を生成する</button>
<div id="result"></div>
<script>
const jobTitleEl = document.getElementById('job_title');
const companyNameEl = document.getElementById('company_name');
const industryEl = document.getElementById('industry');
const employmentTypeEl = document.getElementById('employment_type');
const salaryRangeEl = document.getElementById('salary_range');
const workLocationEl = document.getElementById('work_location');
const appealPointsEl = document.getElementById('appeal_points');
const requirementsEl = document.getElementById('requirements');
const candidateNameEl = document.getElementById('candidate_name');
const candidateHighlightEl = document.getElementById('candidate_highlight');
const send = document.getElementById('send');
const resultEl = document.getElementById('result');

function escapeHtml(s) {{
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}}

function linesToList(text) {{
  return text.split('\\n').map(s => s.trim()).filter(Boolean);
}}

function renderCompliance(issues) {{
  if (!issues || issues.length === 0) {{
    return '<div class="compliance ok">✅ 年齢・性別・身体的条件等の禁止表現は検出されませんでした</div>';
  }}
  const items = issues.map(i => `<li>[${{escapeHtml(i.category)}}] 「${{escapeHtml(i.keyword)}}」</li>`).join('');
  return `<div class="compliance flagged">⚠ 以下の表現が検出されました（職業安定法・均等法上のリスクの可能性・法務専門家への確認を推奨）<ul>${{items}}</ul></div>`;
}}

send.addEventListener('click', async () => {{
  const jobTitle = jobTitleEl.value.trim();
  const companyName = companyNameEl.value.trim();
  const appealPoints = linesToList(appealPointsEl.value);
  if (!jobTitle || !companyName || appealPoints.length === 0) return;
  send.disabled = true;
  resultEl.style.display = 'none';
  resultEl.classList.remove('error');

  const payload = {{
    job: {{
      job_title: jobTitle,
      company_name: companyName,
      industry: industryEl.value,
      employment_type: employmentTypeEl.value,
      salary_range: salaryRangeEl.value.trim() || null,
      work_location: workLocationEl.value.trim() || null,
      appeal_points: appealPoints,
      requirements: linesToList(requirementsEl.value),
    }},
  }};
  const candidateHighlight = candidateHighlightEl.value.trim();
  if (candidateHighlight) {{
    payload.candidate = {{
      candidate_name: candidateNameEl.value.trim() || null,
      candidate_highlight: candidateHighlight,
    }};
  }}

  try {{
    const res = await fetch('/generate', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(payload)
    }});
    const data = await res.json();
    if (!res.ok) {{
      resultEl.classList.add('error');
      resultEl.textContent = data.error || '求人票の生成に失敗しました。';
      resultEl.style.display = 'block';
      return;
    }}

    let html = `<div class="meta">求人票モード ${{data.job_mode}}</div>`;
    html += renderCompliance(data.compliance_issues);
    html += '<h2>求人票（ルールベース）</h2>';
    html += `<div class="doc-text">${{escapeHtml(data.job_template)}}</div>`;
    html += '<h2>求人票（Claude推敲）</h2>';
    if (data.job_refined) {{
      html += `<div class="doc-text">${{escapeHtml(data.job_refined)}}</div>`;
    }} else {{
      html += '<div class="empty-note">(ANTHROPIC_API_KEY 未設定のため、推敲文は生成されていません。ルールベースのみ)</div>';
    }}

    if (data.scout_template) {{
      html += `<div class="meta">スカウトメールモード ${{data.scout_mode}}</div>`;
      html += '<h2>スカウトメール（ルールベース）</h2>';
      html += `<div class="doc-text">${{escapeHtml(data.scout_template)}}</div>`;
      html += '<h2>スカウトメール（Claude推敲）</h2>';
      if (data.scout_refined) {{
        html += `<div class="doc-text">${{escapeHtml(data.scout_refined)}}</div>`;
      }} else {{
        html += '<div class="empty-note">(ANTHROPIC_API_KEY 未設定のため、推敲文は生成されていません。ルールベースのみ)</div>';
      }}
    }}

    resultEl.innerHTML = html;
    resultEl.style.display = 'block';
  }} catch (err) {{
    resultEl.classList.add('error');
    resultEl.textContent = '通信エラーが発生しました。サーバーが起動しているか確認してください。';
    resultEl.style.display = 'block';
  }} finally {{
    send.disabled = false;
  }}
}});
</script>
</body>
</html>
"""
    return html.encode("utf-8")


def make_handler():
    """クロージャで束縛する状態がないため store 等は持たないが、
    ai-me/review-reply-writer と同型のインターフェース（make_handler() が Handler を返す）を維持する。
    """

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # 標準エラー出力への毎リクエストログを抑制（動作確認時のノイズ削減）

        def _write_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                body = render_index_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path != "/generate":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                payload = {}
            status, result = answer_generate(payload)
            self._write_json(status, result)

    return Handler


def run(port: int = DEFAULT_PORT) -> None:
    handler = make_handler()
    server = ThreadingHTTPServer(("localhost", port), handler)
    print(f"job-posting-writer Web版を起動しました: http://localhost:{port}")
    print("Ctrl+C で終了します。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def parse_port(argv: list[str]) -> int:
    port = DEFAULT_PORT
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
    return port


if __name__ == "__main__":
    run(parse_port(sys.argv[1:]))
