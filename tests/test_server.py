"""
job-posting-writer/tests/test_server.py
server.py（job_posting_writer.py のロジックを再利用するローカルWeb版）を検証する。

実サーバーをスレッドで起動し、urllib.request で実際にHTTPリクエストを送って
GET / と POST /generate の応答を確認する（標準ライブラリのみ・新規pip依存なし）。

ANTHROPIC_API_KEY はテスト中は明示的に unset した状態で検証する
（ルールベーステンプレート生成のみを通す。実Claude APIは一切呼び出さない）。

実行方法:
    python3 -m unittest discover -s job-posting-writer/tests -v
"""
import json
import os
import sys
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import answer_generate, make_handler  # noqa: E402

JOB_NO_ISSUES = {
    "job_title": "バックエンドエンジニア",
    "company_name": "株式会社サンプルテック",
    "industry": "it",
    "employment_type": "正社員",
    "salary_range": "年収500万〜800万円",
    "work_location": "東京都渋谷区（フルリモート可）",
    "appeal_points": [
        "フルリモート勤務・フレックスタイム制で裁量をもって働ける",
        "残業月10時間以内・年間休日125日",
    ],
    "requirements": ["Python or Goでのサーバーサイド開発実務経験2年以上"],
}

JOB_WITH_FLAGGED_EXPRESSIONS = {
    "job_title": "法人営業マン",
    "company_name": "株式会社サンプル商事",
    "industry": "sales",
    "employment_type": "正社員",
    "work_location": "大阪府大阪市",
    "appeal_points": [
        "未経験からでもインセンティブ制度でしっかり稼げる",
        "30歳以下の方限定・若手が多く活躍中の職場です",
    ],
    "requirements": ["普通自動車運転免許（AT限定可）"],
}

CANDIDATE = {
    "candidate_name": "田中",
    "candidate_highlight": "前職での決済基幹システムをPythonで刷新したご経験",
}


class ServerHTTPTest(unittest.TestCase):
    """実際にHTTPサーバーを起動してエンドツーエンドで検証する。ANTHROPIC_API_KEYは unset のまま。"""

    @classmethod
    def setUpClass(cls):
        cls._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        cls._env_patcher.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)

        handler = make_handler()
        # port=0 で空きポートをOSに割り当ててもらう（他プロセスとの衝突回避）
        cls.httpd = ThreadingHTTPServer(("localhost", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://localhost:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        cls._env_patcher.stop()

    def _post_generate(self, payload: dict) -> tuple[int, dict]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def test_get_index_returns_html_with_form(self):
        with urllib.request.urlopen(f"{self.base_url}/") as res:
            self.assertEqual(res.status, 200)
            self.assertIn("text/html", res.headers.get("Content-Type", ""))
            body = res.read().decode("utf-8")
        self.assertIn("job-posting-writer", body)
        self.assertIn("id=\"appeal_points\"", body)
        self.assertIn("求人票を生成する", body)

    def test_generate_without_api_key_uses_rule_based_mode(self):
        status, body = self._post_generate({"job": JOB_NO_ISSUES})
        self.assertEqual(status, 200)
        self.assertEqual(body["job_mode"], "rule-based")
        self.assertIsNone(body["job_refined"])
        self.assertIn("job_template", body)

    def test_generate_without_flagged_expressions_returns_empty_compliance_issues(self):
        status, body = self._post_generate({"job": JOB_NO_ISSUES})
        self.assertEqual(status, 200)
        self.assertEqual(body["compliance_issues"], [])
        self.assertIn("バックエンドエンジニア", body["job_template"])

    def test_generate_with_flagged_expressions_returns_compliance_issues(self):
        status, body = self._post_generate({"job": JOB_WITH_FLAGGED_EXPRESSIONS})
        self.assertEqual(status, 200)
        categories = {issue["category"] for issue in body["compliance_issues"]}
        self.assertIn("年齢制限表現", categories)
        self.assertIn("性別限定表現", categories)

    def test_generate_without_candidate_skips_scout_message(self):
        status, body = self._post_generate({"job": JOB_NO_ISSUES})
        self.assertEqual(status, 200)
        self.assertIsNone(body["scout_template"])
        self.assertIsNone(body["scout_mode"])

    def test_generate_with_candidate_also_returns_scout_message(self):
        status, body = self._post_generate({"job": JOB_NO_ISSUES, "candidate": CANDIDATE})
        self.assertEqual(status, 200)
        self.assertIsNotNone(body["scout_template"])
        self.assertEqual(body["scout_mode"], "rule-based")
        self.assertIn("田中様", body["scout_template"])
        self.assertIn(JOB_NO_ISSUES["company_name"], body["scout_template"])

    def test_generate_missing_job_returns_400(self):
        status, body = self._post_generate({})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_generate_job_missing_required_field_returns_400(self):
        incomplete_job = {"job_title": "バックエンドエンジニア"}
        status, body = self._post_generate({"job": incomplete_job})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_generate_candidate_missing_highlight_returns_400(self):
        status, body = self._post_generate(
            {"job": JOB_NO_ISSUES, "candidate": {"candidate_name": "田中"}}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_unknown_path_returns_404(self):
        req = urllib.request.Request(f"{self.base_url}/no-such-path")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)


class AnswerGenerateUnitTest(unittest.TestCase):
    """HTTPを介さずロジック単体を検証する。ANTHROPIC_API_KEYは unset のまま。"""

    def setUp(self):
        self._env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patcher.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        self._env_patcher.stop()

    def test_answer_generate_returns_expected_keys(self):
        status, body = answer_generate({"job": JOB_NO_ISSUES})
        self.assertEqual(status, 200)
        self.assertEqual(
            set(body.keys()),
            {
                "job_template",
                "job_refined",
                "job_mode",
                "compliance_issues",
                "scout_template",
                "scout_refined",
                "scout_mode",
            },
        )

    def test_answer_generate_non_dict_payload_is_validation_error(self):
        status, body = answer_generate([])
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_answer_generate_empty_payload_is_validation_error(self):
        status, body = answer_generate({})
        self.assertEqual(status, 400)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
