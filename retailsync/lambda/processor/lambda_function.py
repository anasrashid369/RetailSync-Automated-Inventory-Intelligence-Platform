import json
import boto3
import csv
import io
import uuid
import os
from datetime import datetime, timezone

# Initialize AWS clients outside handler for connection reuse
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
sns_client = boto3.client('sns')

# Environment variables (set in Lambda config - never hardcode)
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']
INVENTORY_TABLE = os.environ['INVENTORY_TABLE']
ALERTS_TABLE = os.environ['ALERTS_TABLE']
PROCESSED_BUCKET = os.environ['PROCESSED_BUCKET']

inventory_table = dynamodb.Table(INVENTORY_TABLE)
alerts_table = dynamodb.Table(ALERTS_TABLE)


def lambda_handler(event, context):
    """
    Triggered by S3 PUT events.
    Processes supplier CSV files and updates inventory.
    """
    print(f"Processing event: {json.dumps(event)}")
    
    processed_files = []
    low_stock_items = []
    
    # S3 can batch multiple records in one event
    for record in event['Records']:
        bucket_name = record['s3']['bucket']['name']
        object_key = record['s3']['object']['key']
        
        # Skip placeholder files
        if object_key.endswith('.keep'):
            print(f"Skipping placeholder file: {object_key}")
            continue
        
        print(f"Processing file: s3://{bucket_name}/{object_key}")
        
        try:
            # Step 1: Read CSV from S3
            csv_data = read_csv_from_s3(bucket_name, object_key)
            
            # Step 2: Process each row
            file_low_stock = process_inventory_rows(csv_data, object_key)
            low_stock_items.extend(file_low_stock)
            
            # Step 3: Move processed file to processed bucket
            move_to_processed(bucket_name, object_key)
            
            processed_files.append(object_key)
            print(f"Successfully processed: {object_key}")
            
        except Exception as e:
            print(f"ERROR processing {object_key}: {str(e)}")
            raise e
    
    # Step 4: Send consolidated alert if any low stock items found
    if low_stock_items:
        send_low_stock_alert(low_stock_items)
        log_alerts(low_stock_items)
    
    result = {
        'statusCode': 200,
        'processed_files': processed_files,
        'low_stock_alerts_sent': len(low_stock_items),
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    
    print(f"Processing complete: {json.dumps(result)}")
    return result


def read_csv_from_s3(bucket_name, object_key):
    """Read and parse CSV file from S3."""
    response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
    csv_content = response['Body'].read().decode('utf-8')
    
    # Parse CSV
    reader = csv.DictReader(io.StringIO(csv_content))
    rows = list(reader)
    
    print(f"Read {len(rows)} rows from {object_key}")
    return rows


def process_inventory_rows(rows, object_key):
    """
    Validates, cleans, and stores each inventory row.
    Returns list of low stock items.
    """
    low_stock_items = []
    required_fields = ['product_id', 'product_name', 'category', 
                       'quantity', 'threshold', 'unit_price', 'supplier']
    
    for row in rows:
        # Validation: check all required fields present
        missing = [f for f in required_fields if f not in row or not row[f].strip()]
        if missing:
            print(f"WARNING: Row missing fields {missing}, skipping: {row}")
            continue
        
        # Data cleaning: strip whitespace, convert types
        try:
            product_id = row['product_id'].strip()
            product_name = row['product_name'].strip()
            category = row['category'].strip()
            quantity = int(row['quantity'].strip())
            threshold = int(row['threshold'].strip())
            unit_price = float(row['unit_price'].strip())
            supplier = row['supplier'].strip()
        except ValueError as e:
            print(f"WARNING: Data type error in row {row}: {e}, skipping")
            continue
        
        # Determine stock status
        if quantity == 0:
            stock_status = 'OUT_OF_STOCK'
        elif quantity <= threshold:
            stock_status = 'LOW_STOCK'
        elif quantity <= threshold * 1.5:
            stock_status = 'MODERATE'
        else:
            stock_status = 'ADEQUATE'
        
        # Build item for DynamoDB
        timestamp = datetime.now(timezone.utc).isoformat()
        item = {
            'product_id': product_id,
            'supplier': supplier,
            'product_name': product_name,
            'category': category,
            'quantity': quantity,
            'threshold': threshold,
            'unit_price': str(unit_price),  # DynamoDB doesn't support float natively
            'stock_status': stock_status,
            'last_updated': timestamp,
            'source_file': object_key
        }
        
        # Write to DynamoDB
        inventory_table.put_item(Item=item)
        print(f"Stored: {product_id} ({supplier}) - qty:{quantity} status:{stock_status}")
        
        # Flag for alert if low stock
        if stock_status in ['LOW_STOCK', 'OUT_OF_STOCK']:
            low_stock_items.append({
                'product_id': product_id,
                'product_name': product_name,
                'category': category,
                'quantity': quantity,
                'threshold': threshold,
                'supplier': supplier,
                'stock_status': stock_status,
                'unit_price': unit_price
            })
    
    return low_stock_items


def send_low_stock_alert(low_stock_items):
    """Send consolidated SNS alert for all low stock items."""
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    
    # Build alert message
    message_lines = [
        f"🚨 RETAILSYNC LOW STOCK ALERT",
        f"Generated: {timestamp}",
        f"Items requiring attention: {len(low_stock_items)}",
        "",
        "=" * 50,
    ]
    
    # Group by supplier for readability
    by_supplier = {}
    for item in low_stock_items:
        supplier = item['supplier']
        if supplier not in by_supplier:
            by_supplier[supplier] = []
        by_supplier[supplier].append(item)
    
    for supplier, items in by_supplier.items():
        message_lines.append(f"\nSUPPLIER: {supplier.upper()}")
        message_lines.append("-" * 30)
        for item in items:
            status_emoji = "❌" if item['stock_status'] == 'OUT_OF_STOCK' else "⚠️"
            message_lines.append(
                f"{status_emoji} {item['product_name']}"
            )
            message_lines.append(
                f"   Product ID: {item['product_id']}"
            )
            message_lines.append(
                f"   Current Stock: {item['quantity']} units"
            )
            message_lines.append(
                f"   Minimum Threshold: {item['threshold']} units"
            )
            message_lines.append(
                f"   Status: {item['stock_status']}"
            )
            message_lines.append("")
    
    message_lines.extend([
        "=" * 50,
        "Action required: Please review and reorder affected items.",
        "Query current stock: Use the RetailSync Stock Query API",
    ])
    
    message = "\n".join(message_lines)
    
    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=f"[RetailSync] {len(low_stock_items)} Low Stock Alert(s) - {timestamp}",
        Message=message
    )
    
    print(f"SNS alert sent for {len(low_stock_items)} low stock items")


def log_alerts(low_stock_items):
    """Log each alert to DynamoDB for audit trail."""
    for item in low_stock_items:
        alerts_table.put_item(Item={
            'alert_id': str(uuid.uuid4()),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'product_id': item['product_id'],
            'product_name': item['product_name'],
            'supplier': item['supplier'],
            'quantity_at_alert': item['quantity'],
            'threshold': item['threshold'],
            'stock_status': item['stock_status']
        })


def move_to_processed(source_bucket, object_key):
    """Move processed file to processed bucket."""
    timestamp = datetime.now(timezone.utc).strftime('%Y/%m/%d')
    destination_key = f"processed/{timestamp}/{object_key.split('/')[-1]}"
    
    # Copy to processed bucket
    s3_client.copy_object(
        CopySource={'Bucket': source_bucket, 'Key': object_key},
        Bucket=PROCESSED_BUCKET,
        Key=destination_key
    )
    
    # Delete from upload bucket
    s3_client.delete_object(Bucket=source_bucket, Key=object_key)
    
    print(f"Moved {object_key} to processed/{timestamp}/")
