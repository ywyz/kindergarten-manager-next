"""R9: diagnostics must never record the raw launch token."""

from d0_jsdiag import session_diag


def test_session_diag_never_includes_token_value():
    secret = "SUPER-SECRET-TOKEN-VALUE"
    diag = session_diag({"launch_token": secret})
    assert diag == {"has_token": True}
    assert secret not in repr(diag)


def test_session_diag_without_token():
    assert session_diag({}) == {"has_token": False}
    assert session_diag(None) == {"has_token": False}
    assert session_diag({"launch_token": ""}) == {"has_token": False}
