"""
Model Adapter: ModelArts NLP Sentiment Analysis
华为云 ModelArts NLP 情感分析适配器。
"""

import os
import json
import logging
from typing import Dict, Any

try:
    from modelarts.session import Session
    from modelarts.estimator import Estimator
    MODELARTS_AVAILABLE = True
except ImportError:
    MODELARTS_AVAILABLE = False

logger = logging.getLogger(__name__)


class ModelAdapter:
    """
    华为云 ModelArts NLP 情感分析适配器。
    """

    def __init__(self, endpoint: str = None, region: str = None):
        self.endpoint = endpoint or os.environ.get('MODELARTS_ENDPOINT', '')
        self.region = region or os.environ.get('HUAWEI_CLOUD_REGION', 'cn-north-4')
        self._session = None

    def _get_session(self):
        """获取 ModelArts Session（按需初始化）"""
        if not MODELARTS_AVAILABLE:
            raise RuntimeError(
                "ModelArts SDK 未安装，请先安装：pip install modelarts"
            )
        if self._session is None:
            self._session = Session()
        return self._session

    def detect_sentiment(self, Text: str, LanguageCode: str = 'en') -> Dict[str, Any]:
        """
        情感分析调用。

        Parameters
        ----------
        Text : str
            待分析的文本（英文）
        LanguageCode : str
            语言代码（支持: en, zh）

        Returns
        -------
        dict
            {
                'Sentiment': 'POSITIVE' | 'NEGATIVE' | 'NEUTRAL' | 'MIXED',
                'SentimentScore': {
                    'Positive': float,
                    'Negative': float,
                    'Neutral': float,
                    'Mixed': float
                }
            }
        """
        if not self.endpoint:
            raise ValueError("MODELARTS_ENDPOINT 环境变量未设置")

        if not MODELARTS_AVAILABLE:
            # Fallback：使用 HTTP 调用 ModelArts NLP API
            return self._detect_sentiment_http(Text, LanguageCode)

        # 方式1：使用 ModelArts SDK（生产推荐）
        return self._detect_sentiment_sdk(Text, LanguageCode)

    def _detect_sentiment_sdk(self, Text: str, LanguageCode: str) -> Dict[str, Any]:
        """通过 ModelArts SDK 调用情感分析"""
        session = self._get_session()

        # 调用 ModelArts NLP 情感分析接口
        # 这里需要指定训练好的模型 ID 或使用内置服务
        predictor = Estimator(
            model_id=os.environ.get('MODELARTS_MODEL_ID', ''),
            session=session,
            endpoint=self.endpoint
        )

        result = predictor.predict(Text)

        return self._convert_to_standard_format(result)

    def _detect_sentiment_http(self, Text: str, LanguageCode: str) -> Dict[str, Any]:
        """
        Fallback：通过 HTTP 直接调用 ModelArts NLP REST API。
        适用于开发测试或 SDK 不可用时。
        """
        import requests

        api_path = "/v1/nlp/sentiment"
        url = f"{self.endpoint.rstrip('/')}{api_path}"

        headers = {
            'Content-Type': 'application/json',
            'X-Region': self.region,
        }

        # 从环境变量获取 AK/SK（使用时通过环境变量传递，不硬编码）
        ak = os.environ.get('HUAWEI_ACCESS_KEY', '')
        sk = os.environ.get('HUAWEI_SECRET_KEY', '')

        payload = {
            'text': Text,
            'lang': LanguageCode
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            result = response.json()
            return self._convert_to_standard_format(result)
        except requests.exceptions.RequestException as e:
            logger.error(f"ModelArts API 调用失败: {e}")
            raise RuntimeError(f"情感分析服务调用失败: {e}")

    def _convert_to_standard_format(self, model_result: Any) -> Dict[str, Any]:
        """
        将 ModelArts 返回格式转换为标准情感分析输出格式。
        """
        # ModelArts NLP 情感分析典型输出:
        # {
        #   "label": "positive",
        #   "score": 0.97,
        #   "positive_prob": 0.95,
        #   "negative_prob": 0.02,
        #   "neutral_prob": 0.02,
        #   "mixed_prob": 0.01
        # }

        if isinstance(model_result, str):
            model_result = json.loads(model_result)

        label_map = {
            'positive': 'POSITIVE',
            'negative': 'NEGATIVE',
            'neutral': 'NEUTRAL',
            'mixed': 'MIXED'
        }

        sentiment = label_map.get(
            model_result.get('label', 'neutral').lower(),
            'NEUTRAL'
        )

        return {
            'Sentiment': sentiment,
            'SentimentScore': {
                'Positive': float(model_result.get('positive_prob', 0.0)),
                'Negative': float(model_result.get('negative_prob', 0.0)),
                'Neutral': float(model_result.get('neutral_prob', 0.0)),
                'Mixed': float(model_result.get('mixed_prob', 0.0))
            }
        }


# ── 兼容层 ──────────────────────────────────────────────────────────

class ModelArtsAdapter:
    """
    ModelArts 情感分析适配器。
    用法：client = ModelArtsAdapter()
    之后调用 client.detect_sentiment(...) 即可。
    """
    def detect_sentiment(self, Text: str, LanguageCode: str = 'en') -> Dict[str, Any]:
        adapter = ModelAdapter()
        return adapter.detect_sentiment(Text, LanguageCode)


# 全局工厂函数
def create_comprehend_client(region_name: str = None) -> ModelArtsAdapter:
    return ModelArtsAdapter()
