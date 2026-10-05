"""Explicit bearer authentication prevents Requests from borrowing ~/.netrc auth."""
from requests.auth import AuthBase


class BearerAuth(AuthBase):
    def __init__(self, token):
        self._token = token

    def __call__(self, request):
        request.headers['Authorization'] = 'Bearer ' + self._token
        return request
