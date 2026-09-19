from typing import Any

import httpx

from .models import AuthenticatedUser


class SupabaseError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class SupabaseClient:
    """Minimal Auth/PostgREST client that keeps user RLS context intact."""

    def __init__(
        self,
        url: str,
        publishable_key: str,
        secret_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.publishable_key = publishable_key
        self.secret_key = secret_key
        self.client = client or httpx.Client(timeout=30.0)

    def get_user(self, token: str) -> AuthenticatedUser:
        response = self.client.get(
            f"{self.url}/auth/v1/user",
            headers=self._headers(token),
        )
        if response.status_code in (401, 403):
            raise SupabaseError("Invalid or expired access token", 401)
        data = self._json(response)
        return AuthenticatedUser(id=data["id"], email=data.get("email"))

    def select(
        self,
        table: str,
        token: str,
        *,
        filters: dict[str, str] | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"select": "*"}
        for field, value in (filters or {}).items():
            params[field] = f"eq.{value}"
        if order:
            params["order"] = order
        response = self.client.get(
            f"{self.url}/rest/v1/{table}",
            params=params,
            headers=self._headers(token),
        )
        return self._json(response)

    def insert(
        self, table: str, token: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        response = self.client.post(
            f"{self.url}/rest/v1/{table}",
            json=values,
            headers={**self._headers(token), "Prefer": "return=representation"},
        )
        rows = self._json(response)
        if not rows:
            raise SupabaseError(f"Supabase returned no inserted {table} row")
        return rows[0]

    def update(
        self,
        table: str,
        token: str,
        row_id: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        response = self.client.patch(
            f"{self.url}/rest/v1/{table}",
            params={"id": f"eq.{row_id}"},
            json=values,
            headers={**self._headers(token), "Prefer": "return=representation"},
        )
        rows = self._json(response)
        if not rows:
            raise SupabaseError(f"Resource not found or update not permitted", 404)
        return rows[0]

    def delete(self, table: str, token: str, row_id: str) -> dict[str, Any]:
        """Delete one row by id.

        Runs under the caller's token, not the service key, so row-level
        security still decides whether this user may delete this row.
        """
        response = self.client.delete(
            f"{self.url}/rest/v1/{table}",
            params={"id": f"eq.{row_id}"},
            headers={**self._headers(token), "Prefer": "return=representation"},
        )
        rows = self._json(response)
        if not rows:
            raise SupabaseError("Resource not found or delete not permitted", 404)
        return rows[0]

    def rpc(self, function: str, token: str, values: dict[str, Any]) -> Any:
        response = self.client.post(
            f"{self.url}/rest/v1/rpc/{function}",
            json=values,
            headers=self._headers(token),
        )
        return self._json(response)

    def _headers(self, token: str, *, service: bool = False) -> dict[str, str]:
        key = self.secret_key if service else self.publishable_key
        bearer = self.secret_key if service else token
        return {"apikey": key, "Authorization": f"Bearer {bearer}"}

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            data = response.json()
        except ValueError:
            data = response.text[:500]
        if response.is_error:
            message = data.get("message", data) if isinstance(data, dict) else data
            status = 401 if response.status_code in (401, 403) else response.status_code
            raise SupabaseError(str(message), status)
        return data
