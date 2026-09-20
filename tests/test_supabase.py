import httpx
import pytest
import respx

from product_voice.supabase import SupabaseClient, SupabaseError


def make_client() -> SupabaseClient:
    return SupabaseClient(
        "https://example.supabase.co", "publishable-key", "secret-key"
    )


@respx.mock
def test_get_user_preserves_user_token() -> None:
    route = respx.get("https://example.supabase.co/auth/v1/user").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "6f036d18-d16b-4720-88e8-2db2b2f46c84",
                "email": "person@example.com",
            },
        )
    )

    user = make_client().get_user("user-access-token")

    assert str(user.id) == "6f036d18-d16b-4720-88e8-2db2b2f46c84"
    assert route.calls[0].request.headers["authorization"] == "Bearer user-access-token"
    assert route.calls[0].request.headers["apikey"] == "publishable-key"


@respx.mock
def test_invalid_token_becomes_unauthorized() -> None:
    respx.get("https://example.supabase.co/auth/v1/user").mock(
        return_value=httpx.Response(401, json={"message": "invalid JWT"})
    )

    with pytest.raises(SupabaseError) as error:
        make_client().get_user("bad-token")

    assert error.value.status_code == 401


@respx.mock
def test_select_uses_rls_user_context() -> None:
    route = respx.get("https://example.supabase.co/rest/v1/products").mock(
        return_value=httpx.Response(200, json=[])
    )

    rows = make_client().select(
        "products",
        "user-access-token",
        filters={"organization_id": "org-id"},
    )

    assert rows == []
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer user-access-token"
    assert "organization_id=eq.org-id" in str(request.url)
