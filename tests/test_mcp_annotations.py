from app.mcp_server import mcp


def test_mcp_tool_annotations_are_explicit_standard_booleans():
    tools = mcp._tool_manager.list_tools()
    names = {tool.name for tool in tools}
    assert {"extract_reel", "get_visual_image", "extract_visual_urls"} <= names
    for tool in tools:
        if tool.name in {"extract_reel", "get_visual_image", "extract_visual_urls"}:
            assert tool.annotations is not None
            payload = tool.annotations.model_dump(by_alias=True, exclude_none=True)
            assert payload["readOnlyHint"] is True
            assert payload["destructiveHint"] is False
            assert payload["openWorldHint"] is True
            assert not any(k in payload for k in ("read_only_hint", "destructive_hint", "open_world_hint"))
