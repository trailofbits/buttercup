def gen_test_case_short_cookie() -> bytes:
    request = (
        "GET / HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Cookie: uid=shortcookie\r\n"
        "Accept: */*\r\n\r\n"
    )
    return request.encode()


def gen_test_case_invalid_base64() -> bytes:
    request = (
        "GET / HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Cookie: uid=invalid_base64_cookie\r\n"
        "Accept: */*\r\n\r\n"
    )
    return request.encode()
