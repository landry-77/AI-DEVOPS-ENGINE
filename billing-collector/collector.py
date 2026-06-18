import os
import json
import time
import requests
from datetime import datetime, timedelta

API_GATEWAY = os.getenv("API_GATEWAY_URL", "http://django-dashboard:8000")
INTERNAL_TOKEN = os.getenv("INTERNAL_BILLING_TOKEN", "LocalSecretInternalTokenBetweenServices")
COLLECT_INTERVAL = int(os.getenv("COLLECT_INTERVAL_SECONDS", "86400"))

PROVIDERS = []

if os.getenv("AWS_ACCESS_KEY_ID"):
    PROVIDERS.append("aws")
if os.getenv("GCP_SERVICE_ACCOUNT_JSON"):
    PROVIDERS.append("gcp")


def collect_aws():
    try:
        import boto3
        client = boto3.client(
            "cost-explorer",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name="us-east-1",
        )
        end = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        resp = client.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="DAILY",
            Metrics=["UnblendedCost", "UsageQuantity"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        records = []
        for group in resp["ResultsByTime"][0]["Groups"]:
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            if amount > 0:
                records.append({
                    "organization_name": os.getenv("ORG_NAME", "default"),
                    "provider": "aws",
                    "service": group["Keys"][0][:100],
                    "region": "us-east-1",
                    "cost": round(amount, 6),
                    "usage_quantity": float(group["Metrics"]["UsageQuantity"]["Amount"]),
                    "usage_unit": "units",
                    "recorded_at": start,
                })
        return records
    except Exception as e:
        print(f"[AWS] Collection failed: {e}")
        return []


def collect_gcp():
    try:
        from google.cloud import billing
        client = billing.CloudBillingClient()
        records = []
        return records
    except Exception as e:
        print(f"[GCP] Collection failed: {e}")
        return []


def send_records(records):
    if not records:
        return
    try:
        resp = requests.post(
            f"{API_GATEWAY}/api/v1/billing/ingest/",
            headers={
                "Authorization": f"Bearer {INTERNAL_TOKEN}",
                "Content-Type": "application/json",
            },
            json=records,
            timeout=30,
        )
        if resp.status_code == 202:
            print(f"[COLLECTOR] Sent {len(records)} records — accepted")
        else:
            print(f"[COLLECTOR] Send failed: HTTP {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        print(f"[COLLECTOR] Send error: {e}")


def main():
    print(f"[COLLECTOR] Starting — interval={COLLECT_INTERVAL}s, providers={PROVIDERS}")
    while True:
        all_records = []
        for provider in PROVIDERS:
            if provider == "aws":
                all_records.extend(collect_aws())
            elif provider == "gcp":
                all_records.extend(collect_gcp())
        send_records(all_records)
        time.sleep(COLLECT_INTERVAL)


if __name__ == "__main__":
    main()
