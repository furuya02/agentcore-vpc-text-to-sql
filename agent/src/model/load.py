from strands.models import BedrockModel

# ap-northeast-1 では APAC Inference Profile を使用
MODEL_ID = "apac.anthropic.claude-sonnet-4-20250514-v1:0"


def load_model() -> BedrockModel:
    return BedrockModel(model_id=MODEL_ID)
