"""MaindexClient: auth header construction and REST call wiring."""

from unittest.mock import MagicMock

import httpx
import pytest

from maindex_plugin import MaindexClient


# ── Auth headers ─────────────────────────────────────────────────────────


class TestAuthHeaders:
    """The prior bug sent both X-API-Key and Bearer when only an API key
    was provided, causing auth failures on backends that validate the JWT.
    These tests lock down the fix."""

    def test_api_key_only_sends_x_api_key(self):
        c = MaindexClient(api_key="key-123")
        assert c._client.headers["x-api-key"] == "key-123"
        assert "authorization" not in c._client.headers
        c.close()

    def test_bearer_only_sends_authorization(self):
        c = MaindexClient(bearer_token="jwt-abc")
        assert c._client.headers["authorization"] == "Bearer jwt-abc"
        assert "x-api-key" not in c._client.headers
        c.close()

    def test_both_credentials_coexist(self):
        c = MaindexClient(api_key="key-123", bearer_token="jwt-abc")
        assert c._client.headers["x-api-key"] == "key-123"
        assert c._client.headers["authorization"] == "Bearer jwt-abc"
        c.close()

    def test_no_credentials_sends_neither_auth_header(self):
        c = MaindexClient()
        assert "x-api-key" not in c._client.headers
        assert "authorization" not in c._client.headers
        c.close()

    def test_no_global_content_type_header(self):
        c = MaindexClient(api_key="key-123")
        assert "content-type" not in c._client.headers
        c.close()


# ── Helpers ──────────────────────────────────────────────────────────────


def _mock_response(data):
    """Simulate an httpx.Response that passes raise_for_status."""
    r = MagicMock()
    r.json.return_value = data
    return r


def _envelope(data, **meta):
    """Expert API list/single response shape."""
    body: dict = {"ok": True, "data": data}
    if meta:
        body["meta"] = meta
    return body


@pytest.fixture
def client():
    """MaindexClient with a mocked HTTP transport (no real connections)."""
    c = MaindexClient.__new__(MaindexClient)
    c._client = MagicMock()
    return c


# ── search ───────────────────────────────────────────────────────────────


class TestSearch:

    def test_unwraps_envelope_data_array(self, client):
        client._client.get.return_value = _mock_response(
            _envelope([{"shortId": "mem-1a", "headline": "dogs"}]),
        )
        result = client.search("dogs")
        assert len(result["items"]) == 1
        assert result["items"][0]["headline"] == "dogs"

    def test_preserves_search_meta_from_envelope(self, client):
        client._client.get.return_value = _mock_response(
            _envelope(
                [{"shortId": "mem-1a", "headline": "dogs"}],
                degraded_components=["semantic"],
                degraded_reason="embeddings unavailable",
                retrieval_sources=["lexical"],
            ),
        )
        result = client.search("dogs")
        assert result["degraded_components"] == ["semantic"]
        assert result["degraded_reason"] == "embeddings unavailable"
        assert result["retrieval_sources"] == ["lexical"]

    def test_builds_params_with_defaults(self, client):
        client._client.get.return_value = _mock_response(_envelope([]))
        client.search("hello world", limit=3)
        client._client.get.assert_called_once_with(
            "/v1/search",
            params={"q": "hello world", "limit": 3, "search_strategy": "auto"},
        )

    def test_forwards_keyword_filters(self, client):
        client._client.get.return_value = _mock_response(_envelope([]))
        client.search("q", limit=5, tags=["a"], kind="fact")
        _, kwargs = client._client.get.call_args
        assert kwargs["params"]["tags"] == ["a"]
        assert kwargs["params"]["kind"] == "fact"

    def test_truncates_query_at_1000_chars(self, client):
        client._client.get.return_value = _mock_response(_envelope([]))
        client.search("x" * 2000)
        _, kwargs = client._client.get.call_args
        assert len(kwargs["params"]["q"]) == 1000

    def test_excludes_none_filters(self, client):
        client._client.get.return_value = _mock_response(_envelope([]))
        client.search("q", limit=5, kind=None)
        _, kwargs = client._client.get.call_args
        assert "kind" not in kwargs["params"]

    def test_propagates_http_errors(self, client):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock(),
        )
        client._client.get.return_value = resp
        with pytest.raises(httpx.HTTPStatusError):
            client.search("test")


# ── keep ─────────────────────────────────────────────────────────────────


class TestKeep:

    def test_minimal_payload(self, client):
        client._client.post.return_value = _mock_response(
            _envelope({"id": "1", "shortId": "mem-1"}),
        )
        client.keep("My headline")
        _, kwargs = client._client.post.call_args
        payload = kwargs["json"]
        assert payload == {"headline": "My headline", "body": "", "kind": "note"}

    def test_full_payload_with_extras(self, client):
        client._client.post.return_value = _mock_response(
            _envelope({"id": "1", "shortId": "mem-1"}),
        )
        client.keep(
            "HL", body="B", tags=["t1"], kind="fact",
            collections=["col1"], source={"origin": "test"},
        )
        _, kwargs = client._client.post.call_args
        payload = kwargs["json"]
        assert payload["tags"] == ["t1"]
        assert payload["kind"] == "fact"
        assert payload["collections"] == ["col1"]
        assert payload["source"] == {"origin": "test"}

    def test_sends_to_memories_endpoint(self, client):
        client._client.post.return_value = _mock_response(
            _envelope({"id": "1", "shortId": "mem-1"}),
        )
        client.keep("H")
        args, _ = client._client.post.call_args
        assert args[0] == "/v1/memories"


# ── recall ───────────────────────────────────────────────────────────────


class TestRecall:

    def test_include_links_converted_to_lowercase_string(self, client):
        client._client.get.return_value = _mock_response(
            _envelope({"id": "abc", "shortId": "mem-1"}),
        )
        client.recall("abc", include_links=False)
        _, kwargs = client._client.get.call_args
        assert kwargs["params"]["include_links"] == "false"

    def test_default_include_links_is_true(self, client):
        client._client.get.return_value = _mock_response(
            _envelope({"id": "abc", "shortId": "mem-1"}),
        )
        client.recall("abc")
        _, kwargs = client._client.get.call_args
        assert kwargs["params"]["include_links"] == "true"

    def test_calls_correct_endpoint(self, client):
        client._client.get.return_value = _mock_response(_envelope({}))
        client.recall("mem-1a")
        args, _ = client._client.get.call_args
        assert args[0] == "/v1/memories/mem-1a"


# ── update ───────────────────────────────────────────────────────────────


class TestUpdate:

    def test_forwards_all_kwargs(self, client):
        client._client.post.return_value = _mock_response(_envelope({}))
        client.update(
            "abc", "body_replace",
            headline="H", body="B", tags=["t"],
            kind="fact", canon_status="accepted",
        )
        _, kwargs = client._client.post.call_args
        payload = kwargs["json"]
        assert payload["mode"] == "body_replace"
        assert payload["headline"] == "H"
        assert payload["canon_status"] == "accepted"

    def test_excludes_none_kwargs(self, client):
        client._client.post.return_value = _mock_response(_envelope({}))
        client.update("abc", "revision_only", headline=None)
        _, kwargs = client._client.post.call_args
        assert "headline" not in kwargs["json"]

    def test_calls_correct_endpoint(self, client):
        client._client.post.return_value = _mock_response(_envelope({}))
        client.update("mem-1a", "revision_only")
        args, _ = client._client.post.call_args
        assert args[0] == "/v1/memories/mem-1a/update"


# ── forget ───────────────────────────────────────────────────────────────


class TestForget:

    def test_sends_delete_to_correct_endpoint(self, client):
        client._client.delete.return_value = _mock_response(
            _envelope({"deleted": True}),
        )
        client.forget("mem-1a")
        client._client.delete.assert_called_once_with("/v1/memories/mem-1a")


# ── list_memories ────────────────────────────────────────────────────────


class TestRecallExtended:

    def test_include_deleted_and_revisions_params(self, client):
        client._client.get.return_value = _mock_response(_envelope({}))
        client.recall("mem-1a", include_deleted=True, include_revisions=True)
        _, kwargs = client._client.get.call_args
        assert kwargs["params"]["include_deleted"] == "true"
        assert kwargs["params"]["include_revisions"] == "true"


class TestRestore:

    def test_posts_to_restore_endpoint(self, client):
        client._client.post.return_value = _mock_response(
            _envelope({"id": "1", "shortId": "mem-1"}),
        )
        client.restore("mem-1a")
        client._client.post.assert_called_once_with("/v1/memories/mem-1a/restore")


class TestAssociations:

    def test_create_associations(self, client):
        client._client.post.return_value = _mock_response(_envelope([]))
        targets = [{"memory_id": "mem-2", "relation_type": "supports"}]
        client.create_associations("mem-1", targets)
        _, kwargs = client._client.post.call_args
        assert kwargs["json"]["targets"] == targets

    def test_discover_associations(self, client):
        client._client.get.return_value = _mock_response(
            _envelope({"memories": [{"id": "x", "headline": "H"}]}),
        )
        client.discover_associations(memory_id="mem-1", limit=5)
        _, kwargs = client._client.get.call_args
        assert kwargs["params"]["memory_id"] == "mem-1"
        assert kwargs["params"]["limit"] == 5


class TestCollections:

    def test_delete_collection(self, client):
        client._client.delete.return_value = _mock_response(
            _envelope({"deleted": True, "shortId": "col-1"}),
        )
        result = client.delete_collection("col-1")
        client._client.delete.assert_called_once_with("/v1/collections/col-1")
        assert result.get("deleted") is True

    def test_list_collections(self, client):
        client._client.get.return_value = _mock_response(_envelope([]))
        client.list_collections(parent_id="col-parent", limit=10, offset=5)
        _, kwargs = client._client.get.call_args
        assert kwargs["params"]["parent_id"] == "col-parent"
        assert kwargs["params"]["limit"] == 10

    def test_create_collection(self, client):
        client._client.post.return_value = _mock_response(
            _envelope({"id": "c1", "slug": "my-col"}),
        )
        client.create_collection("My Col", slug="my-col", description="desc")
        _, kwargs = client._client.post.call_args
        assert kwargs["json"]["name"] == "My Col"
        assert kwargs["json"]["slug"] == "my-col"
        assert "summary_headline" not in kwargs["json"]

    def test_add_collection_members(self, client):
        client._client.post.return_value = _mock_response(_envelope({"added": 2}))
        client.add_collection_members("col-1", ["mem-1", "mem-2"])
        _, kwargs = client._client.post.call_args
        assert kwargs["json"]["memory_ids"] == ["mem-1", "mem-2"]

    def test_remove_collection_members(self, client):
        client._client.request.return_value = _mock_response(
            _envelope({"removed": 1}),
        )
        client.remove_collection_members("col-1", ["mem-1"])
        client._client.request.assert_called_once()
        args, kwargs = client._client.request.call_args
        assert args[0] == "DELETE"
        assert kwargs["json"]["memory_ids"] == ["mem-1"]


class TestListMemories:

    def test_forwards_filters_as_params(self, client):
        client._client.get.return_value = _mock_response(_envelope([]))
        client.list_memories(kind="note", limit=10)
        _, kwargs = client._client.get.call_args
        assert kwargs["params"] == {"kind": "note", "limit": 10}

    def test_excludes_none_values(self, client):
        client._client.get.return_value = _mock_response(_envelope([]))
        client.list_memories(kind="note", tags=None)
        _, kwargs = client._client.get.call_args
        assert "tags" not in kwargs["params"]

    def test_calls_memories_endpoint(self, client):
        client._client.get.return_value = _mock_response(_envelope([]))
        client.list_memories()
        args, _ = client._client.get.call_args
        assert args[0] == "/v1/memories"


# ── close ────────────────────────────────────────────────────────────────


class TestClose:

    def test_closes_underlying_client(self, client):
        client.close()
        client._client.close.assert_called_once()


# ── team param on search/list ────────────────────────────────────────────


class TestTeamScopedMemory:

    def test_search_forwards_team_param(self, client):
        client._client.get.return_value = _mock_response(_envelope([]))
        client.search("q", team="acme")
        _, kwargs = client._client.get.call_args
        assert kwargs["params"]["team"] == "acme"

    def test_list_memories_forwards_team_param(self, client):
        client._client.get.return_value = _mock_response(_envelope([]))
        client.list_memories(team="acme", kind="note")
        _, kwargs = client._client.get.call_args
        assert kwargs["params"]["team"] == "acme"
        assert kwargs["params"]["kind"] == "note"

    def test_keep_with_team_routes_to_team_keep(self, client):
        client._client.post.return_value = _mock_response(
            _envelope({"id": "1", "shortId": "mem-1"}),
        )
        client.keep("HL", body="body text", team="acme", collection="docs")
        client._client.post.assert_called_once()
        args, kwargs = client._client.post.call_args
        assert args[0] == "/v1/team-keep"
        assert kwargs["json"]["team"] == "acme"
        assert kwargs["json"]["collection"] == "docs"
        assert kwargs["json"]["content"] == "body text"


# ── unassociate ──────────────────────────────────────────────────────────


class TestUnassociate:

    def test_remove_associations(self, client):
        client._client.request.return_value = _mock_response(
            _envelope({"removed": [{"id": "lnk-1"}], "notFound": []}),
        )
        targets = [{"memory_id": "mem-2", "relation_type": "supports"}]
        client.remove_associations("mem-1", targets)
        client._client.request.assert_called_once()
        args, kwargs = client._client.request.call_args
        assert args[0] == "DELETE"
        assert args[1] == "/v1/memories/mem-1/associations"
        assert kwargs["json"]["targets"] == targets

    def test_remove_links_by_ids(self, client):
        client._client.request.return_value = _mock_response(
            _envelope({"removed": [{"id": "lnk-1"}], "notFound": []}),
        )
        client.remove_links_by_ids(["lnk-1", "lnk-2"])
        client._client.request.assert_called_once()
        args, kwargs = client._client.request.call_args
        assert args[0] == "DELETE"
        assert args[1] == "/v1/links"
        assert kwargs["json"]["link_ids"] == ["lnk-1", "lnk-2"]


# ── teams REST ───────────────────────────────────────────────────────────


class TestTeams:

    def test_list_teams(self, client):
        client._client.get.return_value = _mock_response(
            _envelope([{"id": "t1", "slug": "acme", "name": "Acme"}]),
        )
        result = client.list_teams()
        client._client.get.assert_called_once_with("/v1/teams", params=None)
        assert len(result["items"]) == 1

    def test_get_team(self, client):
        client._client.get.return_value = _mock_response(
            _envelope({"id": "t1", "slug": "acme"}),
        )
        client.get_team("t1", include="members,collections")
        args, kwargs = client._client.get.call_args
        assert args[0] == "/v1/teams/t1"
        assert kwargs["params"]["include"] == "members,collections"

    def test_create_team_collection(self, client):
        client._client.post.return_value = _mock_response(
            _envelope({"id": "c1", "slug": "docs"}),
        )
        client.create_team_collection("t1", "Docs", slug="docs")
        args, kwargs = client._client.post.call_args
        assert args[0] == "/v1/teams/t1/collections"
        assert kwargs["json"] == {"name": "Docs", "slug": "docs"}

    def test_list_team_members(self, client):
        client._client.get.return_value = _mock_response(_envelope([]))
        client.list_team_members("t1")
        client._client.get.assert_called_once_with("/v1/teams/t1/members")

    def test_invite_team_member(self, client):
        client._client.post.return_value = _mock_response(
            _envelope({"id": "m1", "role": "editor"}),
        )
        client.invite_team_member("t1", "a@b.com", "editor")
        args, kwargs = client._client.post.call_args
        assert args[0] == "/v1/teams/t1/invites"
        assert kwargs["json"] == {"email": "a@b.com", "role": "editor"}

    def test_set_member_role(self, client):
        client._client.post.return_value = _mock_response(
            _envelope({"id": "m1", "role": "manager"}),
        )
        client.set_member_role("t1", "m1", "manager")
        args, kwargs = client._client.post.call_args
        assert args[0] == "/v1/teams/t1/members/m1/role"
        assert kwargs["json"] == {"role": "manager"}

    def test_team_keep(self, client):
        client._client.post.return_value = _mock_response(
            _envelope({"id": "1", "shortId": "mem-1"}),
        )
        client.team_keep(team="acme", collection="docs", content="Hello", headline="Hi")
        args, kwargs = client._client.post.call_args
        assert args[0] == "/v1/team-keep"
        assert kwargs["json"]["team"] == "acme"
        assert kwargs["json"]["collection"] == "docs"
        assert kwargs["json"]["content"] == "Hello"
        assert kwargs["json"]["headline"] == "Hi"
