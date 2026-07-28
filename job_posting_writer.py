#!/usr/bin/env python3
"""job-posting-writer: AI求人票・スカウトメール生成デモ（コンプライアンスチェック付き・ローカルfallback付き）

APIキーなし → 求人情報（職種・会社名・魅力ポイント等）から求人票／スカウトメールを
             ルールベースで組み立てる（ゼロ依存・純Python）。同時に年齢・性別等の
             禁止表現をキーワードベースで検出するコンプライアンスチェックを実行する。
ANTHROPIC_API_KEY設定 → テンプレート結果を土台に、Claude Haiku が業種のトーンに合わせて
             文章を推敲・自然化する（給与・雇用形態・必須条件等の事実は変えない）。

【スコープの注意】本デモは求人票・スカウトメールの「文章生成」のみを対象とする。
候補者の選定・推薦・面接調整等の「あっせん」行為は行わない（職業安定法上の
有料職業紹介事業の許可対象になり得るため、本デモのスコープには含めない）。
"""

import json
import os
import sys

REQUIRED_JOB_FIELDS = ("job_title", "company_name", "appeal_points")

EMPLOYMENT_TYPES = ("正社員", "契約社員", "パート・アルバイト", "業務委託")

INDUSTRIES = {
    "it": "IT・エンジニア",
    "medical": "医療・福祉",
    "sales": "販売・サービス",
    "general": "汎用",
}

# 職業安定法上の求人不受理事由（労働施策総合推進法9条の年齢制限禁止、
# 男女雇用機会均等法5条の性別を理由とする募集・採用禁止）に抵触しうる表現を検出する。
# キーワード一致による簡易検出であり、専門的な法務判断の代替にはならない。
PROHIBITED_PATTERNS = {
    "年齢制限表現": ["歳以下", "歳未満", "若手限定", "新卒のみ", "35歳まで", "40歳まで"],
    "性別限定表現": [
        "営業マン", "看護婦", "男性のみ", "女性のみ", "主婦(夫)歓迎", "スチュワーデス",
        "男性歓迎", "女性歓迎", "男性の方歓迎", "女性の方歓迎", "男性希望", "女性希望",
    ],
    "身体的条件表現": ["容姿端麗", "スタイル良好", "健康な男女", "健康な男性", "健康な女性"],
}


# ---------------------------------------------------------------------------
# 求人情報・候補者情報の検証・正規化
# ---------------------------------------------------------------------------

def validate_job(job: dict) -> dict:
    """必須フィールドの存在・型を確認し、任意フィールドをデフォルト値で補って返す。"""
    missing = [f for f in REQUIRED_JOB_FIELDS if f not in job or not job[f]]
    if missing:
        raise ValueError(f"必須フィールドが不足しています: {', '.join(missing)}")

    if not isinstance(job["job_title"], str) or not job["job_title"].strip():
        raise ValueError("job_titleは空でない文字列である必要があります")

    if not isinstance(job["company_name"], str) or not job["company_name"].strip():
        raise ValueError("company_nameは空でない文字列である必要があります")

    appeal_points = job["appeal_points"]
    if not isinstance(appeal_points, list) or not appeal_points:
        raise ValueError("appeal_pointsは1件以上を含むリストである必要があります")
    if not all(isinstance(p, str) and p.strip() for p in appeal_points):
        raise ValueError("appeal_pointsの各要素は空でない文字列である必要があります")

    employment_type = job.get("employment_type", "正社員") or "正社員"
    if employment_type not in EMPLOYMENT_TYPES:
        raise ValueError(f"employment_typeは{list(EMPLOYMENT_TYPES)}のいずれかである必要があります: {employment_type}")

    industry = job.get("industry", "general") or "general"
    if industry not in INDUSTRIES:
        raise ValueError(f"industryは{list(INDUSTRIES.keys())}のいずれかである必要があります: {industry}")

    requirements = job.get("requirements", []) or []
    if not isinstance(requirements, list) or not all(isinstance(r, str) for r in requirements):
        raise ValueError("requirementsは文字列のリストである必要があります")

    normalized = dict(job)
    normalized["employment_type"] = employment_type
    normalized["industry"] = industry
    normalized["requirements"] = requirements
    normalized.setdefault("salary_range", None)
    normalized.setdefault("work_location", None)
    return normalized


def validate_candidate(candidate: dict) -> dict:
    """候補者情報の必須フィールド（candidate_highlight）を確認し、正規化して返す。"""
    if not candidate or "candidate_highlight" not in candidate or not candidate["candidate_highlight"]:
        raise ValueError("必須フィールドが不足しています: candidate_highlight")
    if not isinstance(candidate["candidate_highlight"], str) or not candidate["candidate_highlight"].strip():
        raise ValueError("candidate_highlightは空でない文字列である必要があります")

    normalized = dict(candidate)
    normalized.setdefault("candidate_name", None)
    return normalized


# ---------------------------------------------------------------------------
# コンプライアンスチェック（ルールベース・APIキー不要）
# ---------------------------------------------------------------------------

def detect_prohibited_expressions(text: str) -> list[dict]:
    """テキストから年齢・性別・身体的条件等の禁止表現を検出する。

    検出順序はPROHIBITED_PATTERNSの定義順（年齢制限表現→性別限定表現→身体的条件表現）で固定。
    """
    findings = []
    for category, keywords in PROHIBITED_PATTERNS.items():
        for keyword in keywords:
            if keyword in text:
                findings.append({"category": category, "keyword": keyword})
    return findings


def check_job_compliance(job: dict) -> list[dict]:
    """求人情報（職種名・魅力ポイント・応募資格）を結合してコンプライアンスチェックする。"""
    text = " ".join([job["job_title"], *job["appeal_points"], *job.get("requirements", [])])
    return detect_prohibited_expressions(text)


# ---------------------------------------------------------------------------
# 求人票組み立て（ルールベース・APIキー不要）
# ---------------------------------------------------------------------------

def build_headline(job: dict) -> str:
    """雇用形態・職種名・トップの魅力ポイントを組み合わせた見出しを組み立てる。"""
    lead_point = job["appeal_points"][0]
    return f"【{job['employment_type']}】{job['job_title']}｜{lead_point}"


def build_appeal_section(job: dict) -> str:
    """魅力ポイントの箇条書きセクションを組み立てる。"""
    lines = ["■ この仕事の魅力"]
    lines.extend(f"・{point}" for point in job["appeal_points"])
    return "\n".join(lines)


def build_requirements_section(job: dict) -> str:
    """応募資格セクションを組み立てる。requirements未指定時は未経験歓迎の既定文を返す。"""
    if not job["requirements"]:
        return "■ 応募資格\n・未経験の方も歓迎します（詳細はお気軽にお問い合わせください）"
    lines = ["■ 応募資格"]
    lines.extend(f"・{req}" for req in job["requirements"])
    return "\n".join(lines)


def build_treatment_section(job: dict) -> str:
    """待遇・勤務条件セクションを組み立てる。給与・勤務地は未指定時に既定文へフォールバックする。"""
    lines = ["■ 待遇・勤務条件", f"雇用形態: {job['employment_type']}"]
    if job.get("salary_range"):
        lines.append(f"給与: {job['salary_range']}")
    else:
        lines.append("給与: 経験・スキルに応じて決定（詳細面談時にご案内）")
    if job.get("work_location"):
        lines.append(f"勤務地: {job['work_location']}")
    return "\n".join(lines)


def build_job_posting_text(job: dict) -> str:
    """求人票全文（見出し＋魅力＋応募資格＋待遇）を組み立てる。"""
    sections = [
        build_headline(job),
        build_appeal_section(job),
        build_requirements_section(job),
        build_treatment_section(job),
    ]
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# スカウトメール組み立て（ルールベース・APIキー不要）
# ---------------------------------------------------------------------------

def build_scout_opening(candidate: dict) -> str:
    """候補者のハイライト経歴に触れた冒頭文を組み立てる。"""
    highlight = candidate["candidate_highlight"]
    name = candidate.get("candidate_name")
    if name:
        return f"{name}様、はじめまして。貴殿の{highlight}という経歴を拝見し、ぜひ一度お話しできればと思いご連絡いたしました。"
    return f"はじめまして。{highlight}という経歴を拝見し、ぜひ一度お話しできればと思いご連絡いたしました。"


def build_scout_appeal(job: dict) -> str:
    """求人の魅力ポイントを候補者向けの文体で組み立てる。"""
    lines = [
        f"{job['company_name']}では現在、「{job['job_title']}」のポジションを募集しております。",
        "特に以下の点で、これまでのご経験を活かしていただけると考えています。",
    ]
    lines.extend(f"・{point}" for point in job["appeal_points"])
    return "\n".join(lines)


def build_scout_cta(job: dict) -> str:
    """カジュアル面談を促すCTA文を組み立てる。"""
    return (
        "まずはカジュアルにお話しする機会をいただけますと幸いです。"
        "ご都合の良い日時をいくつかいただけますでしょうか。"
        f"{job['company_name']}一同、ご返信を心よりお待ちしております。"
    )


def build_scout_message_text(job: dict, candidate: dict) -> str:
    """スカウトメール全文（冒頭＋求人アピール＋CTA）を組み立てる。"""
    sections = [
        build_scout_opening(candidate),
        build_scout_appeal(job),
        build_scout_cta(job),
    ]
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# LLM 推敲（ANTHROPIC_API_KEY 設定時）
# ---------------------------------------------------------------------------

_INDUSTRY_STYLE_HINTS = {
    "it": "エンジニア向けに、技術的な裁量権や技術スタックの魅力が伝わる、落ち着いたトーン。",
    "medical": "誠実で信頼感のある、丁寧なトーン。",
    "sales": "明るく親しみやすい、行動を後押しするトーン。",
    "general": "丁寧語ベースの標準的なビジネストーン。",
}

_DOC_TYPE_FACT_GUARD = {
    "job_posting": "給与・雇用形態・応募資格といった事実は一切変えず、文章のみを推敲してください。",
    "scout_message": "候補者への敬意を保ち、経歴への言及・求人内容といった事実は一切変えず、文章のみを推敲してください。",
}


def _refine_with_claude_haiku(template_text: str, industry: str, doc_type: str, api_key: str) -> str | None:
    """テンプレート文章をClaude Haikuで業種トーンに推敲する。失敗時は None を返す。"""
    try:
        import anthropic  # type: ignore
    except ImportError:
        print("[INFO] anthropic ライブラリ未インストール → 推敲はスキップ", file=sys.stderr)
        return None

    style_hint = _INDUSTRY_STYLE_HINTS.get(industry, _INDUSTRY_STYLE_HINTS["general"])
    fact_guard = _DOC_TYPE_FACT_GUARD.get(doc_type, _DOC_TYPE_FACT_GUARD["job_posting"])
    doc_label = "求人票" if doc_type == "job_posting" else "スカウトメール"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        print(f"[INFO] Claude API: {doc_label}を{style_hint}で推敲中...", file=sys.stderr)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{
                "role": "user",
                "content": (
                    f"あなたは採用広報を担当する人事担当者です。以下はルールベースで組み立てた{doc_label}の"
                    f"下書きです。{fact_guard} {style_hint} という文体基準で自然な日本語に推敲してください。"
                    "出力は推敲後の本文のみとし、前置きや説明は付けないでください。\n\n"
                    f"[下書き]\n{template_text}"
                ),
            }],
        )
        return msg.content[0].text
    except Exception as exc:
        print(f"[警告] Claude API 呼び出し失敗: {exc} → 推敲はスキップ", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def load_input_json(filepath: str) -> dict:
    """求人情報・候補者情報を含むJSONファイルを読み込む。"""
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def generate_job_posting(job: dict) -> tuple[str, str | None, str, list[dict]]:
    """求人情報から求人票を生成する。(template, refined, mode, compliance_issues) を返す。"""
    j = validate_job(job)
    template = build_job_posting_text(j)
    issues = check_job_compliance(j)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    refined = None
    mode = "rule-based"
    if api_key:
        print("[INFO] ANTHROPIC_API_KEY 検出 → 求人票をClaude APIで推敲", file=sys.stderr)
        refined = _refine_with_claude_haiku(template, j["industry"], "job_posting", api_key)
        if refined:
            mode = "rule-based+claude-api"

    return template, refined, mode, issues


def generate_scout_message(job: dict, candidate: dict) -> tuple[str, str | None, str, list[dict]]:
    """求人情報・候補者情報からスカウトメールを生成する。(template, refined, mode, compliance_issues) を返す。"""
    j = validate_job(job)
    c = validate_candidate(candidate)
    template = build_scout_message_text(j, c)
    issues = check_job_compliance(j)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    refined = None
    mode = "rule-based"
    if api_key:
        print("[INFO] ANTHROPIC_API_KEY 検出 → スカウトメールをClaude APIで推敲", file=sys.stderr)
        refined = _refine_with_claude_haiku(template, j["industry"], "scout_message", api_key)
        if refined:
            mode = "rule-based+claude-api"

    return template, refined, mode, issues


def _print_compliance_issues(issues: list[dict]) -> None:
    if not issues:
        print("コンプライアンスチェック: ✅ 年齢・性別・身体的条件等の禁止表現は検出されませんでした")
        return
    print("コンプライアンスチェック: ⚠ 以下の表現が検出されました（職業安定法・均等法上のリスクの可能性・法務専門家への確認を推奨）")
    for issue in issues:
        print(f"  - [{issue['category']}] 「{issue['keyword']}」")


def _print_section(title: str, template: str, refined: str | None, mode: str, issues: list[dict]) -> None:
    sep = "=" * 60
    print(f"\n{sep}")
    print(title)
    print(f"モード : {mode}")
    print(sep)
    _print_compliance_issues(issues)
    print(f"\n## {title}本文\n")
    print(refined if refined else template)


def main() -> None:
    if len(sys.argv) < 2:
        print("使い方: python job_posting_writer.py <求人・候補者情報JSONファイル>", file=sys.stderr)
        print("例:     python job_posting_writer.py sample/job_01_it_engineer_scout.json", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"[エラー] ファイルが見つかりません: {filepath}", file=sys.stderr)
        sys.exit(1)

    try:
        data = load_input_json(filepath)
        job = data.get("job")
        if not job:
            raise ValueError("入力JSONに'job'キーが必要です")
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[エラー] 入力の読み込みに失敗しました: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        template, refined, mode, issues = generate_job_posting(job)
    except ValueError as exc:
        print(f"[エラー] 求人情報が不正です: {exc}", file=sys.stderr)
        sys.exit(1)
    _print_section("求人票", template, refined, mode, issues)

    candidate = data.get("candidate")
    if candidate:
        try:
            s_template, s_refined, s_mode, s_issues = generate_scout_message(job, candidate)
        except ValueError as exc:
            print(f"[エラー] 候補者情報が不正です: {exc}", file=sys.stderr)
            sys.exit(1)
        _print_section("スカウトメール", s_template, s_refined, s_mode, s_issues)


if __name__ == "__main__":
    main()
