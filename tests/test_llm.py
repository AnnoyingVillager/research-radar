from app.llm import parse_json_object


def test_parse_json_object_with_fence() -> None:
    result = parse_json_object(
        """```json
        {"title_zh":"测试","key_results":["结果一","结果二"],"novelty_score":0.8}
        ```"""
    )
    assert result is not None
    assert result["title_zh"] == "测试"
    assert result["key_results"] == "结果一；结果二"
    assert result["novelty_score"] == 0.8

