import unittest

from services.api.app.opportunity_matcher import match_opportunity


class OpportunityMatcherTest(unittest.TestCase):
    def test_technical_resume_ranks_matching_job_higher(self):
        resume = "计算机硕士，熟悉 Python、SQL、机器学习和大模型，目标北京算法研发岗位。"
        technical = {
            "record_type": "job",
            "company_name": "甲公司",
            "industry": "互联网/人工智能",
            "title": "算法工程师",
            "campaign_name": "2027届校园招聘",
            "job_families": ["技术"],
            "majors": ["计算机", "人工智能"],
            "cities": ["北京"],
            "degree_min": "master",
            "source_level": "A",
            "status": "open",
        }
        finance = {
            **technical,
            "industry": "金融",
            "title": "财务会计",
            "job_families": ["职能"],
            "majors": ["会计学"],
            "cities": ["深圳"],
        }
        technical_match = match_opportunity(
            resume,
            technical,
            target_cities=["北京"],
            preferred_job_families=["技术"],
            degree="master",
        )
        finance_match = match_opportunity(
            resume,
            finance,
            target_cities=["北京"],
            preferred_job_families=["技术"],
            degree="master",
        )
        self.assertGreater(technical_match["score"], finance_match["score"])
        self.assertIn("算法", technical_match["matched_keywords"])


if __name__ == "__main__":
    unittest.main()
