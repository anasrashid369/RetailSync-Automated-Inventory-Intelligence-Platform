# RetailSync — Automated Inventory Intelligence Platform

> Manual inventory management costs small retailers 10+ hours per week
> and causes stockouts that directly hurt revenue. RetailSync eliminates
> this entirely using an event-driven serverless architecture on AWS.

---

## The Problem

A small e-commerce retailer receives daily inventory reports from 3
different suppliers as CSV files. Their team manually downloads these,
opens Excel, checks stock levels, and sends alerts to the purchasing
team when something is low. This takes 2-3 hours daily and causes
human errors — products go out of stock before anyone notices.

## The Solution

An automated serverless pipeline that eliminates this manual process
entirely. Supplier drops a CSV → system processes it → purchasing team
gets alerted — all within 60 seconds, zero human effort.

---

## Architecture
Supplier CSV Upload
↓
S3 Bucket (3 prefixes: /supplier-a, /supplier-b, /supplier-c)
↓  S3 Event Trigger (.csv only)
Lambda: Processor Function
↓  reads, validates, cleans, transforms
DynamoDB: RetailSync-Inventory-table
↓  if stock < threshold
SNS Topic → Email Alert to Purchasing Team
↓
CloudWatch: Logs + Dashboard + Alarms
API Gateway → Lambda: Query Function → DynamoDB
(Manager queries current stock via REST API)

---

## Business Impact

| Metric | Before | After |
|---|---|---|
| Daily inventory review time | 2-3 hours | 0 minutes |
| Alert delivery time | Next morning | Under 60 seconds |
| CSV processing time | Manual | Avg 4-7 seconds |
| Human error risk | High | Zero |
| Monthly AWS cost (50 reports) | — | $0.00 (free tier) |

---

## AWS Services Used

| Service | Role | Why This Service |
|---|---|---|
| S3 | File ingestion trigger | Event-driven, durable, versioned |
| Lambda | CSV processing + query | Serverless, scales to zero, pay per use |
| DynamoDB | Inventory data store | Schemaless, always-free 25GB tier |
| SNS | Low stock alerting | Pub/sub, supports email + SMS |
| API Gateway | Manager query interface | Managed, zero infrastructure |
| CloudWatch | Logs + metrics + alarms | Native AWS observability |
| IAM | Least privilege security | Each service has minimum permissions |
| CloudFormation | Infrastructure as Code | Entire stack in one command |

---

## Security Decisions

| Decision | Reason |
|---|---|
| All S3 buckets block public access | No data ever publicly exposed |
| S3 versioning enabled | Recover from corrupted supplier uploads |
| S3 encryption at rest (AES-256) | Data protected at storage level |
| DynamoDB encryption at rest | Sensitive inventory data protected |
| DynamoDB Point-in-Time Recovery | Restore to any point in last 35 days |
| IAM least privilege per Lambda | Processor cannot query, Query cannot publish |
| No hardcoded credentials | All config via environment variables |
| S3 trigger filtered to .csv only | Non-CSV uploads ignored silently |
| CloudWatch alarms on errors | Immediate notification if pipeline fails |

---

## Project Structure
retailsync/
├── lambda/
│   ├── processor/
│   │   └── lambda_function.py    # CSV processing + alerting
│   └── query/
│       └── lambda_function.py    # Stock query API
├── cloudformation/
│   └── template.yaml             # Full IaC — deploy in one command
├── test-data/
│   ├── supplier_a_inventory.csv
│   ├── supplier_b_inventory.csv
│   └── supplier_c_inventory.csv
└── README.md

---

## Deploy in One Command

Clone the repo and deploy the entire infrastructure:

```bash
git clone https://github.com/YOUR_USERNAME/retailsync.git
cd retailsync

aws cloudformation deploy \
  --template-file cloudformation/template.yaml \
  --stack-name retailsync-stack \
  --parameter-overrides AlertEmail=your@email.com \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

One command creates every S3 bucket, DynamoDB table, IAM role,
and SNS topic. No manual console clicks. No configuration drift.

---

## How to Test

**1. Upload a supplier CSV to trigger the pipeline:**
```bash
aws s3 cp test-data/supplier_a_inventory.csv \
  s3://YOUR-UPLOADS-BUCKET/supplier-a/supplier_a_inventory.csv
```

**2. Watch it process in real time:**
```bash
aws logs tail /aws/lambda/RetailSync-Processor --follow
```

**3. Query current stock via API:**
```bash
# All products
curl https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com/prod/stock

# Low stock items only
curl "https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com/prod/stock?status=LOW_STOCK"

# By category
curl "https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com/prod/stock?category=Electronics"
```

**4. Check your email** for the low stock alert within 60 seconds.

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/stock` | GET | All products with summary stats |
| `/stock?status=LOW_STOCK` | GET | Items below threshold |
| `/stock?status=OUT_OF_STOCK` | GET | Items with zero quantity |
| `/stock?status=ADEQUATE` | GET | Healthy stock items |
| `/stock?category=Electronics` | GET | Filter by category |

---

## What I Would Add With a Production Budget

- **SQS queue** between S3 and Lambda for guaranteed delivery at scale
  and to handle concurrent supplier uploads without throttling
- **AWS Glue + Athena** for historical trend analysis across months of data
- **QuickSight dashboard** for visual inventory analytics and forecasting
- **KMS customer-managed keys** for encryption instead of AWS-managed
- **EventBridge** for scheduled daily summary reports to management
- **Lambda layers** to share common utilities across functions
- **X-Ray tracing** for end-to-end request tracing across services
- **RDS Aurora Serverless** if relational queries become necessary

---

## Lessons Learned

- IAM least privilege must match exact resource names — placeholder
  names in policies cause silent AccessDenied failures at runtime
- S3 event triggers filter by suffix at the bucket level — cleaner
  than filtering inside Lambda code
- DynamoDB PAY_PER_REQUEST billing is ideal for unpredictable
  workloads and stays within free tier at low volume
- CloudFormation resource names must be unique across your account —
  use AccountId in bucket names to guarantee global uniqueness

---

## Author

**Muhammad Anas Rashid**
AWS Certified Solutions Architect Associate (SAA-C03)
