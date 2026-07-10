import unittest

from services.api.app.extraction import infer_job_family


class JobFamilyInferenceTests(unittest.TestCase):
    def test_title_has_priority_over_unrelated_notice_text(self) -> None:
        self.assertEqual(infer_job_family("专职教师", "招聘金融学、经济学等专业毕业生"), "教育")

    def test_generic_research_is_not_finance(self) -> None:
        self.assertEqual(infer_job_family("专家联络处（政策研究岗）", "承担政策研究工作"), "职能")

    def test_manufacturing_product_description_is_not_product_role(self) -> None:
        self.assertEqual(infer_job_family("一通三防岗", "负责煤炭产品加工与矿井通风"), "技术")

    def test_precise_finance_and_product_roles_still_match(self) -> None:
        self.assertEqual(infer_job_family("证券行业研究员", "校招岗位"), "金融")
        self.assertEqual(infer_job_family("AI产品经理", "校招岗位"), "产品")


if __name__ == "__main__":
    unittest.main()
