import unittest

from services.api.app.written_test import (
    ASSESSMENT_ONLY,
    NO_UNIFIED_WRITTEN_TEST,
    NO_WRITTEN_TEST,
    REQUIRED,
    ROLE_SPECIFIC_OR_OPTIONAL,
    classify_written_test,
)


class WrittenTestClassifierTest(unittest.TestCase):
    def test_no_written_test(self):
        result = classify_written_test("本岗位无需笔试，简历通过后直接面试。")
        self.assertEqual(result.status, NO_WRITTEN_TEST)
        self.assertEqual(result.burden, 0)

    def test_no_unified_with_exception(self):
        result = classify_written_test("本届春招不设置统一笔试，美术设计类及个别需要笔试的职位会单独通知。")
        self.assertEqual(result.status, ROLE_SPECIFIC_OR_OPTIONAL)
        self.assertEqual(result.burden, 2)

    def test_no_unified_without_exception(self):
        result = classify_written_test("本项目无统一笔试，网申后进入面试环节。")
        self.assertEqual(result.status, NO_UNIFIED_WRITTEN_TEST)
        self.assertEqual(result.burden, 1)

    def test_required(self):
        result = classify_written_test("招聘流程包含网申、在线笔试、面试和录用。")
        self.assertEqual(result.status, REQUIRED)

    def test_assessment_only(self):
        result = classify_written_test("招聘流程包含网申、在线测评、面试和 offer。")
        self.assertEqual(result.status, ASSESSMENT_ONLY)


if __name__ == "__main__":
    unittest.main()
