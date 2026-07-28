"""
job-posting-writer/tests/test_job_posting_writer.py
job_posting_writer.py の validate_job/validate_candidate/detect_prohibited_expressions/
check_job_compliance/build_headline/build_appeal_section/build_requirements_section/
build_treatment_section/build_job_posting_text/build_scout_opening/build_scout_appeal/
build_scout_cta/build_scout_message_text を検証する。

外部API・ネットワーク依存のない純粋関数のみを対象とする。
_refine_with_claude_haiku（ANTHROPIC_API_KEY使用）は対象外。

実行方法:
    python3 -m unittest discover -s job-posting-writer/tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from job_posting_writer import (  # noqa: E402
    build_appeal_section,
    build_headline,
    build_job_posting_text,
    build_requirements_section,
    build_scout_appeal,
    build_scout_cta,
    build_scout_message_text,
    build_scout_opening,
    build_treatment_section,
    check_job_compliance,
    detect_prohibited_expressions,
    validate_candidate,
    validate_job,
)


def _base_job(**overrides):
    job = {
        "job_title": "バックエンドエンジニア",
        "company_name": "株式会社サンプルテック",
        "appeal_points": ["フルリモート勤務が可能"],
    }
    job.update(overrides)
    return job


def _base_candidate(**overrides):
    candidate = {"candidate_highlight": "前職でのPythonを用いた基幹システム開発経験"}
    candidate.update(overrides)
    return candidate


class ValidateJobTest(unittest.TestCase):
    def test_valid_job_passes_through_required_fields(self):
        result = validate_job(_base_job())
        self.assertEqual(result["job_title"], "バックエンドエンジニア")
        self.assertEqual(result["company_name"], "株式会社サンプルテック")

    def test_missing_job_title_raises_value_error(self):
        job = _base_job()
        del job["job_title"]
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_missing_company_name_raises_value_error(self):
        job = _base_job()
        del job["company_name"]
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_missing_appeal_points_raises_value_error(self):
        job = _base_job()
        del job["appeal_points"]
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_empty_appeal_points_raises_value_error(self):
        job = _base_job(appeal_points=[])
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_appeal_points_not_list_raises_value_error(self):
        job = _base_job(appeal_points="フルリモート勤務が可能")
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_appeal_points_with_empty_string_raises_value_error(self):
        job = _base_job(appeal_points=["良い", ""])
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_job_title_not_str_raises_value_error(self):
        job = _base_job(job_title=12345)
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_job_title_whitespace_only_raises_value_error(self):
        job = _base_job(job_title="   ")
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_company_name_whitespace_only_raises_value_error(self):
        job = _base_job(company_name="  ")
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_default_employment_type_is_full_time(self):
        result = validate_job(_base_job())
        self.assertEqual(result["employment_type"], "正社員")

    def test_explicit_employment_type_is_preserved(self):
        result = validate_job(_base_job(employment_type="業務委託"))
        self.assertEqual(result["employment_type"], "業務委託")

    def test_unknown_employment_type_raises_value_error(self):
        job = _base_job(employment_type="日雇い")
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_default_industry_is_general(self):
        result = validate_job(_base_job())
        self.assertEqual(result["industry"], "general")

    def test_explicit_industry_is_preserved(self):
        result = validate_job(_base_job(industry="it"))
        self.assertEqual(result["industry"], "it")

    def test_unknown_industry_raises_value_error(self):
        job = _base_job(industry="finance")
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_default_requirements_is_empty_list(self):
        result = validate_job(_base_job())
        self.assertEqual(result["requirements"], [])

    def test_requirements_not_list_raises_value_error(self):
        job = _base_job(requirements="経験2年以上")
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_optional_fields_default_to_none(self):
        result = validate_job(_base_job())
        self.assertIsNone(result["salary_range"])
        self.assertIsNone(result["work_location"])

    def test_explicit_optional_fields_are_preserved(self):
        result = validate_job(_base_job(salary_range="年収500万円", work_location="東京都"))
        self.assertEqual(result["salary_range"], "年収500万円")
        self.assertEqual(result["work_location"], "東京都")

    def test_error_message_lists_all_missing_fields(self):
        with self.assertRaises(ValueError) as ctx:
            validate_job({})
        msg = str(ctx.exception)
        self.assertIn("job_title", msg)
        self.assertIn("company_name", msg)
        self.assertIn("appeal_points", msg)


class ValidateCandidateTest(unittest.TestCase):
    def test_valid_candidate_passes_through(self):
        result = validate_candidate(_base_candidate())
        self.assertIn("Python", result["candidate_highlight"])

    def test_missing_highlight_raises_value_error(self):
        with self.assertRaises(ValueError):
            validate_candidate({})

    def test_empty_highlight_raises_value_error(self):
        with self.assertRaises(ValueError):
            validate_candidate({"candidate_highlight": ""})

    def test_whitespace_only_highlight_raises_value_error(self):
        with self.assertRaises(ValueError):
            validate_candidate({"candidate_highlight": "   "})

    def test_highlight_not_str_raises_value_error(self):
        with self.assertRaises(ValueError):
            validate_candidate({"candidate_highlight": 123})

    def test_none_candidate_raises_value_error(self):
        with self.assertRaises(ValueError):
            validate_candidate(None)

    def test_candidate_name_defaults_to_none(self):
        result = validate_candidate(_base_candidate())
        self.assertIsNone(result["candidate_name"])

    def test_explicit_candidate_name_is_preserved(self):
        result = validate_candidate(_base_candidate(candidate_name="田中様"))
        self.assertEqual(result["candidate_name"], "田中様")


class DetectProhibitedExpressionsTest(unittest.TestCase):
    def test_detects_age_restriction_keyword(self):
        findings = detect_prohibited_expressions("30歳以下の方を歓迎します")
        self.assertTrue(any(f["category"] == "年齢制限表現" for f in findings))

    def test_detects_gender_specific_job_title(self):
        findings = detect_prohibited_expressions("法人営業マンを募集")
        self.assertTrue(any(f["category"] == "性別限定表現" for f in findings))

    def test_detects_appearance_keyword(self):
        findings = detect_prohibited_expressions("容姿端麗な方を募集")
        self.assertTrue(any(f["category"] == "身体的条件表現" for f in findings))

    def test_returns_empty_list_when_no_keyword_matches(self):
        self.assertEqual(detect_prohibited_expressions("フルリモート勤務が可能です"), [])

    def test_detects_multiple_categories_in_definition_order(self):
        findings = detect_prohibited_expressions("30歳以下の営業マンを募集")
        categories = [f["category"] for f in findings]
        self.assertEqual(categories, ["年齢制限表現", "性別限定表現"])

    def test_returns_matched_keyword_value(self):
        findings = detect_prohibited_expressions("新卒のみ応募可能")
        self.assertTrue(any(f["keyword"] == "新卒のみ" for f in findings))


class CheckJobComplianceTest(unittest.TestCase):
    def test_clean_job_returns_no_issues(self):
        job = validate_job(_base_job())
        self.assertEqual(check_job_compliance(job), [])

    def test_flagged_appeal_point_is_detected(self):
        job = validate_job(_base_job(appeal_points=["30歳以下の方限定です"]))
        issues = check_job_compliance(job)
        self.assertTrue(any(i["category"] == "年齢制限表現" for i in issues))

    def test_flagged_job_title_is_detected(self):
        job = validate_job(_base_job(job_title="法人営業マン"))
        issues = check_job_compliance(job)
        self.assertTrue(any(i["category"] == "性別限定表現" for i in issues))

    def test_flagged_requirement_is_detected(self):
        job = validate_job(_base_job(requirements=["健康な男女に限る"]))
        issues = check_job_compliance(job)
        self.assertTrue(any(i["category"] == "身体的条件表現" for i in issues))


class BuildHeadlineTest(unittest.TestCase):
    def test_includes_employment_type_job_title_and_lead_point(self):
        job = validate_job(_base_job())
        headline = build_headline(job)
        self.assertIn("正社員", headline)
        self.assertIn("バックエンドエンジニア", headline)
        self.assertIn("フルリモート勤務が可能", headline)

    def test_uses_explicit_employment_type(self):
        job = validate_job(_base_job(employment_type="業務委託"))
        self.assertIn("業務委託", build_headline(job))


class BuildAppealSectionTest(unittest.TestCase):
    def test_includes_all_appeal_points_as_bullets(self):
        job = validate_job(_base_job(appeal_points=["魅力A", "魅力B"]))
        section = build_appeal_section(job)
        self.assertIn("・魅力A", section)
        self.assertIn("・魅力B", section)

    def test_includes_section_header(self):
        job = validate_job(_base_job())
        self.assertIn("この仕事の魅力", build_appeal_section(job))


class BuildRequirementsSectionTest(unittest.TestCase):
    def test_default_text_when_no_requirements(self):
        job = validate_job(_base_job())
        section = build_requirements_section(job)
        self.assertIn("未経験", section)

    def test_lists_explicit_requirements_as_bullets(self):
        job = validate_job(_base_job(requirements=["Python実務経験2年以上"]))
        section = build_requirements_section(job)
        self.assertIn("・Python実務経験2年以上", section)


class BuildTreatmentSectionTest(unittest.TestCase):
    def test_includes_employment_type(self):
        job = validate_job(_base_job())
        self.assertIn("雇用形態: 正社員", build_treatment_section(job))

    def test_default_salary_text_when_unspecified(self):
        job = validate_job(_base_job())
        section = build_treatment_section(job)
        self.assertIn("経験・スキルに応じて決定", section)

    def test_explicit_salary_is_used(self):
        job = validate_job(_base_job(salary_range="年収500万〜800万円"))
        section = build_treatment_section(job)
        self.assertIn("年収500万〜800万円", section)

    def test_work_location_included_when_present(self):
        job = validate_job(_base_job(work_location="東京都渋谷区"))
        self.assertIn("東京都渋谷区", build_treatment_section(job))

    def test_work_location_omitted_when_absent(self):
        job = validate_job(_base_job())
        self.assertNotIn("勤務地:", build_treatment_section(job))


class BuildJobPostingTextTest(unittest.TestCase):
    def test_contains_all_sections(self):
        job = validate_job(_base_job())
        text = build_job_posting_text(job)
        self.assertIn("この仕事の魅力", text)
        self.assertIn("応募資格", text)
        self.assertIn("待遇・勤務条件", text)

    def test_headline_appears_first(self):
        job = validate_job(_base_job())
        text = build_job_posting_text(job)
        self.assertTrue(text.startswith("【正社員】"))


class BuildScoutOpeningTest(unittest.TestCase):
    def test_includes_candidate_name_when_present(self):
        candidate = validate_candidate(_base_candidate(candidate_name="田中"))
        opening = build_scout_opening(candidate)
        self.assertTrue(opening.startswith("田中様、"))

    def test_omits_name_prefix_when_absent(self):
        candidate = validate_candidate(_base_candidate())
        opening = build_scout_opening(candidate)
        self.assertTrue(opening.startswith("はじめまして。"))

    def test_includes_highlight(self):
        candidate = validate_candidate(_base_candidate())
        self.assertIn("Python", build_scout_opening(candidate))


class BuildScoutAppealTest(unittest.TestCase):
    def test_includes_company_name_and_job_title(self):
        job = validate_job(_base_job())
        appeal = build_scout_appeal(job)
        self.assertIn("株式会社サンプルテック", appeal)
        self.assertIn("バックエンドエンジニア", appeal)

    def test_includes_appeal_points_as_bullets(self):
        job = validate_job(_base_job(appeal_points=["魅力A", "魅力B"]))
        appeal = build_scout_appeal(job)
        self.assertIn("・魅力A", appeal)
        self.assertIn("・魅力B", appeal)


class BuildScoutCtaTest(unittest.TestCase):
    def test_includes_company_name(self):
        job = validate_job(_base_job())
        self.assertIn("株式会社サンプルテック", build_scout_cta(job))

    def test_invites_casual_interview(self):
        job = validate_job(_base_job())
        self.assertIn("カジュアル", build_scout_cta(job))


class BuildScoutMessageTextTest(unittest.TestCase):
    def test_contains_opening_appeal_and_cta(self):
        job = validate_job(_base_job())
        candidate = validate_candidate(_base_candidate(candidate_name="田中"))
        text = build_scout_message_text(job, candidate)
        self.assertIn("田中様、", text)
        self.assertIn("バックエンドエンジニア", text)
        self.assertIn("カジュアル", text)

    def test_distinct_for_different_candidates(self):
        job = validate_job(_base_job())
        candidate_a = validate_candidate(_base_candidate(candidate_highlight="経験A"))
        candidate_b = validate_candidate(_base_candidate(candidate_highlight="経験B"))
        text_a = build_scout_message_text(job, candidate_a)
        text_b = build_scout_message_text(job, candidate_b)
        self.assertNotEqual(text_a, text_b)


if __name__ == "__main__":
    unittest.main()
