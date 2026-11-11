from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from wiroapi.client import WiroClient, WiroError


class WiroMediaProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        """Read one task row from the project. It costs nothing and fails on a wrong key or signature."""
        try:
            WiroClient(credentials).check_credentials()
        except WiroError as exc:
            raise ToolProviderCredentialValidationError(str(exc)) from exc
