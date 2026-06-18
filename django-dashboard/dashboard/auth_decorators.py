import hashlib
from django.http import JsonResponse
from django.utils import timezone
from .models import DeveloperAPIKey, CLISession


def require_api_key(view_func):
    def _wrapped_view(request, *args, **kwargs):
        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JsonResponse({"error": "Missing or malformed Authorization header token."}, status=401)

        raw_key = auth_header.split(" ")[1]
        hashed_input = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        try:
            key_record = DeveloperAPIKey.objects.get(hashed_key=hashed_input, is_active=True)
            request.organization_name = key_record.organization_name
        except DeveloperAPIKey.DoesNotExist:
            return JsonResponse({"error": "Invalid or revoked corporate API key credentials."}, status=403)

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def require_cli_session(view_func):
    def _wrapped_view(request, *args, **kwargs):
        auth_header = request.META.get("HTTP_AUTHORIZATION")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JsonResponse({"error": "Missing or malformed Authorization header token."}, status=401)

        raw_token = auth_header.split(" ")[1]
        hashed = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        try:
            session = CLISession.objects.get(
                session_token_hash=hashed,
                is_active=True,
                expires_at__gt=timezone.now(),
            )
            request.organization_name = session.organization_name
            request.cli_session = session
        except CLISession.DoesNotExist:
            return JsonResponse({"error": "Invalid or expired session token. Run 'patch-bot --auth' to re-authenticate."}, status=403)

        return view_func(request, *args, **kwargs)

    return _wrapped_view
