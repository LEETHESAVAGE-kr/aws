"""G0 킬체크①: 대회 계정에서 호출 가능한 Bedrock 모델을 확인하고 Converse 1회를 시도한다.

사용: python tools/check_bedrock_access.py [--region ap-northeast-2] [--try-model <modelId>]
자격증명은 AWS CLI 프로필 또는 환경변수로 설정돼 있어야 한다.
"""
from __future__ import annotations

import argparse
import sys

import boto3
from botocore.exceptions import ClientError


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="ap-northeast-2")
    ap.add_argument("--try-model", default=None, help="Converse를 시도할 modelId 또는 추론 프로파일 ID")
    a = ap.parse_args()

    br = boto3.client("bedrock", region_name=a.region)
    print(f"# region = {a.region}")

    print("\n## 파운데이션 모델 (TEXT 출력 · ON_DEMAND/INFERENCE_PROFILE 지원)")
    try:
        models = br.list_foundation_models(byOutputModality="TEXT")["modelSummaries"]
    except ClientError as e:
        print("list_foundation_models 실패:", e)
        return 1
    for m in sorted(models, key=lambda x: x["modelId"]):
        types = ",".join(m.get("inferenceTypesSupported", []))
        print(f"- {m['modelId']}  [{m['providerName']}]  {types}")

    print("\n## 크로스리전 추론 프로파일")
    try:
        profs = br.list_inference_profiles()["inferenceProfileSummaries"]
        for p in profs:
            print(f"- {p['inferenceProfileId']}  ({p.get('status')})")
    except ClientError as e:
        print("list_inference_profiles 실패(권한 없을 수 있음):", e)

    print("\n## 임베딩 모델")
    try:
        emb = br.list_foundation_models(byOutputModality="EMBEDDING")["modelSummaries"]
        for m in emb:
            print(f"- {m['modelId']}")
    except ClientError as e:
        print("실패:", e)

    if a.try_model:
        print(f"\n## Converse 시도: {a.try_model}")
        rt = boto3.client("bedrock-runtime", region_name=a.region)
        try:
            r = rt.converse(
                modelId=a.try_model,
                messages=[{"role": "user", "content": [{"text": "HAZOP 가이드워드 7개를 쉼표로만 나열해."}]}],
                inferenceConfig={"maxTokens": 100, "temperature": 0},
            )
            text = r["output"]["message"]["content"][0]["text"]
            u = r["usage"]
            print("응답:", text.strip())
            print(f"토큰 in/out = {u['inputTokens']}/{u['outputTokens']}, 지연 = {r['metrics']['latencyMs']} ms")
            print("\n✅ G0 킬체크① 통과 — 이 modelId를 config/models.yaml generation.model_id에 기록")
        except ClientError as e:
            print("❌ Converse 실패:", e.response["Error"]["Code"], e.response["Error"]["Message"])
            print("→ 모델 액세스 미승인이면 콘솔 Bedrock > Model access에서 요청, 리전 문제면 --region 변경 또는 프로파일 ID 사용")
            return 2
    else:
        print("\n(다음: 위 목록에서 Claude 계열 ID 하나를 골라 --try-model 로 재실행)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
