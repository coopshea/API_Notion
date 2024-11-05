from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
from notion_client import Client
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="Notion Integration API",
    description="API for interacting with Notion databases and pages",
    version="1.0.0"
)

# Add CORS middleware to allow Custom GPT to make requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://chat.openai.com",  # Allow CustomGPT to access
        "http://localhost:8000",    # Local development
        "http://localhost:3000",    # Local frontend if any
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add better error handling
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Notion client
notion = Client(auth=os.getenv("NOTION_TOKEN"))
database_id = os.getenv("NOTION_DATABASE_ID")

class NotionPage(BaseModel):
    page_id: str
    content: Optional[str] = None

class NotionQuery(BaseModel):
    filter: Optional[Dict[str, Any]] = None
    sorts: Optional[List[Dict[str, Any]]] = None

class PaginationParams(BaseModel):
    start_cursor: Optional[str] = None
    page_size: Optional[int] = 10  # Default to 10 items per page

@app.get("/")
async def root():
    """
    Root endpoint returning API information
    """
    return {
        "message": "Notion Integration API",
        "endpoints": {
            "GET /notion/databases": "List all accessible databases",
            "GET /notion/pages": "Query pages in the configured database",
            "GET /notion/page/{page_id}": "Get specific page content",
            "POST /notion/query": "Query database with filters"
        }
    }

@app.get("/notion/databases")
async def get_databases():
    """
    Get a list of all accessible Notion databases
    """
    try:
        response = notion.search(filter={"property": "object", "value": "database"})
        return response["results"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/notion/pages")
async def get_notion_pages():
    """
    Get all pages from the configured database
    """
    try:
        response = notion.databases.query(
            database_id=database_id
        )
        # Format the response to be more readable
        pages = []
        for page in response["results"]:
            formatted_page = {
                "id": page["id"],
                "url": page["url"],
                "properties": page["properties"]
            }
            pages.append(formatted_page)
        return pages
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/notion/page/{page_id}")
async def get_notion_page(page_id: str):
    """
    Get detailed content of a specific page
    """
    try:
        # Get page metadata
        page = notion.pages.retrieve(page_id=page_id)
        
        # Get page content (blocks)
        blocks = notion.blocks.children.list(block_id=page_id)
        
        # Format the response
        content = []
        for block in blocks["results"]:
            block_type = block["type"]
            if block_type in ["paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item"]:
                text_content = ""
                if "rich_text" in block[block_type]:
                    for text in block[block_type]["rich_text"]:
                        text_content += text["plain_text"]
                content.append({
                    "type": block_type,
                    "content": text_content
                })
        
        return {
            "metadata": page,
            "content": content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/notion/query")
async def query_database(query: NotionQuery):
    """
    Query the database with custom filters and sorts
    """
    try:
        response = notion.databases.query(
            database_id=database_id,
            filter=query.filter,
            sorts=query.sorts
        )
        return response["results"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/notion/test-database")
async def test_database_access(pagination: PaginationParams):
    """
    Test endpoint to verify database access with pagination
    Returns a paginated list of pages from the database
    """
    try:
        # Query the database with pagination parameters
        response = notion.databases.query(
            database_id=database_id,
            start_cursor=pagination.start_cursor,
            page_size=min(pagination.page_size, 100)  # Ensure we don't exceed the 100 item limit
        )
        
        # Format the response
        formatted_response = {
            "object": "list",
            "results": [],
            "has_more": response["has_more"],
            "next_cursor": response.get("next_cursor"),
            "type": "page"
        }

        # Format each page in the results
        for page in response["results"]:
            formatted_page = {
                "id": page["id"],
                "url": page["url"],
                "created_time": page["created_time"],
                "last_edited_time": page["last_edited_time"],
                "properties": {}
            }
            
            # Extract and format properties
            for prop_name, prop_data in page["properties"].items():
                if prop_data["type"] == "title":
                    formatted_page["properties"][prop_name] = "".join(
                        text["plain_text"] for text in prop_data["title"]
                    )
                elif prop_data["type"] == "rich_text":
                    formatted_page["properties"][prop_name] = "".join(
                        text["plain_text"] for text in prop_data["rich_text"]
                    )
                else:
                    formatted_page["properties"][prop_name] = prop_data[prop_data["type"]]
            
            formatted_response["results"].append(formatted_page)

        return formatted_response

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "message": "Failed to access Notion database",
                "database_id": database_id
            }
        )

# Add this helper endpoint to test pagination
@app.get("/notion/test-pagination")
async def test_pagination():
    """
    Test endpoint that demonstrates pagination by fetching all pages
    """
    try:
        all_pages = []
        has_more = True
        next_cursor = None
        page_count = 0

        while has_more:
            response = await test_database_access(
                PaginationParams(
                    start_cursor=next_cursor,
                    page_size=10
                )
            )
            
            all_pages.extend(response["results"])
            has_more = response["has_more"]
            next_cursor = response.get("next_cursor")
            page_count += 1

            # Optional: break after a certain number of pages to avoid infinite loops
            if page_count >= 10:  # Limit to 10 pages maximum
                break

        return {
            "total_pages_fetched": len(all_pages),
            "pagination_rounds": page_count,
            "pages": all_pages
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "message": "Failed to test pagination"
            }
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port) 