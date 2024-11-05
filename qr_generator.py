import qrcode
import os
from notion_client import Client
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from pprint import pprint
from urllib.parse import quote_plus
import json

# Load environment variables from .env file
load_dotenv()

class NotionQRGenerator:
    def __init__(self, notion_token: str, database_id: str, workspace: str):
        """
        Initialize the QR generator with Notion credentials
        
        Args:
            notion_token: Your Notion integration token
            database_id: The ID of your inventory database
            workspace: Your Notion workspace name
        """
        if not notion_token or not database_id or not workspace:
            raise ValueError("Missing required environment variables: NOTION_TOKEN, NOTION_DATABASE_ID, and NOTION_WORKSPACE")
            
        self.notion = Client(auth=notion_token)
        self.database_id = database_id
        self.workspace = workspace
        self.output_dir = Path(__file__).parent / "qr_codes"
        self.schema = None  # Will store database schema
        
    def get_database_schema(self) -> Dict:
        """Get database schema to understand its structure"""
        response = self.notion.databases.retrieve(database_id=self.database_id)
        
        # Extract property configurations
        properties = response["properties"]
        self.schema = {
            "name": response["title"][0]["text"]["content"] if response["title"] else "Untitled",
            "properties": {
                key: prop["type"] for key, prop in properties.items()
            }
        }
        
        print("\nDatabase Schema:")
        pprint(self.schema)
        return self.schema
        
    def generate_item_qr(self, page_id: str, properties: Dict) -> None:
        """
        Generate QR code for a single inventory item with title
        
        Args:
            page_id: Notion page ID for the item
            properties: Item properties from Notion
        """
        # Get item name from Item field
        if 'Item' not in properties or not properties['Item']['title']:
            raise ValueError(f"Could not find Item title in properties: {properties}")
            
        item_name = properties['Item']['title'][0]['text']['content']
        
        # Create Notion page URL
        notion_url = f"https://www.notion.so/{page_id.replace('-', '')}"
        print(f"Generated URL for item {item_name}: {notion_url}")
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(notion_url)
        qr.make(fit=True)
        
        # Create QR code with title
        qr_image = qr.make_image(fill_color="black", back_color="white")
        
        # Create safe filename from item name
        safe_filename = "".join(c for c in item_name if c.isalnum() or c in (' ','-','_')).rstrip()
        
        # Add timestamp to filename
        timestamp = datetime.now().strftime("%Y%m%d")
        filename = f"{safe_filename}_{timestamp}.png"
        
        # Save QR code
        qr_image.save(self.output_dir / filename)
        print(f"Generated QR code for: {item_name}")
        
    def generate_location_qr(self, location: Dict) -> None:
        """Generate QR code for a location's linked database"""
        location_string = f"{location.get('name', '')}"
        if location.get('rack'): location_string += f"_R{location['rack']}"
        if location.get('shelf'): location_string += f"_S{location['shelf']}"
        
        # Get the linked database ID (you'll need to store/retrieve these)
        linked_db_id = self.get_linked_database_id(location)
        
        if linked_db_id:
            notion_url = f"https://www.notion.so/{linked_db_id.replace('-', '')}"
            
            # Generate QR code...
            
    def generate_all_qrs(self) -> None:
        """Generate QR codes for semi-consumable items only, collapsing duplicates"""
        self.output_dir.mkdir(exist_ok=True)
        print("Getting database schema...")
        self.get_database_schema()
        
        print("\nQuerying database for semi-consumable items...")
        
        all_results = []
        start_cursor = None
        
        # Get all semi-consumable items
        while True:
            query_params = {
                "database_id": self.database_id,
                "filter": {
                    "property": "Category",
                    "multi_select": {
                        "contains": "Semi-consumable"
                    }
                },
                "page_size": 100
            }
            
            if start_cursor:
                query_params["start_cursor"] = start_cursor
            
            response = self.notion.databases.query(**query_params)
            all_results.extend(response["results"])
            
            if not response.get("has_more"):
                break
            start_cursor = response.get("next_cursor")
        
        print(f"\nFound total of {len(all_results)} semi-consumable items")
        
        # Group items by name
        items_by_name = {}
        for item in all_results:
            try:
                item_name = item['properties']['Item']['title'][0]['text']['content']
                if item_name not in items_by_name:
                    items_by_name[item_name] = {
                        'items': [],
                        'total_quantity': 0
                    }
                items_by_name[item_name]['items'].append(item)
                
                # Try to get quantity if it exists
                try:
                    quantity_text = item['properties'].get('Quantity', {}).get('rich_text', [])
                    if quantity_text and quantity_text[0].get('text', {}).get('content'):
                        qty = int(quantity_text[0]['text']['content'])
                        items_by_name[item_name]['total_quantity'] += qty
                except (ValueError, KeyError, IndexError):
                    items_by_name[item_name]['total_quantity'] += 1
                    
            except Exception as e:
                print(f"Error processing item: {str(e)}")
                continue
        
        # Generate QR codes for unique items
        generated_count = 0
        for item_name, data in items_by_name.items():
            try:
                # Use the first item's ID for the QR code
                first_item = data['items'][0]
                print(f"\nProcessing: {item_name}")
                print(f"Found {len(data['items'])} instances")
                if data['total_quantity'] > 1:
                    print(f"Total quantity: {data['total_quantity']}")
                
                self.generate_item_qr(first_item["id"], first_item["properties"])
                generated_count += 1
                
            except Exception as e:
                print(f"Error generating QR for {item_name}: {str(e)}")
                continue
        
        print(f"\nSummary:")
        print(f"Total items found: {len(all_results)}")
        print(f"Unique items: {len(items_by_name)}")
        print(f"QR codes generated: {generated_count}")
        
        # Print details of collapsed items
        print("\nCollapsed items:")
        for item_name, data in items_by_name.items():
            if len(data['items']) > 1:
                print(f"- {item_name}: {len(data['items'])} instances, Total quantity: {data['total_quantity']}")

if __name__ == "__main__":
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
    WORKSPACE = os.getenv("NOTION_WORKSPACE")
    
    if not NOTION_TOKEN or not DATABASE_ID or not WORKSPACE:
        print("Error: Missing required environment variables. Please check your .env file.")
        exit(1)
        
    try:
        generator = NotionQRGenerator(NOTION_TOKEN, DATABASE_ID, WORKSPACE)
        generator.generate_all_qrs()
    except Exception as e:
        print(f"Error: {str(e)}")
        exit(1)