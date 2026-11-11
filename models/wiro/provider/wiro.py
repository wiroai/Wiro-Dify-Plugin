from collections.abc import Mapping

from dify_plugin import ModelProvider
from dify_plugin.errors.model import CredentialsValidateFailedError

from models._wiro import WiroGatewayError, check_key


class WiroModelProvider(ModelProvider):
    def validate_provider_credentials(self, credentials: Mapping) -> None:
        """Check the key against the free model list instead of sending a paid chat request."""
        try:
            check_key(credentials)
        except WiroGatewayError as exc:
            raise CredentialsValidateFailedError(str(exc)) from exc
