import pytest
from unittest.mock import AsyncMock, MagicMock
from mdcx.crawlers.javstash import StashGraphQLCrawler
from mdcx.crawlers.base import Context, CralwerException
from mdcx.models.types import CrawlerInput
from mdcx.config.models import Website
from mdcx.config.manager import manager

@pytest.fixture
def mock_client():
    client = MagicMock()
    client.post_json = AsyncMock()
    return client

@pytest.mark.asyncio
async def test_javstash_missing_api_key(mock_client):
    # Set empty API key
    manager.config.javstash_api_key = ""
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())
    
    with pytest.raises(CralwerException, match="请在设置中配置 StashAPI 令牌"):
        await crawler._post_graphql(ctx, "query", {})

@pytest.mark.asyncio
async def test_javstash_url_parsing(mock_client):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    
    # Mock GraphQL response for findScene
    mock_client.post_json.return_value = (
        {
            "data": {
                "findScene": {
                    "id": "12345",
                    "title": "Test Scene",
                    "code": "TEST-123",
                    "date": "2023-01-01",
                    "performers": [],
                    "studio": {"name": "Test Studio"},
                    "tags": [],
                    "paths": {"screenshot": "http://image.jpg"},
                    "files": [{"duration": 3600}]
                }
            }
        },
        None
    )
    
    input_data = CrawlerInput.empty()
    input_data.appoint_url = "https://javstash.org/scenes/12345"
    ctx = Context(input=input_data)
    
    data = await crawler._run(ctx)
    
    assert data.title == "Test Scene"
    assert data.external_id == "12345"
    assert data.runtime == "60" # 3600 / 60
    
    # Verify the ID was passed to the query
    args, kwargs = mock_client.post_json.call_args
    assert kwargs['json_data']['variables']['id'] == "12345"

@pytest.mark.asyncio
async def test_javstash_mapping(mock_client):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    
    scene_data = {
        "id": "67890",
        "title": "Scene Mapping Test",
        "details": "Detail text",
        "date": "2024-05-20",
        "urls": ["http://javstash.org/scenes/67890"],
        "studio": {"name": "Studio A"},
        "tags": [{"name": "Tag1"}, {"name": "Tag2"}],
        "performers": [
            {"name": "Actor Female", "gender": "FEMALE", "image_path": "http://photo1.jpg"},
            {"name": "Actor Male", "gender": "MALE", "image_path": "http://photo2.jpg"}
        ],
        "files": [{"duration": 7200}],
        "paths": {"screenshot": "http://thumb.jpg"},
        "code": "CODE-001"
    }
    
    ctx = Context(input=CrawlerInput.empty())
    data = crawler._map_scene(scene_data, ctx)
    
    assert data.title == "Scene Mapping Test"
    assert data.outline == "Detail text"
    assert data.release == "2024-05-20"
    assert data.year == "2024"
    assert data.studio == "Studio A"
    assert data.tags == ["Tag1", "Tag2"]
    assert data.runtime == "120"
    assert data.actors == ["Actor Female"]
    assert data.all_actors == ["Actor Female", "Actor Male"]
    assert data.actor_photo == {"Actor Female": "http://photo1.jpg"}
    assert data.all_actor_photo == {"Actor Female": "http://photo1.jpg", "Actor Male": "http://photo2.jpg"}
    assert data.external_id == "67890"
    assert data.number == "CODE-001"
