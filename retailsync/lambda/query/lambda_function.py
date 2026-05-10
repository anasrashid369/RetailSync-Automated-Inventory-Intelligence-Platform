import json
import boto3
import os
from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
INVENTORY_TABLE = os.environ['INVENTORY_TABLE']
inventory_table = dynamodb.Table(INVENTORY_TABLE)


class DecimalEncoder(json.JSONEncoder):
    """Handle DynamoDB Decimal types for JSON serialization."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def lambda_handler(event, context):
    """
    Query endpoint for managers to check stock levels.
    Supports: /stock (all), /stock?category=Electronics, 
              /stock?status=LOW_STOCK, /stock/{product_id}
    """
    print(f"Query event: {json.dumps(event)}")
    
    # Get query parameters
    params = event.get('queryStringParameters') or {}
    path = event.get('path', '/stock')
    path_params = event.get('pathParameters') or {}
    
    try:
        # Route: GET /stock/{product_id}
        if path_params.get('product_id'):
            result = get_product(path_params['product_id'])
        
        # Route: GET /stock?status=LOW_STOCK
        elif params.get('status'):
            result = get_by_status(params['status'])
        
        # Route: GET /stock?category=Electronics
        elif params.get('category'):
            result = get_by_category(params['category'])
        
        # Route: GET /stock (all items)
        else:
            result = get_all_inventory()
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(result, cls=DecimalEncoder)
        }
    
    except Exception as e:
        print(f"Query error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error', 'detail': str(e)})
        }


def get_product(product_id):
    """Get specific product by ID."""
    response = inventory_table.query(
        KeyConditionExpression=Key('product_id').eq(product_id)
    )
    items = response.get('Items', [])
    return {
        'product_id': product_id,
        'count': len(items),
        'items': items
    }


def get_by_status(status):
    """Get all items with specific stock status."""
    valid_statuses = ['ADEQUATE', 'MODERATE', 'LOW_STOCK', 'OUT_OF_STOCK']
    if status not in valid_statuses:
        raise ValueError(f"Invalid status. Must be one of: {valid_statuses}")
    
    response = inventory_table.scan(
        FilterExpression=Attr('stock_status').eq(status)
    )
    items = response.get('Items', [])
    
    # Sort by quantity ascending (most critical first)
    items.sort(key=lambda x: int(x.get('quantity', 0)))
    
    return {
        'status_filter': status,
        'count': len(items),
        'items': items
    }


def get_by_category(category):
    """Get all items in a category."""
    response = inventory_table.scan(
        FilterExpression=Attr('category').eq(category)
    )
    items = response.get('Items', [])
    items.sort(key=lambda x: x.get('product_name', ''))
    
    return {
        'category_filter': category,
        'count': len(items),
        'items': items
    }


def get_all_inventory():
    """Get complete inventory with summary stats."""
    response = inventory_table.scan()
    items = response.get('Items', [])
    
    # Build summary
    status_counts = {}
    category_counts = {}
    for item in items:
        status = item.get('stock_status', 'UNKNOWN')
        category = item.get('category', 'UNKNOWN')
        status_counts[status] = status_counts.get(status, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
    
    return {
        'total_products': len(items),
        'summary': {
            'by_status': status_counts,
            'by_category': category_counts
        },
        'items': items
    }
