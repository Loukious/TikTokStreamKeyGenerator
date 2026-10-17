"""Typed hosted-signer failures and a versioned proxy error-report contract."""
from enum import Enum
import json
import os
from pathlib import Path


class SignerFailureKind(Enum):
    QUOTA = 'quota'
    SUBSCRIPTION = 'subscription'
    UNAVAILABLE = 'unavailable'


class HostedSignerError(RuntimeError):
    def __init__(self, message, *, kind=SignerFailureKind.UNAVAILABLE, status_code=None):
        super().__init__(message)
        self.kind = SignerFailureKind(kind)
        self.status_code = status_code

    @classmethod
    def from_http(cls, status_code, message):
        kind = (SignerFailureKind.QUOTA if status_code == 429 else
                SignerFailureKind.SUBSCRIPTION if status_code in (401, 403) else
                SignerFailureKind.UNAVAILABLE)
        return cls(message, kind=kind, status_code=status_code)


class OperationError(RuntimeError):
    def __init__(self, operation, cause):
        super().__init__(f'{operation}:\n\n{cause}')
        self.__cause__ = cause


def hosted_signer_failure(error):
    """Follow explicit exception causes; never infer origin from message text."""
    seen = set()
    while isinstance(error, BaseException) and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, HostedSignerError):
            return error
        error = error.__cause__
    return None


def write_proxy_error(path, error):
    """Report the terminal failure, independently of human-readable logs.

    Each launch supplies a unique path. Failure to write the report (e.g. disk
    full) leaves the parent with an ordinary proxy error, never a guessed cause.
    """
    if not path:
        return
    signer = hosted_signer_failure(error)
    record = {'version': 1, 'source': 'hosted_signer' if signer else 'local',
              'message': str(error)[:16000], 'exception_type': type(error).__name__}
    if signer:
        record.update(kind=signer.kind.value, status_code=signer.status_code)
    temporary = str(path) + '.tmp'
    try:
        with open(temporary, 'w', encoding='utf-8') as file:
            json.dump(record, file)
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError):
        pass
    finally:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass


def read_proxy_error(path):
    if not path:
        return None
    try:
        with open(path, 'r', encoding='utf-8') as file:
            raw = file.read(65537)
        if len(raw) > 65536:
            return None
        record = json.loads(raw)
        if (not isinstance(record, dict) or type(record.get('version')) is not int or
                record['version'] != 1 or not isinstance(record.get('message'), str)):
            return None
        if record.get('source') == 'local':
            return RuntimeError(record['message'])
        if record.get('source') != 'hosted_signer':
            return None
        status = record.get('status_code')
        if status is not None and (type(status) is not int or not 100 <= status <= 599):
            return None
        return HostedSignerError(record['message'], kind=SignerFailureKind(record.get('kind')),
                                 status_code=status)
    except (OSError, ValueError, TypeError):
        return None
